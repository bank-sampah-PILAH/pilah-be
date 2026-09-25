"""Shared fixtures for the regression net: base test case plus payload builders."""

from typing import Any, ClassVar

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, Nasabah, Saldo, User


def nasabah_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kode": "NAS-0001",
        "nama": "Budi Santoso",
        "jenis_kelamin": "laki-laki",
        "tanggal_lahir": "1990-01-01",
        "no_hp": "081234567890",
        "alamat": "Jl. Anggrek No. 3",
    }
    payload.update(overrides)
    if "no_hp" not in overrides and payload["kode"] != "NAS-0001":
        payload["no_hp"] = "081234567891"
    return payload


def logo(name: str = "foto.png") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"fakepngdata", content_type="image/png")


def twilio_env(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "TWILIO_ACCOUNT_SID": "ACx",
        "TWILIO_AUTH_TOKEN": "tok",
        "TWILIO_API_KEY_SID": "",
        "TWILIO_API_KEY_SECRET": "",
        "TWILIO_WHATSAPP_FROM": "whatsapp:+1000",
        "TWILIO_MESSAGING_SERVICE_SID": "",
        "TWILIO_CONTENT_SID": "",
        "WHATSAPP_GATEWAY_URL": "",
    }
    base.update(overrides)
    return override_settings(**base)


def gateway_env() -> Any:
    return twilio_env(
        TWILIO_ACCOUNT_SID="",
        TWILIO_AUTH_TOKEN="",
        TWILIO_API_KEY_SID="",
        TWILIO_API_KEY_SECRET="",
        TWILIO_WHATSAPP_FROM="",
        TWILIO_MESSAGING_SERVICE_SID="",
        TWILIO_CONTENT_SID="",
        WHATSAPP_GATEWAY_URL="https://wa.example/hook",
    )


class RegressionTestCase(APITestCase):
    _fake_tokens: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._fake_tokens = override_settings(DEBUG=True, PILAH_ALLOW_FAKE_GOOGLE_TOKEN=True)
        cls._fake_tokens.enable()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._fake_tokens.disable()
        super().tearDownClass()

    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(
            nama="Bank Sampah BTH", alamat="Depok", kota="Depok", no_hp_pic="+628123456789"
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

    def make_user(self, email: str, role: str, bank: Any = None) -> User:
        return User.objects.create_user(
            email=email,
            nama=email,
            role=role,
            bank_sampah=bank,
            is_profile_complete=True,
        )

    def fresh_pengelola(self, email: str) -> User:
        return User.objects.create_user(email=email, nama="Baru", role=User.Role.PENGELOLA)

    def make_nasabah(self, kode: str = "NAS-0001") -> Nasabah:
        nasabah = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor=kode,
            nama="Ahmad Ridwan",
            no_hp="+628123456789",
            alamat="Jl. Mawar No. 12",
        )
        Saldo.objects.create(nasabah=nasabah)
        return nasabah

    def make_jenis(self, kode: str = "PLS-001") -> str:
        response = self.client.post(
            "/api/v1/jenis-sampah",
            {
                "kode": kode,
                "nama_sampah": "Plastik PET",
                "kategori": "plastik",
                "deskripsi": "Botol bening",
                "harga_per_kg": 3500,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        result: str = response.data["id"]
        return result

    def make_transaksi(self) -> str:
        nasabah = self.make_nasabah()
        jenis_id = self.make_jenis()
        created = self.client.post(
            "/api/v1/transaksi",
            {
                "nasabah_id": str(nasabah.id),
                "items": [{"jenis_sampah_id": jenis_id, "berat": "2.500"}],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        result: str = created.data["id"]
        return result
