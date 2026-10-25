"""PIL-427: pengurus memperbaiki setoran yang sudah tercatat (berat, jenis, catatan)."""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.utils import timezone
from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, Saldo, Transaksi, User
from apps.waste_catalog.api import buat_jenis_sampah


class SetoranEditTests(APITestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(
            nama="Bank Edit", alamat="Depok", kota="Depok", no_hp_pic="+628123456789"
        )
        self.pengelola = User.objects.create_user(
            email="edit@example.test",
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
        self.kardus = buat_jenis_sampah(
            bank_sampah=self.bank, nomor="KRT", nama_sampah="Kardus", harga_per_kg=Decimal(1000)
        )
        self.client.force_authenticate(self.pengelola)
        response = self.client.post(
            "/api/v1/transaksi",
            {
                "nasabah_id": str(self.nasabah.id),
                "items": [{"jenis_sampah_id": str(self.pet.id), "berat": "2.000"}],
                "catatan": "awal",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.transaksi = Transaksi.objects.get(pk=response.data["id"])

    def _patch(self, **body: Any) -> Any:
        body.setdefault("alasan", "Salah timbang")
        return self.client.patch(f"/api/v1/transaksi/{self.transaksi.id}", body, format="json")

    def _saldo(self) -> Decimal:
        return Saldo.objects.get(nasabah=self.nasabah).total_saldo

    def test_changing_weight_recalculates_total_and_saldo(self) -> None:
        response = self._patch(items=[{"jenis_sampah_id": str(self.pet.id), "berat": "3.000"}])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.data["total_nilai"]), Decimal(9000))
        self.assertEqual(self._saldo(), Decimal(9000))

    def test_changing_waste_type_replaces_items(self) -> None:
        response = self._patch(items=[{"jenis_sampah_id": str(self.kardus.id), "berat": "2.000"}])

        self.assertEqual(response.status_code, 200)
        self.assertEqual([i["nama_sampah_snapshot"] for i in response.data["items"]], ["Kardus"])
        self.assertEqual(self._saldo(), Decimal(2000))

    def test_catatan_only_edit_keeps_saldo(self) -> None:
        response = self._patch(catatan="dikoreksi")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["catatan"], "dikoreksi")
        self.assertEqual(self._saldo(), Decimal(6000))

    def test_edit_without_change_is_rejected_and_writes_no_revision(self) -> None:
        response = self._patch(items=[{"jenis_sampah_id": str(self.pet.id), "berat": "2.000"}])

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.transaksi.revisi.count(), 0)

    def test_alasan_is_required(self) -> None:
        response = self.client.patch(
            f"/api/v1/transaksi/{self.transaksi.id}", {"catatan": "x"}, format="json"
        )

        self.assertEqual(response.status_code, 422)

    def test_edit_keeps_old_version_visible_in_detail(self) -> None:
        self._patch(items=[{"jenis_sampah_id": str(self.pet.id), "berat": "3.000"}])

        detail = self.client.get(f"/api/v1/transaksi/{self.transaksi.id}")

        revisi = detail.data["revisi"]
        self.assertEqual(len(revisi), 1)
        self.assertEqual(revisi[0]["versi"], 1)
        self.assertEqual(Decimal(revisi[0]["total_nilai"]), Decimal(6000))
        self.assertEqual(revisi[0]["catatan"], "awal")
        self.assertEqual(revisi[0]["alasan"], "Salah timbang")
        self.assertEqual(revisi[0]["diubah_oleh"], str(self.pengelola.id))
        self.assertEqual(Decimal(revisi[0]["items"][0]["berat"]), Decimal("2.000"))

    def test_revisions_are_numbered_per_edit(self) -> None:
        self._patch(catatan="satu")
        self._patch(catatan="dua")

        detail = self.client.get(f"/api/v1/transaksi/{self.transaksi.id}")

        self.assertEqual([r["versi"] for r in detail.data["revisi"]], [1, 2])

    def test_edit_that_would_make_saldo_negative_is_rejected(self) -> None:
        Saldo.objects.filter(nasabah=self.nasabah).update(total_saldo=Decimal(1000))

        response = self._patch(items=[{"jenis_sampah_id": str(self.pet.id), "berat": "0.500"}])

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.transaksi.revisi.count(), 0)
        self.assertEqual(self._saldo(), Decimal(1000))

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

        response = self._patch(catatan="x")

        self.assertEqual(response.status_code, 404)

    def test_over_weight_limit_is_rejected(self) -> None:
        response = self._patch(items=[{"jenis_sampah_id": str(self.pet.id), "berat": "501"}])

        self.assertEqual(response.status_code, 422)

    def test_unknown_waste_type_is_rejected(self) -> None:
        response = self._patch(items=[{"jenis_sampah_id": str(uuid.uuid4()), "berat": "1.000"}])

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.transaksi.revisi.count(), 0)

    def test_waste_type_without_a_price_on_the_setoran_date_is_rejected(self) -> None:
        # The setoran predates every price of Kardus, so no harga was in force.
        Transaksi.objects.filter(pk=self.transaksi.pk).update(
            tanggal=self.transaksi.tanggal - timedelta(days=365)
        )

        response = self._patch(items=[{"jenis_sampah_id": str(self.kardus.id), "berat": "1.000"}])

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.transaksi.revisi.count(), 0)

    def test_item_worth_nothing_is_rejected(self) -> None:
        murah = buat_jenis_sampah(
            bank_sampah=self.bank, nomor="MRH", nama_sampah="Murah", harga_per_kg=Decimal(1)
        )
        # Murah only has a price from now on, so move the setoran after it.
        Transaksi.objects.filter(pk=self.transaksi.pk).update(tanggal=timezone.now())

        response = self._patch(items=[{"jenis_sampah_id": str(murah.id), "berat": "0.001"}])

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.transaksi.revisi.count(), 0)
