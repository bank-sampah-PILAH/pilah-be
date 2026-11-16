"""Kontrak HTTP: nilai body mentah tidak lagi sampai ke query sebelum divalidasi.

Lanjutan #172: NUL pada `search` sudah 422, tetapi `kode` pada edit jenis
sampah dan nasabah dicek duplikatnya dari `request.data` mentah, sebelum
serializer berjalan. NUL di sana membuat psycopg DataError (500).
"""

from decimal import Decimal

from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, User
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

    def test_kode_milik_jenis_lain_tetap_ditolak_dan_kode_sendiri_diterima(self) -> None:
        buat_jenis_sampah(
            bank_sampah=self.bank, nomor="HDPE", nama_sampah="Galon", harga_per_kg=Decimal(2000)
        )
        url = f"/api/v1/jenis-sampah/{self.jenis.id}"

        ganda = self.client.patch(url, {"kode": " HDPE "}, format="json")
        sendiri = self.client.patch(url, {"kode": "PET"}, format="json")

        self.assertEqual(ganda.status_code, 422)
        self.assertEqual(ganda.json()["errors"]["kode"], ["Kode sampah sudah digunakan"])
        self.assertEqual(sendiri.status_code, 200)


class KodeNasabahTests(_PengurusFixture):
    def setUp(self) -> None:
        super().setUp()
        self.nasabah = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-001",
            nama="Siti",
            alamat="Jl. Melati 1",
            no_hp="0811",
            email="siti@example.test",
        )
        Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-002",
            nama="Budi",
            alamat="Jl. Melati 2",
            no_hp="0812",
            email="budi@example.test",
        )
        self.url = f"/api/v1/nasabah/{self.nasabah.id}"

    def test_kode_tidak_valid_ditolak_422_bukan_500(self) -> None:
        for kode in KODE_TIDAK_VALID:
            with self.subTest(kode=kode):
                response = self.client.patch(self.url, {"kode": kode}, format="json")

                self.assertEqual(response.status_code, 422)
                self.assertIn("kode", response.json()["errors"])

    def test_kode_milik_nasabah_lain_tetap_ditolak_dan_kode_sendiri_diterima(self) -> None:
        ganda = self.client.patch(self.url, {"kode": " NAS-002 "}, format="json")
        sendiri = self.client.patch(self.url, {"kode": "NAS-001"}, format="json")

        self.assertEqual(ganda.status_code, 422)
        self.assertEqual(ganda.json()["errors"]["kode"], ["ID Nasabah sudah digunakan"])
        self.assertEqual(sendiri.status_code, 200)
