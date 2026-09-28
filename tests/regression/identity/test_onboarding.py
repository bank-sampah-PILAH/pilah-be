"""Identity contracts: profile completion and bank registration."""

from typing import Any

from api.models import User
from apps.identity.services import OnboardingService
from tests.regression.helpers import RegressionTestCase, logo


class OnboardingRegressionTests(RegressionTestCase):
    def test_complete_profile_then_double_complete(self) -> None:
        user = self.fresh_pengelola("baru@example.com")
        self.auth_as(user)
        done = self.client.put(
            "/api/v1/onboarding/profile",
            {
                "nama": "Pengelola Baru",
                "no_hp": "081234567890",
                "jenis_kelamin": "laki-laki",
                "tanggal_lahir": "1990-01-01",
            },
            format="json",
        )
        self.assertEqual(done.status_code, 200)
        self.assertIn("next_step", done.data)
        again = self.client.put("/api/v1/onboarding/profile", {"nama": "Lain"}, format="json")
        self.assertEqual(again.status_code, 400)

    def test_complete_profile_rejects_bad_fields(self) -> None:
        user = User.objects.create_user(email="cp@example.com", nama="Cp", role=User.Role.PENGELOLA)
        self.auth_as(user)
        for payload in (
            {"jenis_kelamin": "other"},
            {"tanggal_lahir": "2999-01-01"},
            {"nama": "AB"},
        ):
            with self.subTest(payload=payload):
                response = self.client.put("/api/v1/onboarding/profile", payload, format="json")
                self.assertGreaterEqual(response.status_code, 400)

    def test_register_bank_then_pending_blocked_then_double(self) -> None:
        user = self.fresh_pengelola("daftar@example.com")
        self.auth_as(user)
        created = self.client.post(
            "/api/v1/onboarding/bank-sampah",
            {
                "nama": "Bank Sampah Maju",
                "alamat": "Jl. Panjang Sekali No. 100",
                "kota": "Depok",
                "no_hp_pic": "081234567890",
                "foto_kegiatan": logo("kegiatan.png"),
            },
            format="multipart",
        )
        self.assertEqual(created.status_code, 201)
        self.assertIn("next_step", created.data)
        self.assertEqual(self.client.get("/api/v1/dashboard/stats").status_code, 403)
        double = self.client.post(
            "/api/v1/onboarding/bank-sampah",
            {
                "nama": "Bank Sampah Maju",
                "alamat": "Jl. Panjang Sekali No. 100",
                "no_hp_pic": "081234567890",
                "foto_kegiatan": logo("kegiatan.png"),
            },
            format="multipart",
        )
        self.assertGreaterEqual(double.status_code, 400)

    def test_register_bank_rejects_bad_payload(self) -> None:
        user = self.fresh_pengelola("jelek@example.com")
        self.auth_as(user)
        base: dict[str, Any] = {
            "nama": "Bank Sampah Maju",
            "alamat": "Jl. Panjang Sekali No. 100",
            "no_hp_pic": "081234567890",
            "foto_kegiatan": logo(),
        }
        cases = [
            {"nama": "AB"},
            {"alamat": "pendek"},
            {"no_hp_pic": "123"},
            {"foto_kegiatan": ""},
        ]
        for override in cases:
            with self.subTest(override=override):
                payload = dict(base, **override)
                response = self.client.post(
                    "/api/v1/onboarding/bank-sampah", payload, format="multipart"
                )
                self.assertGreaterEqual(response.status_code, 400)

    def test_register_rejects_non_pengelola_role(self) -> None:
        user = User.objects.create_user(email="nb@example.com", nama="Nb", role=User.Role.NASABAH)
        with self.assertRaises(PermissionError):
            OnboardingService.register_bank_sampah(user, {})

    def test_bank_me_get_contract(self) -> None:
        response = self.client.get("/api/v1/bank-sampah/me")
        self.assertEqual(response.status_code, 200)
        for key in ("id", "nama", "alamat", "kota", "no_hp_pic", "status"):
            self.assertIn(key, response.data)

    def test_bank_me_rejects_bad_phone(self) -> None:
        response = self.client.put(
            "/api/v1/bank-sampah/me",
            {
                "nama": "Bank Sampah BTH",
                "alamat": "Kel. Kukusan Panjang",
                "kota": "Depok",
                "no_hp_pic": "123",
            },
            format="json",
        )
        self.assertGreaterEqual(response.status_code, 400)
