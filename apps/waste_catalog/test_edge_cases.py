from decimal import Decimal

from rest_framework import serializers
from rest_framework.test import APITestCase

from api.models import BankSampah, User
from apps.waste_catalog.api import buat_jenis_sampah
from apps.waste_catalog.serializers import JenisSampahSerializer


class JenisSampahEdgeCaseTests(APITestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(nama="Bank Katalog", alamat="Depok", kota="Depok")
        pengelola = User.objects.create_user(
            email="katalog@example.test",
            nama="Pengurus",
            bank_sampah=self.bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        self.client.force_authenticate(pengelola)

    def test_waste_code_must_be_unique_within_the_bank(self) -> None:
        payload = {
            "kode": "PET",
            "nama_sampah": "Botol PET",
            "kategori": "plastik",
            "harga_per_kg": "3000",
        }
        first = self.client.post("/api/v1/jenis-sampah", payload, format="json")
        self.assertEqual(first.status_code, 201, first.data)

        duplicate = self.client.post("/api/v1/jenis-sampah", payload, format="json")

        self.assertEqual(duplicate.status_code, 422)
        self.assertEqual(duplicate.data["errors"]["kode"], ["Kode sampah sudah digunakan"])

    def test_waste_type_string_is_its_name(self) -> None:
        jenis = buat_jenis_sampah(
            bank_sampah=self.bank, nomor="PET", nama_sampah="Botol PET", harga_per_kg=Decimal(3000)
        )

        self.assertEqual(str(jenis), "Botol PET")


class JenisSampahSerializerGuardTests(APITestCase):
    def test_blank_code_and_nine_digit_price_cap_are_enforced_by_the_validators(self) -> None:
        # Field-level blank and max_digits checks fire first over HTTP; these
        # validators remain the backstop for values that reach them directly.
        serializer = JenisSampahSerializer()

        with self.assertRaisesRegex(serializers.ValidationError, "Kode sampah wajib diisi"):
            serializer.validate_kode("  ")
        with self.assertRaisesRegex(serializers.ValidationError, "Harga maksimal 9 digit"):
            serializer.validate_harga_per_kg(Decimal(1000000000))
