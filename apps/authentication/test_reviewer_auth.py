from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from api.models import BankSampah, Nasabah, User


class ReviewerAuthenticationTests(APITestCase):
    email = "reviewer@example.test"
    password = "test-reviewer-password"

    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(
            nama="Synthetic Bank",
            alamat="Depok",
            kota="Depok",
            no_hp_pic="+628123456789",
            status=BankSampah.Status.ACTIVE,
            is_active=True,
        )
        self.user = User.objects.create_user(
            email=self.email,
            nama="Reviewer",
            role=User.Role.PENGELOLA,
            bank_sampah=self.bank,
            is_profile_complete=True,
        )
        self.enterContext(
            override_settings(
                DEBUG=False,
                PILAH_ALLOW_FAKE_GOOGLE_TOKEN=False,
                PILAH_ENABLE_DEMO_LOGIN=True,
                PILAH_REVIEWER_EMAIL=self.email,
                PILAH_REVIEWER_PASSWORD_HASH=make_password(self.password),
                PILAH_REVIEWER_BANK_SAMPAH_ID=str(self.bank.id),
            )
        )
        self.client.defaults["REMOTE_ADDR"] = f"192.0.2.{sum(map(ord, self._testMethodName)) % 254 + 1}"

    def _login(self, email: str | None = None, password: str | None = None):
        return self.client.post(
            "/api/v1/auth/reviewer",
            {
                "email": self.email if email is None else email,
                "password": self.password if password is None else password,
            },
            format="json",
        )

    def _assert_invalid_credentials(self, response) -> None:
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.data, {"error": "Kredensial tidak valid", "code": "invalid_credentials"}
        )
        self.assertNotIn("access_token", response.data)
        self.assertIn("no-store", response["Cache-Control"])

    def test_configured_reviewer_gets_standard_session_and_is_tenant_scoped(self) -> None:
        other_bank = BankSampah.objects.create(
            nama="Other Bank",
            alamat="Bogor",
            kota="Bogor",
            no_hp_pic="+628129999999",
            status=BankSampah.Status.ACTIVE,
            is_active=True,
        )
        other_nasabah = Nasabah.objects.create(
            bank_sampah=other_bank,
            nomor="NAS-0001",
            nama="Other Customer",
            no_hp="+628129999999",
            alamat="Jl. Kenanga No. 1",
            email="other-customer@example.test",
        )

        response = self._login()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            set(response.data),
            {
                "access_token",
                "refresh_token",
                "token_type",
                "expires_in",
                "user",
                "next_step",
                "is_new_user",
            },
        )
        self.assertEqual(response.data["user"]["role"], User.Role.PENGELOLA)
        self.assertEqual(response.data["user"]["bank_sampah_id"], str(self.bank.id))
        self.assertEqual(response.data["is_new_user"], False)
        self.assertIn("no-store", response["Cache-Control"])

        access = AccessToken(response.data["access_token"])
        self.assertEqual(access["role"], User.Role.PENGELOLA)
        self.assertEqual(access["bank_sampah_id"], str(self.bank.id))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access_token']}")
        self.assertEqual(
            self.client.get(f"/api/v1/nasabah/{other_nasabah.id}").status_code, 404
        )

    def test_wrong_email_and_password_return_the_same_generic_error(self) -> None:
        wrong_email = self._login(email="someone-else@example.test")
        wrong_password = self._login(password="wrong-password")
        missing_credentials = self.client.post("/api/v1/auth/reviewer", {}, format="json")

        self._assert_invalid_credentials(wrong_email)
        self._assert_invalid_credentials(wrong_password)
        self._assert_invalid_credentials(missing_credentials)

    def test_only_active_pengelola_on_the_configured_active_bank_can_login(self) -> None:
        cases = [
            ("role", User.Role.PENGELOLA_INDUK),
            ("role", User.Role.SUPERADMIN),
            ("is_active", False),
            ("is_staff", True),
            ("is_superuser", True),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                original = getattr(self.user, field)
                setattr(self.user, field, value)
                self.user.save(update_fields=[field, "updated_at"])

                self._assert_invalid_credentials(self._login())

                setattr(self.user, field, original)
                self.user.save(update_fields=[field, "updated_at"])

        other_bank = BankSampah.objects.create(
            nama="Other Bank",
            alamat="Bogor",
            kota="Bogor",
            no_hp_pic="+628129999999",
            status=BankSampah.Status.ACTIVE,
            is_active=True,
        )
        self.user.bank_sampah = other_bank
        self.user.save(update_fields=["bank_sampah", "updated_at"])
        self._assert_invalid_credentials(self._login())

        self.user.bank_sampah = self.bank
        self.user.save(update_fields=["bank_sampah", "updated_at"])
        self.bank.status = BankSampah.Status.PENDING
        self.bank.save(update_fields=["status", "updated_at"])
        self._assert_invalid_credentials(self._login())

    def test_disabled_reviewer_login_returns_not_found_without_debug(self) -> None:
        with override_settings(PILAH_ENABLE_DEMO_LOGIN=False):
            response = self._login()

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("access_token", response.data)
        self.assertIn("no-store", response["Cache-Control"])

    def test_reviewer_login_is_throttled_by_source(self) -> None:
        rest_framework = dict(settings.REST_FRAMEWORK)
        rates = dict(rest_framework["DEFAULT_THROTTLE_RATES"])
        rates["reviewer_login"] = "2/min"
        rest_framework["DEFAULT_THROTTLE_RATES"] = rates
        self.client.defaults["REMOTE_ADDR"] = "192.0.2.250"

        with override_settings(REST_FRAMEWORK=rest_framework):
            self.assertEqual(self._login(password="wrong-password").status_code, 401)
            self.assertEqual(self._login(password="wrong-password").status_code, 401)
            throttled = self._login(password="wrong-password")

        self.assertEqual(throttled.status_code, 429)
        self.assertIn("no-store", throttled["Cache-Control"])
