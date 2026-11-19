"""Kontrak HTTP: `nasabah_id` yang bukan UUID ditolak 422, bukan 500 (PIL-482).

Sebelumnya `transaksi` dan `pencairan` meneruskan nilai mentah ke ORM, sehingga
`?nasabah_id=abc` memunculkan ValidationError Django yang tidak tertangani (500).
"""

from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, User

ENDPOINTS = ("aktivitas", "transaksi", "pencairan")


class NasabahIdTidakValidTests(APITestCase):
    def setUp(self) -> None:
        bank = BankSampah.objects.create(nama="Melati", no_hp_pic="081200")
        self.pengurus = User.objects.create_user(
            email="pengurus-filter@example.test",
            nama="Pengurus",
            bank_sampah=bank,
            role=User.Role.PENGELOLA,
            is_profile_complete=True,
        )
        akun = User.objects.create_user(
            email="nasabah-filter@example.test",
            nama="Siti",
            role=User.Role.NASABAH,
            is_profile_complete=True,
        )
        self.nasabah = Nasabah.objects.create(
            bank_sampah=bank, user=akun, nomor="001", nama="Siti", alamat="Depok", no_hp="081201"
        )

    def test_nasabah_id_bukan_uuid_ditolak_422_di_semua_endpoint(self) -> None:
        self.client.force_authenticate(self.pengurus)
        for path in ENDPOINTS:
            for raw in ("abc", "123", "00000000-0000-0000-0000-00000000000Z"):
                with self.subTest(path=path, raw=raw):
                    response = self.client.get(f"/api/v1/{path}?nasabah_id={raw}")

                    self.assertEqual(response.status_code, 422)
                    self.assertIn("nasabah_id", response.json()["errors"])

    def test_nasabah_id_uuid_tetap_menyaring(self) -> None:
        self.client.force_authenticate(self.pengurus)
        for path in ENDPOINTS:
            with self.subTest(path=path):
                response = self.client.get(f"/api/v1/{path}?nasabah_id={self.nasabah.id}")

                self.assertEqual(response.status_code, 200)
