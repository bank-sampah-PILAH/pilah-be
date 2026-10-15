from typing import Any

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
        source_octet = sum(map(ord, self._testMethodName)) % 254 + 1
        self.client.defaults["REMOTE_ADDR"] = f"192.0.2.{source_octet}"

    def _login(self, email: str | None = None, password: str | None = None) -> Any:
        return self.client.post(
            "/api/v1/auth/reviewer",
            {
                "email": self.email if email is None else email,
                "password": self.password if password is None else password,
            },
            format="json",
        )

    def _assert_invalid_credentials(self, response: Any) -> None:
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.data, {"error": "Kredensial tidak valid", "code": "invalid_credentials"}
        )
        self.assertNotIn("access_token", response.data)
        self.assertIn("no-store", response["Cache-Control"])

    def test_configured_reviewer_gets_standard_session_and_is_tenant_scoped(self) -> None:
        own_nasabah = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-0002",
            nama="Synthetic Customer",
            no_hp="+628128888888",
            alamat="Jl. Melati No. 2",
            email="synthetic-customer@example.test",
        )
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
        self.assertGreater(access["exp"], access["iat"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access_token']}")
        self.assertEqual(self.client.get(f"/api/v1/nasabah/{own_nasabah.id}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/nasabah/{other_nasabah.id}").status_code, 404)

    def test_wrong_email_and_password_return_the_same_generic_error(self) -> None:
        wrong_email = self._login(email="someone-else@example.test")
        wrong_password = self._login(password="wrong-password")
        missing_credentials = self.client.post("/api/v1/auth/reviewer", {}, format="json")

        self._assert_invalid_credentials(wrong_email)
        self._assert_invalid_credentials(wrong_password)
        self._assert_invalid_credentials(missing_credentials)

    def test_reviewer_auth_logs_generic_events_without_sensitive_data(self) -> None:
        attempted_password = "never-log-this-password"
        with self.assertLogs("apps.authentication.views", level="INFO") as captured:
            successful = self._login()
            failed = self._login(password=attempted_password)

        self.assertEqual(successful.status_code, 200)
        self.assertEqual(failed.status_code, 401)
        messages = "\n".join(
            f"{record.name} {record.levelname} {record.getMessage()} {record.args!r}"
            for record in captured.records
        )
        self.assertIn("reviewer_auth.success", messages)
        self.assertIn("reviewer_auth.failure", messages)
        sensitive_values = (
            self.email,
            self.password,
            attempted_password,
            successful.data["access_token"],
            successful.data["refresh_token"],
            str(self.bank.id),
            self.bank.nama,
        )
        self.assertFalse(any(value in messages for value in sensitive_values))

    def test_reviewer_refresh_token_is_revoked_by_logout(self) -> None:
        login = self._login()
        self.assertEqual(login.status_code, 200)
        refresh_token = login.data["refresh_token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access_token']}")

        refreshed = self.client.post(
            "/api/v1/auth/refresh", {"refresh_token": refresh_token}, format="json"
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.data)
        self.assertIn("access_token", refreshed.data)

        logout = self.client.post(
            "/api/v1/auth/logout", {"refresh_token": refresh_token}, format="json"
        )
        self.assertEqual(logout.status_code, 200, logout.data)
        rejected = self.client.post(
            "/api/v1/auth/refresh", {"refresh_token": refresh_token}, format="json"
        )
        self.assertEqual(rejected.status_code, 401)

    def test_only_active_pengelola_on_the_configured_active_bank_can_login(self) -> None:
        cases = [
            ("role", User.Role.PENGELOLA_INDUK),
            ("role", User.Role.SUPERADMIN),
            ("is_active", False),
            ("is_staff", True),
            ("is_superuser", True),
        ]
        for index, (field, value) in enumerate(cases):
            with self.subTest(field=field, value=value):
                self.client.defaults["REMOTE_ADDR"] = f"192.0.2.{index + 20}"
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
        self.client.defaults["REMOTE_ADDR"] = "192.0.2.30"
        self._assert_invalid_credentials(self._login())

        self.user.bank_sampah = self.bank
        self.user.save(update_fields=["bank_sampah", "updated_at"])
        self.bank.status = BankSampah.Status.PENDING
        self.bank.save(update_fields=["status", "updated_at"])
        self.client.defaults["REMOTE_ADDR"] = "192.0.2.31"
        self._assert_invalid_credentials(self._login())

        self.bank.status = BankSampah.Status.ACTIVE
        self.bank.is_active = False
        self.bank.save(update_fields=["status", "is_active", "updated_at"])
        self.client.defaults["REMOTE_ADDR"] = "192.0.2.32"
        self._assert_invalid_credentials(self._login())

    def test_disabled_reviewer_login_returns_not_found_without_debug(self) -> None:
        with override_settings(PILAH_ENABLE_DEMO_LOGIN=False):
            response = self._login()

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("access_token", response.data)
        self.assertIn("no-store", response["Cache-Control"])

    def test_reviewer_login_is_throttled_by_source(self) -> None:
        self.client.defaults["REMOTE_ADDR"] = "192.0.2.250"

        for _ in range(5):
            self.assertEqual(self._login(password="wrong-password").status_code, 401)
        throttled = self._login(password="wrong-password")

        self.assertEqual(throttled.status_code, 429)
        self.assertIn("no-store", throttled["Cache-Control"])

    def test_untrusted_forwarded_prefix_cannot_bypass_source_throttle(self) -> None:
        self.client.defaults["REMOTE_ADDR"] = "10.0.0.5"

        for octet in range(1, 6):
            self.client.defaults["HTTP_X_FORWARDED_FOR"] = (
                f"198.51.100.{octet}, 192.0.2.251, 198.51.100.250, 203.0.113.250"
            )
            self.assertEqual(self._login(password="wrong-password").status_code, 401)

        self.client.defaults["HTTP_X_FORWARDED_FOR"] = (
            "203.0.113.99, 192.0.2.251, 198.51.100.250, 203.0.113.250"
        )
        throttled = self._login(password="wrong-password")

        self.assertEqual(throttled.status_code, 429)
