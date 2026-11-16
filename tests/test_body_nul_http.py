"""Kontrak HTTP: nilai body mentah tidak lagi sampai ke query sebelum divalidasi.

Lanjutan #172: NUL pada `search` sudah 422, tetapi `kode` pada edit jenis
sampah dan nasabah dicek duplikatnya dari `request.data` mentah, sebelum
serializer berjalan. NUL di sana membuat psycopg DataError (500).
"""

from decimal import Decimal

from rest_framework.test import APITestCase

from api.models import BankSampah, User
from apps.waste_catalog.api import buat_jenis_sampah

KODE_TIDAK_VALID = ("A\x00B", ["PET"], {"kode": "PET"})


class _PengurusFixture(APITestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(nama="Melati", no_hp_pic="081200")
        self.pengurus = User.objects.create_user(
            email="pengurus-body@example.test",
            nama="Pengurus",
            bank_sampah=self.bank,
            role=User.Role.PENGELOLA,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        self.client.force_authenticate(self.pengurus)


class KodeJenisSampahTests(_PengurusFixture):
    def setUp(self) -> None:
        super().setUp()
        self.jenis = buat_jenis_sampah(
            bank_sampah=self.bank,
            nomor="PET",
            nama_sampah="Botol PET",
            harga_per_kg=Decimal(3000),
        )

    def test_kode_tidak_valid_ditolak_422_bukan_500(self) -> None:
        for kode in KODE_TIDAK_VALID:
            with self.subTest(kode=kode):
                response = self.client.patch(
                    f"/api/v1/jenis-sampah/{self.jenis.id}", {"kode": kode}, format="json"
                )

                self.assertEqual(response.status_code, 422)
                self.assertIn("kode", response.json()["errors"])
