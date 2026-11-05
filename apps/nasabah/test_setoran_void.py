"""PIL-428: a voided setoran in the nasabah views; shown as dibatalkan, never counted."""

from decimal import Decimal
from typing import Any

from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, Transaksi, User
from apps.waste_catalog.api import buat_jenis_sampah


class VoidedSetoranNasabahTests(APITestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(
            nama="Bank Nasabah", alamat="Depok", kota="Depok", no_hp_pic="+628123456789"
        )
        self.pengelola = User.objects.create_user(
            email="pengurus@example.test",
            nama="Pengelola",
            bank_sampah=self.bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        self.akun = User.objects.create_user(
            email="budi@example.test",
            nama="Budi",
            role=User.Role.NASABAH,
            is_profile_complete=True,
        )
        self.nasabah = Nasabah.objects.create(
            bank_sampah=self.bank,
            user=self.akun,
            nomor="NAS-0001",
            nama="Budi",
            no_hp="+628111111111",
            alamat="Jl. A",
        )
        pet = buat_jenis_sampah(
            bank_sampah=self.bank, nomor="PET", nama_sampah="Botol PET", harga_per_kg=Decimal(3000)
        )
        self.client.force_authenticate(self.pengelola)
        for berat in ("1.000", "2.000"):
            response = self.client.post(
                "/api/v1/transaksi",
                {
                    "nasabah_id": str(self.nasabah.id),
                    "items": [{"jenis_sampah_id": str(pet.id), "berat": berat}],
                },
                format="json",
            )
            self.assertEqual(response.status_code, 201)
        self.batal = Transaksi.objects.get(total_nilai=Decimal(6000))
        response = self.client.post(
            f"/api/v1/transaksi/{self.batal.id}/batalkan", {"alasan": "Dobel"}, format="json"
        )
        self.assertEqual(response.status_code, 200)

    def _status_per_id(self, rows: list[dict[str, Any]]) -> dict[str, str]:
        return {str(row["id"]): row["status"] for row in rows}

    def test_pengurus_ringkasan_does_not_count_the_voided_setoran(self) -> None:
        response = self.client.get(f"/api/v1/nasabah/{self.nasabah.id}")

        ringkasan = response.data["ringkasan_transaksi"]
        self.assertEqual(ringkasan["jumlah_transaksi"], 1)
        self.assertEqual(Decimal(ringkasan["total_kg"]), Decimal(1))

    def test_nasabah_riwayat_shows_the_voided_setoran_as_dibatalkan(self) -> None:
        self.client.force_authenticate(self.akun)

        for params in ({}, {"periode": "semua", "tipe": "semua"}):
            with self.subTest(params=params):
                response = self.client.get("/api/v1/nasabah/me/riwayat", params)

                statuses = self._status_per_id(response.data["results"])
                self.assertEqual(statuses[str(self.batal.id)], "dibatalkan")
                self.assertEqual(sorted(statuses.values()), ["dibatalkan", "tercatat"])

    def test_nasabah_beranda_and_detail_show_the_void(self) -> None:
        self.client.force_authenticate(self.akun)

        beranda = self.client.get("/api/v1/nasabah/me/beranda")
        detail = self.client.get(f"/api/v1/nasabah/me/riwayat/{self.batal.id}")

        terbaru = self._status_per_id(beranda.data["aktivitas_terbaru"])
        self.assertEqual(terbaru[str(self.batal.id)], "dibatalkan")
        self.assertEqual(detail.data["status"], "dibatalkan")
