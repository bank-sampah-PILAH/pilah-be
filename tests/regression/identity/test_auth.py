"""Identity contracts: login, refresh, logout, me, and access gating."""

from api.models import BankSampah, User
from tests.regression.helpers import RegressionTestCase


class AuthRegressionTests(RegressionTestCase):
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
        for email in ("fresh@example.com", "incomplete@example.com"):
            with self.subTest(email=email):
                response = self.client.post(
                    "/api/v1/auth/google", {"id_token": f"dev:{email}:N"}, format="json"
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
