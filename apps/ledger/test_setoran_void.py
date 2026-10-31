"""PIL-428: pengurus membatalkan (void) setoran. Datanya tetap ada, hanya ditandai dibatalkan."""

from decimal import Decimal
from typing import Any

from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, Saldo, Transaksi, User
from apps.waste_catalog.api import buat_jenis_sampah


class SetoranVoidTests(APITestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(
            nama="Bank Void", alamat="Depok", kota="Depok", no_hp_pic="+628123456789"
        )
        self.pengelola = User.objects.create_user(
            email="void@example.test",
            nama="Pengelola",
            bank_sampah=self.bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        self.nasabah = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-0001",
            nama="Budi",
            no_hp="+628111111111",
            alamat="Jl. A",
        )
        self.pet = buat_jenis_sampah(
            bank_sampah=self.bank, nomor="PET", nama_sampah="Botol PET", harga_per_kg=Decimal(3000)
        )
        self.client.force_authenticate(self.pengelola)
        self.transaksi = self._setor("2.000")

    def _setor(self, berat: str) -> Transaksi:
        response = self.client.post(
            "/api/v1/transaksi",
            {
                "nasabah_id": str(self.nasabah.id),
                "items": [{"jenis_sampah_id": str(self.pet.id), "berat": berat}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        return Transaksi.objects.get(pk=response.data["id"])

    def _batalkan(self, transaksi: Transaksi | None = None, **body: Any) -> Any:
        body.setdefault("alasan", "Salah nasabah")
        target = transaksi or self.transaksi
        return self.client.post(f"/api/v1/transaksi/{target.id}/batalkan", body, format="json")

    def _saldo(self) -> Decimal:
        return Saldo.objects.get(nasabah=self.nasabah).total_saldo

    def test_void_marks_the_setoran_and_takes_it_out_of_the_saldo(self) -> None:
        response = self._batalkan()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "dibatalkan")
        self.assertEqual(response.data["alasan_batal"], "Salah nasabah")
        self.assertEqual(response.data["dibatalkan_oleh"], str(self.pengelola.id))
        self.assertEqual(response.data["dibatalkan_oleh_nama"], "Pengelola")
        self.assertIsNotNone(response.data["dibatalkan_pada"])
        self.assertEqual(self._saldo(), Decimal(0))
        # Soft delete: the row and its items stay.
        self.assertTrue(Transaksi.objects.filter(pk=self.transaksi.pk).exists())
        self.assertEqual(self.transaksi.items.count(), 1)

    def test_alasan_is_required(self) -> None:
        response = self._batalkan(alasan="")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.data["errors"]["alasan"], ["Alasan pembatalan wajib diisi"])
        self.assertEqual(self._status(), Transaksi.Status.TERCATAT)
        self.assertEqual(self._saldo(), Decimal(6000))

    def test_other_banks_setoran_is_not_found(self) -> None:
        other = BankSampah.objects.create(
            nama="Bank Lain", alamat="Depok", kota="Depok", no_hp_pic="+628123450000"
        )
        intruder = User.objects.create_user(
            email="lain@example.test",
            nama="Lain",
            bank_sampah=other,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        self.client.force_authenticate(intruder)

        response = self._batalkan()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self._status(), Transaksi.Status.TERCATAT)

    def test_nasabah_cannot_void_their_own_setoran(self) -> None:
        akun = User.objects.create_user(
            email="budi@example.test", nama="Budi", role=User.Role.NASABAH
        )
        Nasabah.objects.filter(pk=self.nasabah.pk).update(user=akun)
        self.client.force_authenticate(akun)

        response = self._batalkan()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._status(), Transaksi.Status.TERCATAT)

    def test_a_voided_setoran_cannot_be_voided_again(self) -> None:
        self._batalkan()

        response = self._batalkan(alasan="Lagi")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"], "Setoran sudah dibatalkan")
        self.assertEqual(self._saldo(), Decimal(0))
        self.transaksi.refresh_from_db()
        self.assertEqual(self.transaksi.alasan_batal, "Salah nasabah")

    def test_a_voided_setoran_cannot_be_edited(self) -> None:
        self._batalkan()

        response = self.client.patch(
            f"/api/v1/transaksi/{self.transaksi.id}",
            {
                "items": [{"jenis_sampah_id": str(self.pet.id), "berat": "3.000"}],
                "alasan": "Salah timbang",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._saldo(), Decimal(0))
        self.assertEqual(self.transaksi.revisi.count(), 0)

    def test_a_voided_setoran_sends_no_whatsapp_receipt(self) -> None:
        self._batalkan()

        response = self.client.post(f"/api/v1/transaksi/{self.transaksi.id}/notify-wa")

        self.assertEqual(response.status_code, 409)

    def _status(self) -> str:
        return Transaksi.objects.values_list("status", flat=True).get(pk=self.transaksi.pk)
