from typing import Any
from unittest.mock import Mock, patch

from django.core import signing
from django.db import IntegrityError
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, User
from apps.authentication.api import register_nasabah
from apps.authentication.services import REGISTRATION_TOKEN_SALT, AuthService

GOOGLE_PROFILE: dict[str, Any] = {
    "sub": "google-race",
    "email": "race@example.com",
    "email_verified": True,
    "name": "Race User",
    "picture": "",
}


def _first_lookup_misses() -> Mock:
    """Stand-in for a concurrent signup: the first email lookup runs before the
    other request commits, so it sees nobody; later lookups see the real row."""
    real = AuthService._user_for_email
    calls: list[str] = []

    def lookup(email: str) -> User | None:
        if not calls:
            calls.append(email)
            return None
        return real(email)

    return Mock(side_effect=lookup)


@override_settings(PILAH_ALLOW_FAKE_GOOGLE_TOKEN=False, PILAH_SUPERADMIN_EMAILS=())
class GoogleIdentityEdgeCaseTests(APITestCase):
    def _register(self, token: str, role: str = User.Role.PENGELOLA) -> object:
        return self.client.post(
            "/api/v1/auth/google/register",
            {"registration_token": token, "role": role},
            format="json",
        )

    def _login(self, verify: Mock) -> object:
        verify.return_value = GOOGLE_PROFILE
        return self.client.post("/api/v1/auth/google", {"id_token": "t"}, format="json")

    def test_registration_token_without_identity_is_invalid(self) -> None:
        token = signing.dumps({"sub": "", "email": ""}, salt=REGISTRATION_TOKEN_SALT)

        response = self._register(token)

        self.assertEqual(response.status_code, 400)  # type: ignore[attr-defined]
        self.assertEqual(response.data["code"], "registration_token_invalid")  # type: ignore[attr-defined]

    def test_registration_loses_race_to_concurrent_signup_and_signs_in_that_account(self) -> None:
        existing = User.objects.create_user(
            email=GOOGLE_PROFILE["email"], nama="Race User", role=User.Role.NASABAH
        )
        token = signing.dumps(
            {"sub": "google-race", "email": GOOGLE_PROFILE["email"], "name": "Race User"},
            salt=REGISTRATION_TOKEN_SALT,
        )

        with patch.object(AuthService, "_user_for_email", staticmethod(_first_lookup_misses())):
            response = self._register(token, User.Role.PENGELOLA)

        self.assertEqual(response.status_code, 200)  # type: ignore[attr-defined]
        self.assertEqual(response.data["user"]["id"], str(existing.id))  # type: ignore[attr-defined]
        self.assertEqual(response.data["user"]["role"], User.Role.NASABAH)  # type: ignore[attr-defined]

    def test_registration_surfaces_integrity_error_when_no_account_exists(self) -> None:
        token = signing.dumps(
            {"sub": "google-race", "email": GOOGLE_PROFILE["email"], "name": "Race User"},
            salt=REGISTRATION_TOKEN_SALT,
        )

        with (
            patch.object(User.objects, "create_user", side_effect=IntegrityError("other")),
            self.assertRaises(IntegrityError),
        ):
            AuthService.register_with_google(token, User.Role.PENGELOLA)

    @patch("apps.authentication.services.google_id_token.verify_oauth2_token")
    def test_login_loses_race_to_concurrent_signup_and_signs_in_that_account(
        self, verify: Mock
    ) -> None:
        bank = BankSampah.objects.create(nama="Bank Race", alamat="x", kota="Depok")
        Nasabah.objects.create(
            bank_sampah=bank,
            nomor="NAS-0001",
            nama="Race User",
            no_hp="+628111111111",
            email=GOOGLE_PROFILE["email"],
            alamat="Jl. A",
        )
        existing = User.objects.create_user(
            email=GOOGLE_PROFILE["email"], nama="Race User", role=User.Role.NASABAH
        )

        with patch.object(AuthService, "_user_for_email", staticmethod(_first_lookup_misses())):
            response = self._login(verify)

        self.assertEqual(response.status_code, 200)  # type: ignore[attr-defined]
        self.assertEqual(response.data["user"]["id"], str(existing.id))  # type: ignore[attr-defined]
        self.assertFalse(response.data["is_new_user"])  # type: ignore[attr-defined]

    @patch("apps.authentication.services.google_id_token.verify_oauth2_token")
    def test_login_surfaces_integrity_error_when_no_account_exists(self, verify: Mock) -> None:
        bank = BankSampah.objects.create(nama="Bank Race", alamat="x", kota="Depok")
        Nasabah.objects.create(
            bank_sampah=bank,
            nomor="NAS-0001",
            nama="Race User",
            no_hp="+628111111111",
            email=GOOGLE_PROFILE["email"],
            alamat="Jl. A",
        )
        verify.return_value = GOOGLE_PROFILE

        with (
            patch.object(User.objects, "create_user", side_effect=IntegrityError("other")),
            self.assertRaises(IntegrityError),
        ):
            AuthService.login_with_google("t")

    @patch("apps.authentication.services.google_id_token.verify_oauth2_token")
    def test_login_fills_in_a_missing_name_from_google(self, verify: Mock) -> None:
        user = User.objects.create_user(
            email=GOOGLE_PROFILE["email"], nama="", role=User.Role.NASABAH
        )

        response = self._login(verify)

        self.assertEqual(response.status_code, 200)  # type: ignore[attr-defined]
        user.refresh_from_db()
        self.assertEqual(user.nama, "Race User")
        self.assertEqual(user.google_id, "google-race")


class GoogleOAuthStartTests(APITestCase):
    @override_settings(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="")
    def test_start_is_unavailable_until_the_oauth_client_is_configured(self) -> None:
        response = self.client.get("/api/v1/auth/google/start")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data, {"error": "Google OAuth client is not configured"})


class ProfileValidationTests(APITestCase):
    def test_blank_gender_is_refused_when_completing_a_profile(self) -> None:
        user = User.objects.create_user(
            email="cp@example.com", nama="Cp User", role=User.Role.PENGELOLA
        )
        self.client.force_authenticate(user)

        response = self.client.put(
            "/api/v1/onboarding/profile", {"jenis_kelamin": ""}, format="json"
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.data["errors"]["jenis_kelamin"], ["Jenis kelamin wajib dipilih"])


class NasabahSelfRegistrationServiceTests(APITestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(
            nama="Bank Aktif",
            alamat="x",
            kota="Depok",
            status=BankSampah.Status.ACTIVE,
        )

    def test_only_nasabah_accounts_may_apply_for_membership(self) -> None:
        pengelola = User.objects.create_user(
            email="p@example.com", nama="Pengelola", role=User.Role.PENGELOLA
        )

        with self.assertRaisesRegex(PermissionError, "Hanya nasabah"):
            register_nasabah(pengelola, {"bank_sampah_id": self.bank.id})

        self.assertFalse(Nasabah.objects.exists())

    def test_gives_up_when_no_free_member_number_can_be_found(self) -> None:
        # Number NAS-0002 is taken while the bank holds one row, so the next
        # derived number keeps colliding.
        Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-0002",
            nama="Lama",
            no_hp="+628111111111",
            email="lama@example.com",
            alamat="Jl. A",
        )
        user = User.objects.create_user(
            email="n@example.com",
            nama="Nasabah Baru",
            role=User.Role.NASABAH,
            alamat="Jl. B",
            no_hp="+628222222222",
        )

        with self.assertRaisesRegex(ValueError, "Gagal membuat nomor"):
            register_nasabah(user, {"bank_sampah_id": self.bank.id})

        self.assertFalse(Nasabah.objects.filter(user=user).exists())


class NewAccountRoleTests(SimpleTestCase):
    """Role precedence for a new Google account.

    `login_with_google` answers with a registration response before it reaches
    `_role_for_new_account` unless the email is allowlisted, carries a dev role
    or matches an active Nasabah, so the final Pengelola fallback cannot be
    reached through a request. It is the safe default if that guard ever moves,
    so it is pinned here directly.
    """

    def test_allowlisted_email_outranks_every_other_signal(self) -> None:
        role = AuthService._role_for_new_account(True, "pengelola", Mock(spec=Nasabah))

        self.assertEqual(role, User.Role.SUPERADMIN)

    def test_dev_role_outranks_a_matching_nasabah(self) -> None:
        role = AuthService._role_for_new_account(False, "pengelola", Mock(spec=Nasabah))

        self.assertEqual(role, "pengelola")

    def test_matching_nasabah_record_makes_a_nasabah_account(self) -> None:
        role = AuthService._role_for_new_account(False, None, Mock(spec=Nasabah))

        self.assertEqual(role, User.Role.NASABAH)

    def test_no_signal_defaults_to_pengelola(self) -> None:
        role = AuthService._role_for_new_account(False, None, None)

        self.assertEqual(role, User.Role.PENGELOLA)
