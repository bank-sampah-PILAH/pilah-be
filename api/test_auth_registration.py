from unittest.mock import Mock, patch

from django.test import override_settings
from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, User


GOOGLE_PROFILE = {
    "sub": "google-new-user",
    "email": "new.user@example.com",
    "email_verified": True,
    "name": "New User",
    "picture": "https://example.com/avatar.png",
}


@override_settings(PILAH_ALLOW_FAKE_GOOGLE_TOKEN=False, PILAH_SUPERADMIN_EMAILS=())
class GoogleRegistrationTests(APITestCase):
    @patch("api.services.google_id_token.verify_oauth2_token")
    def test_unknown_verified_identity_requires_registration_without_creating_user(
        self, verify: Mock
    ) -> None:
        verify.return_value = GOOGLE_PROFILE

        response = self.client.post(
            "/api/v1/auth/google", {"id_token": "signed-google-token"}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["registration_required"])
        self.assertEqual(response.data["expires_in"], 600)
        self.assertEqual(response.data["google_profile"]["email"], GOOGLE_PROFILE["email"])
        self.assertIn("registration_token", response.data)
        self.assertFalse(User.objects.filter(email=GOOGLE_PROFILE["email"]).exists())

    @patch("api.services.google_id_token.verify_oauth2_token")
    def test_each_registration_role_creates_an_incomplete_account(self, verify: Mock) -> None:
        for index, role in enumerate(
            (User.Role.PENGELOLA, User.Role.PENGELOLA_INDUK, User.Role.NASABAH), start=1
        ):
            with self.subTest(role=role):
                profile = dict(GOOGLE_PROFILE)
                profile["sub"] = f"google-{index}"
                profile["email"] = f"new-{index}@example.com"
                verify.return_value = profile
                login = self.client.post(
                    "/api/v1/auth/google", {"id_token": f"google-token-{index}"}, format="json"
                )

                response = self.client.post(
                    "/api/v1/auth/google/register",
                    {"registration_token": login.data["registration_token"], "role": role},
                    format="json",
                )

                self.assertEqual(response.status_code, 201, response.data)
                self.assertEqual(response.data["user"]["role"], role)
                self.assertEqual(response.data["next_step"], "complete_profile")
                user = User.objects.get(email=profile["email"])
                self.assertFalse(user.is_profile_complete)

    @patch("api.services.google_id_token.verify_oauth2_token")
    def test_existing_account_logs_in_with_its_stored_role(self, verify: Mock) -> None:
        user = User.objects.create_user(
            email=GOOGLE_PROFILE["email"],
            nama="Stored Name",
            role=User.Role.NASABAH,
            is_profile_complete=True,
        )
        verify.return_value = {**GOOGLE_PROFILE, "role": User.Role.SUPERADMIN}

        response = self.client.post(
            "/api/v1/auth/google", {"id_token": "signed-google-token"}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn("registration_required", response.data)
        self.assertEqual(response.data["user"]["role"], User.Role.NASABAH)
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.NASABAH)

    def test_registration_rejects_invalid_tampered_and_expired_tokens(self) -> None:
        invalid_role = self.client.post(
            "/api/v1/auth/google/register",
            {"registration_token": "invalid", "role": User.Role.SUPERADMIN},
            format="json",
        )
        self.assertEqual(invalid_role.status_code, 422, invalid_role.data)

        tampered = self.client.post(
            "/api/v1/auth/google/register",
            {"registration_token": "tampered", "role": User.Role.PENGELOLA},
            format="json",
        )
        self.assertEqual(tampered.status_code, 400, tampered.data)

        with patch("api.services.REGISTRATION_TOKEN_MAX_AGE", -1):
            expired = self.client.post(
                "/api/v1/auth/google/register",
                {
                    "registration_token": self._registration_token(),
                    "role": User.Role.PENGELOLA,
                },
                format="json",
            )
        self.assertEqual(expired.status_code, 400, expired.data)
        self.assertEqual(expired.data["code"], "registration_token_expired")

    @patch("api.services.google_id_token.verify_oauth2_token")
    def test_repeated_registration_authenticates_the_stored_role(self, verify: Mock) -> None:
        verify.return_value = GOOGLE_PROFILE
        token = self._registration_token()
        first = self.client.post(
            "/api/v1/auth/google/register",
            {"registration_token": token, "role": User.Role.NASABAH},
            format="json",
        )
        second = self.client.post(
            "/api/v1/auth/google/register",
            {"registration_token": token, "role": User.Role.PENGELOLA},
            format="json",
        )

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(second.data["user"]["role"], User.Role.NASABAH)

    @patch("api.services.google_id_token.verify_oauth2_token")
    def _registration_token(self, verify: Mock) -> str:
        verify.return_value = GOOGLE_PROFILE
        response = self.client.post(
            "/api/v1/auth/google", {"id_token": "signed-google-token"}, format="json"
        )
        return str(response.data["registration_token"])


@override_settings(PILAH_ALLOW_FAKE_GOOGLE_TOKEN=False)
class SuperadminWhitelistTests(APITestCase):
    @patch("api.services.google_id_token.verify_oauth2_token")
    @override_settings(PILAH_SUPERADMIN_EMAILS=("admin@example.com",))
    def test_whitelist_is_case_insensitive_and_provisions_superadmin(self, verify: Mock) -> None:
        verify.return_value = {
            **GOOGLE_PROFILE,
            "sub": "google-admin",
            "email": "ADMIN@EXAMPLE.COM",
        }

        response = self.client.post(
            "/api/v1/auth/google", {"id_token": "signed-google-token"}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["user"]["role"], User.Role.SUPERADMIN)
        self.assertEqual(response.data["next_step"], "superadmin_dashboard")

    @patch("api.services.google_id_token.verify_oauth2_token")
    @override_settings(PILAH_SUPERADMIN_EMAILS=())
    def test_existing_superadmin_removed_from_whitelist_is_rejected(self, verify: Mock) -> None:
        User.objects.create_user(
            email=GOOGLE_PROFILE["email"],
            nama="Former Admin",
            role=User.Role.SUPERADMIN,
            is_profile_complete=True,
        )
        verify.return_value = GOOGLE_PROFILE

        response = self.client.post(
            "/api/v1/auth/google", {"id_token": "signed-google-token"}, format="json"
        )

        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["code"], "superadmin_not_allowlisted")

    @patch("api.services.google_id_token.verify_oauth2_token")
    @override_settings(PILAH_SUPERADMIN_EMAILS=("member@example.com",))
    def test_whitelist_conflict_does_not_promote_nasabah_membership(self, verify: Mock) -> None:
        bank = BankSampah.objects.create(
            nama="Bank Membership", alamat="Depok", no_hp_pic="+628111111111"
        )
        user = User.objects.create_user(
            email="member@example.com",
            nama="Member",
            role=User.Role.NASABAH,
            is_profile_complete=True,
        )
        Nasabah.objects.create(
            user=user,
            bank_sampah=bank,
            nomor="NAS-001",
            nama="Member",
            alamat="Depok",
            no_hp="+628111111112",
        )
        verify.return_value = {**GOOGLE_PROFILE, "email": "MEMBER@example.com"}

        response = self.client.post(
            "/api/v1/auth/google", {"id_token": "signed-google-token"}, format="json"
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "superadmin_configuration_conflict")
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.NASABAH)


@override_settings(PILAH_ALLOW_FAKE_GOOGLE_TOKEN=True)
class RoleOnboardingStateTests(APITestCase):
    def test_all_registration_roles_can_complete_shared_profile(self) -> None:
        expected = {
            User.Role.PENGELOLA: ("dev", "register_bank_sampah"),
            User.Role.PENGELOLA_INDUK: (
                "dev-pengelola-induk",
                "register_bank_sampah_induk",
            ),
            User.Role.NASABAH: ("dev-nasabah", "register_nasabah"),
        }
        for index, (role, (prefix, next_step)) in enumerate(expected.items(), start=1):
            with self.subTest(role=role):
                login = self.client.post(
                    "/api/v1/auth/google",
                    {"id_token": f"{prefix}:role-{index}@example.com:Role User"},
                    format="json",
                )
                self.client.credentials(
                    HTTP_AUTHORIZATION=f"Bearer {login.data['access_token']}"
                )

                response = self.client.put(
                    "/api/v1/onboarding/profile",
                    {
                        "nama": "Role User",
                        "jenis_kelamin": "laki-laki",
                        "tanggal_lahir": "1990-01-01",
                        "no_hp": f"08123456789{index}",
                    },
                    format="json",
                )

                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["next_step"], next_step)
                self.client.credentials()
