"""UAT 2026-11: kode jenis sampah ternomori otomatis."""

from rest_framework.test import APITestCase

from api.models import BankSampah, User
from apps.waste_catalog.models import JenisSampah


class KodeJenisOtomatisTests(APITestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(nama="Bank Jenis", alamat="Depok", kota="Depok")
        self.pengelola = User.objects.create_user(
            email="pengurus-jenis@example.test",
            nama="Pengurus Jenis",
            bank_sampah=self.bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        self.client.force_authenticate(self.pengelola)

    def test_buat_jenis_tanpa_kode_mendapat_kode_otomatis(self) -> None:
        response = self.client.post(
            "/api/v1/jenis-sampah",
            {"nama_sampah": "Plastik Uji", "kategori": "plastik", "harga_per_kg": "1500"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["kode"], "SM-001")

    def test_nomor_berikut_jenis_menambah(self) -> None:
        JenisSampah.objects.create(bank_sampah=self.bank, nomor="SM-012", nama_sampah="Kaca")
        self.assertEqual(JenisSampah.nomor_berikut(self.bank.id), "SM-013")

    def test_dua_tanpa_kode_berturut_mendapat_kode_berbeda(self) -> None:
        body = {"nama_sampah": "Kertas Uji", "kategori": "kertas", "harga_per_kg": "800"}
        first = self.client.post("/api/v1/jenis-sampah", body, format="json")
        second = self.client.post(
            "/api/v1/jenis-sampah", {**body, "nama_sampah": "Logam Uji"}, format="json"
        )
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(first.data["kode"], "SM-001")
        self.assertEqual(second.data["kode"], "SM-002")
