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
