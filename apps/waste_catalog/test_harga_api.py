"""PIL-304: API harga jenis sampah ber-versi untuk pengurus."""

from datetime import timedelta
from typing import Any

from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, HargaSampah, User


class HargaApiTestCase(APITestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(
            nama="Bank Sampah BTH",
            alamat="Depok",
            kota="Depok",
            no_hp_pic="+628123456789",
            status=BankSampah.Status.ACTIVE,
        )
        self.user = User.objects.create_user(
            email="sari@example.com",
            nama="Ibu Sari",
            bank_sampah=self.bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        self.auth_as(self.user)

    def auth_as(self, user: User) -> None:
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def buat_jenis(self, harga: int = 3500, kode: str = "PLS-001") -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/jenis-sampah",
            {
                "kode": kode,
                "nama_sampah": "Plastik PET",
                "kategori": "plastik",
                "harga_per_kg": harga,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return dict(response.data)


class BuatJenisSampahTests(HargaApiTestCase):
    def test_initial_price_is_recorded_as_a_version_starting_now_with_its_author(self) -> None:
        sebelum = timezone.now()

        jenis = self.buat_jenis(harga=3500)

        versi = HargaSampah.objects.get(jenis_sampah_id=jenis["id"])
        self.assertEqual(versi.harga_per_kg, 3500)
        self.assertEqual(versi.bank_sampah, self.bank)
        self.assertEqual(versi.dibuat_oleh, self.user)
        self.assertGreaterEqual(versi.berlaku_mulai, sebelum - timedelta(seconds=1))
        self.assertLessEqual(versi.berlaku_mulai, timezone.now())
