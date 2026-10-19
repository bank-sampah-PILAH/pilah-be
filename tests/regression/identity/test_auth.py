"""Identity contracts: login, refresh, logout, me, and access gating."""

from unittest.mock import patch

from django.core.cache import caches

from api.models import BankSampah, User
from apps.authentication.views import PasswordLoginThrottle
from tests.regression.helpers import RegressionTestCase


class AuthRegressionTests(RegressionTestCase):
    def setUp(self) -> None:
        super().setUp()
        rate_limit_cache = caches["auth_rate_limit"]
        rate_limit_cache.clear()
        self.addCleanup(rate_limit_cache.clear)

    def test_password_login_rejects_malformed_credentials(self) -> None:
        self.client.credentials()

        response = self.client.post(
            "/api/v1/auth/login", {"email": "not-an-email", "password": "x"}, format="json"
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("errors", response.data)

    def test_password_login_hides_ambiguous_email_matches(self) -> None:
        User.objects.create_user(email="duplicate@example.com", nama="First")
        User.objects.create_user(email="Duplicate@example.com", nama="Second")

        response = self.client.post(
            "/api/v1/auth/login",
            {"email": "duplicate@example.com", "password": "any-password"},
            format="json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["code"], "invalid_credentials")

    def test_password_login_rejects_unallowlisted_superadmin(self) -> None:
        User.objects.create_user(
            email="blocked-admin@example.com",
            nama="Blocked Admin",
            role=User.Role.SUPERADMIN,
            is_profile_complete=True,
            email_verified=True,
            password="correct-password",
        )

        response = self.client.post(
            "/api/v1/auth/login",
            {"email": "blocked-admin@example.com", "password": "correct-password"},
            format="json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["code"], "invalid_credentials")

    def test_password_login_is_rate_limited(self) -> None:
        self.client.credentials()
        rate_limit_cache = caches["auth_rate_limit"]
        self.assertIs(PasswordLoginThrottle.cache, rate_limit_cache)
        payload = {"email": "sari@example.com", "password": "password"}

        with patch(
            "apps.authentication.views.AuthService.login_with_password", return_value={}
        ) as login:
            responses = [
                self.client.post("/api/v1/auth/login", payload, format="json") for _ in range(6)
            ]

        self.assertEqual([response.status_code for response in responses], [200] * 5 + [429])
        self.assertEqual(login.call_count, 5)
        login.assert_called_with("sari@example.com", "password")

    def test_password_login_throttle_ignores_untrusted_forwarded_prefix(self) -> None:
        self.client.credentials()
        payload = {"email": "sari@example.com", "password": "password"}
        forwarded_for = [
            f"{spoofed}, 198.51.100.23, 35.191.0.1, 35.191.0.2"
            for spoofed in (
                "192.0.2.1",
                "192.0.2.2",
                "192.0.2.3",
                "192.0.2.4",
                "192.0.2.5",
                "192.0.2.6",
            )
        ]

        with patch("apps.authentication.views.AuthService.login_with_password", return_value={}):
            responses = [
                self.client.post(
                    "/api/v1/auth/login",
                    payload,
                    format="json",
                    HTTP_X_FORWARDED_FOR=header,
                )
                for header in forwarded_for
            ]

        self.assertEqual([response.status_code for response in responses], [200] * 5 + [429])

    def test_protected_endpoints_require_auth(self) -> None:
        self.client.credentials()
        paths = [
            "/api/v1/auth/me",
            "/api/v1/nasabah",
            "/api/v1/jenis-sampah",
            "/api/v1/transaksi",
            "/api/v1/bank-sampah/me",
            "/api/v1/team",
            "/api/v1/dashboard/stats",
            "/api/v1/dashboard/recent-transactions",
            "/api/v1/pengaturan/wa-template",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)

    def test_auth_me_returns_user_contract(self) -> None:
        response = self.client.get("/api/v1/auth/me")
        self.assertEqual(response.status_code, 200)
        for key in (
            "id",
            "nama",
            "email",
            "role",
            "bank_sampah_id",
            "bank_sampah_nama",
            "bank_sampah_status",
            "is_profile_complete",
            "is_primary_pengelola",
            "state",
        ):
            self.assertIn(key, response.data)
        self.assertEqual(response.data["email"], "sari@example.com")

    def test_refresh_returns_access_contract(self) -> None:
        self.client.credentials()
        login = self.client.post(
            "/api/v1/auth/google", {"id_token": "dev:sari@example.com:Sari"}, format="json"
        )
        self.assertEqual(login.status_code, 200)
        refresh = self.client.post(
            "/api/v1/auth/refresh",
            {"refresh_token": login.data["refresh_token"]},
            format="json",
        )
        self.assertEqual(refresh.status_code, 200)
        self.assertIn("access_token", refresh.data)
        self.assertIn("expires_in", refresh.data)

    def test_refresh_rejects_missing_token(self) -> None:
        self.assertGreaterEqual(self.client.post("/api/v1/auth/refresh", {}).status_code, 400)

    def test_logout_always_succeeds_and_blacklists(self) -> None:
        self.client.credentials()
        login = self.client.post(
            "/api/v1/auth/google", {"id_token": "dev:sari@example.com:Sari"}, format="json"
        )
        token = login.data["refresh_token"]
        self.auth_as(self.user)
        logout = self.client.post("/api/v1/auth/logout", {"refresh_token": token}, format="json")
        self.assertEqual(logout.status_code, 200)
        retry = self.client.post("/api/v1/auth/refresh", {"refresh_token": token}, format="json")
        self.assertGreaterEqual(retry.status_code, 400)

    def test_logout_with_garbage_token_still_200(self) -> None:
        response = self.client.post(
            "/api/v1/auth/logout", {"refresh_token": "not-a-token"}, format="json"
        )
        self.assertEqual(response.status_code, 200)

    def test_google_login_rejects_missing_token(self) -> None:
        self.client.credentials()
        self.assertGreaterEqual(self.client.post("/api/v1/auth/google", {}).status_code, 400)

    def test_password_login_returns_the_google_session_contract(self) -> None:
        self.client.credentials()
        self.user.set_password("correct-password")
        self.user.email_verified = True
        self.user.save(update_fields=["password", "email_verified"])

        response = self.client.post(
            "/api/v1/auth/login",
            {"email": " SARI@EXAMPLE.COM ", "password": "correct-password"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, getattr(response, "data", None))
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
        self.assertEqual(response.data["next_step"], "dashboard")
        self.assertFalse(response.data["is_new_user"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access_token']}")
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 200)
        refresh = self.client.post(
            "/api/v1/auth/refresh",
            {"refresh_token": response.data["refresh_token"]},
            format="json",
        )
        self.assertEqual(refresh.status_code, 200, refresh.data)

    def test_password_login_returns_the_same_error_for_invalid_credentials(self) -> None:
        self.client.credentials()
        self.user.set_password("correct-password")
        self.user.email_verified = True
        self.user.save(update_fields=["password", "email_verified"])
        inactive = self.make_user("inactive@example.com", User.Role.PENGELOLA, self.bank)
        inactive.set_password("correct-password")
        inactive.is_active = False
        inactive.save(update_fields=["password", "is_active"])
        expected = {
            "error": "Email atau kata sandi tidak valid",
            "code": "invalid_credentials",
        }

        for email, password in (
            ("missing@example.com", "correct-password"),
            (self.user.email, "wrong-password"),
            (inactive.email, "correct-password"),
        ):
            with self.subTest(email=email):
                response = self.client.post(
                    "/api/v1/auth/login",
                    {"email": email, "password": password},
                    format="json",
                )
                self.assertEqual(response.status_code, 401, getattr(response, "data", None))
                self.assertEqual(response.data, expected)

    def test_password_login_requires_verified_email_unless_explicitly_exempt(self) -> None:
        self.client.credentials()
        self.user.set_password("correct-password")
        self.user.email_verified = False
        self.user.save(update_fields=["password", "email_verified"])
        payload = {"email": self.user.email, "password": "correct-password"}

        with self.settings(PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS=()):
            denied = self.client.post("/api/v1/auth/login", payload, format="json")
        self.assertEqual(denied.status_code, 401, getattr(denied, "data", None))
        self.assertEqual(denied.data["code"], "invalid_credentials")

        with self.settings(PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS=" SARI@EXAMPLE.COM "):
            allowed = self.client.post("/api/v1/auth/login", payload, format="json")
        self.assertEqual(allowed.status_code, 200, getattr(allowed, "data", None))

    def test_non_pengelola_roles_denied_on_pengelola_endpoints(self) -> None:
        paths = [
            "/api/v1/dashboard/stats",
            "/api/v1/dashboard/recent-transactions",
            "/api/v1/nasabah",
            "/api/v1/jenis-sampah",
            "/api/v1/transaksi",
            "/api/v1/bank-sampah/me",
        ]
        for role in (User.Role.PENGELOLA_INDUK, User.Role.NASABAH, User.Role.SUPERADMIN):
            user = self.make_user(f"{role}@example.com", role)
            self.auth_as(user)
            for path in paths:
                with self.subTest(role=role, path=path):
                    self.assertEqual(self.client.get(path).status_code, 403)
        self.auth_as(self.user)

    def test_pending_bank_pengelola_denied_on_active_endpoints(self) -> None:
        self.bank.status = "pending"
        self.bank.save()
        for path in ("/api/v1/dashboard/stats", "/api/v1/nasabah", "/api/v1/transaksi"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)

    def test_login_next_steps_per_account_state(self) -> None:
        self.client.credentials()
        # PIL-180: a Google email with no account and no verified Nasabah row
        # gets the registration gate, so these logins use the dev-role token
        # (default role PENGELOLA) to exercise the "account exists" next-step
        # states below.
        for email in ("fresh@example.com", "incomplete@example.com"):
            with self.subTest(email=email):
                response = self.client.post(
                    "/api/v1/auth/google",
                    {"id_token": f"dev-pengelola:{email}:N"},
                    format="json",
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("next_step", response.data)

        pending_bank = BankSampah.objects.create(
            nama="Pending",
            alamat="Jl. Panjang Sekali No. 9",
            kota="Depok",
            no_hp_pic="+628100000009",
            status=BankSampah.Status.PENDING,
        )
        User.objects.create_user(
            email="pending@example.com",
            nama="Pending",
            no_hp="081234567890",
            jenis_kelamin="laki-laki",
            tanggal_lahir="1990-01-01",
            bank_sampah=pending_bank,
            is_profile_complete=True,
        )
        pending_login = self.client.post(
            "/api/v1/auth/google", {"id_token": "dev:pending@example.com:P"}, format="json"
        )
        self.assertEqual(pending_login.data["next_step"], "approval_pending")
        pending_bank.status = BankSampah.Status.REJECTED
        pending_bank.save(update_fields=["status"])
        rejected_login = self.client.post(
            "/api/v1/auth/google", {"id_token": "dev:pending@example.com:P"}, format="json"
        )
        self.assertEqual(rejected_login.data["next_step"], "registration_rejected")
