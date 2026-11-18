"""Kontrak HTTP: karakter kontrol pada parameter `search` ditolak 422, bukan 500
(temuan scan s3w2: NUL membuat psycopg DataError)."""

from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, User

ENDPOINTS = ("aktivitas", "transaksi", "pencairan", "nasabah", "jenis-sampah")


class PencarianKarakterKontrolTests(APITestCase):
    def setUp(self) -> None:
        bank = BankSampah.objects.create(nama="Melati", no_hp_pic="081200")
        self.pengurus = User.objects.create_user(
            email="pengurus-cari@example.test",
            nama="Pengurus",
            bank_sampah=bank,
            role=User.Role.PENGELOLA,
            is_profile_complete=True,
        )
        akun = User.objects.create_user(
            email="nasabah-cari@example.test",
            nama="Siti",
            role=User.Role.NASABAH,
            is_profile_complete=True,
        )
        Nasabah.objects.create(
            bank_sampah=bank, user=akun, nomor="001", nama="Siti", alamat="Depok", no_hp="081201"
        )

    def test_nul_dan_kontrol_c0_ditolak_422_di_semua_endpoint(self) -> None:
        self.client.force_authenticate(self.pengurus)
        for path in ENDPOINTS:
            for raw in ("a%00b", "a%01b", "a%1Fb"):
                with self.subTest(path=path, raw=raw):
                    response = self.client.get(f"/api/v1/{path}?search={raw}")

                    self.assertEqual(response.status_code, 422)
                    self.assertIn("search", response.json()["errors"])

    def test_pencarian_biasa_tetap_diterima(self) -> None:
        self.client.force_authenticate(self.pengurus)
        for path in ENDPOINTS:
            with self.subTest(path=path):
                response = self.client.get(f"/api/v1/{path}?search=Siti%20Aminah")

                self.assertEqual(response.status_code, 200)
