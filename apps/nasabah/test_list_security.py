"""PIL-442 security boundaries exercised through the real authenticated API."""

from datetime import timedelta
from typing import ClassVar
from unittest.mock import patch

from django.core.cache import caches
from django.db import DatabaseError
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from api.models import BankSampah, Nasabah, User


class NasabahListSecurityTests(APITestCase):
    bank: ClassVar[BankSampah]
    pengurus: ClassVar[User]
    other_pengurus: ClassVar[User]
    foreign_customer: ClassVar[Nasabah]

    @classmethod
    def setUpTestData(cls) -> None:
        cls.bank = BankSampah.objects.create(nama="Bank Aman", alamat="Depok", kota="Depok")
        cls.pengurus = User.objects.create_user(
            email="pengurus-security@example.test",
            nama="Pengurus",
            bank_sampah=cls.bank,
            is_profile_complete=True,
        )
        other_bank = BankSampah.objects.create(nama="Bank Lain", alamat="Bogor", kota="Bogor")
        cls.other_pengurus = User.objects.create_user(
            email="other-security@example.test",
            nama="Pengurus Lain",
            bank_sampah=other_bank,
            is_profile_complete=True,
        )
        for number in range(1, 106):
            Nasabah.objects.create(
                bank_sampah=cls.bank,
                nomor=f"NAS-{number:04}",
                nama=f"Nasabah {number}",
                no_hp=f"+6281234{number:06}",
                email=f"member{number}@example.test",
            )
        cls.foreign_customer = Nasabah.objects.create(
            bank_sampah=other_bank,
            nomor="NAS-0001",
            nama="Rahasia Bank Lain",
            no_hp="+628121234567",
            email="foreign@example.test",
        )

    def setUp(self) -> None:
        caches["auth_rate_limit"].clear()
        self.login_as(self.pengurus)

    def login_as(self, user: User) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")

    def assert_private(self, response: object) -> None:
        # DRF Response implements the HTTP header mapping.
        headers = response.headers  # type: ignore[attr-defined]
        self.assertIn("no-store", headers.get("Cache-Control", ""))
        self.assertIn("private", headers.get("Cache-Control", ""))
        self.assertIn("max-age=0", headers.get("Cache-Control", ""))
        self.assertIn("authorization", headers.get("Vary", "").lower())

    def test_customer_response_cannot_be_stored_in_shared_or_browser_caches(self) -> None:
        response = self.client.get("/api/v1/nasabah", {"urutan": "nama"})
        self.assertEqual(response.status_code, 200)
        self.assert_private(response)

    def test_rejects_overlong_or_nul_search_before_querying_customers(self) -> None:
        for search in ("x" * 255, "name\x00"):
            with self.subTest(search_length=len(search)):
                response = self.client.get("/api/v1/nasabah", {"search": search})
                self.assertEqual(response.status_code, 422)
                self.assertIn("search", response.data["errors"])
                self.assert_private(response)
        accepted = self.client.get("/api/v1/nasabah", {"search": "x" * 254})
        self.assertEqual(accepted.status_code, 200)

    def test_rejects_duplicate_query_keys_instead_of_using_the_last_value(self) -> None:
        for key, first, second in (
            ("status", "aktif", "semua"),
            ("urutan", "nama", "nomor"),
            ("search", "Nasabah", "foreign"),
            ("page", "1", "2"),
            ("page_size", "1", "100"),
        ):
            with self.subTest(key=key):
                response = self.client.get(f"/api/v1/nasabah?{key}={first}&{key}={second}")
                self.assertEqual(response.status_code, 422)
                self.assertIn(key, response.data["errors"])

    def test_unknown_status_cannot_accidentally_disable_status_filter(self) -> None:
        response = self.client.get("/api/v1/nasabah", {"status": "unexpected"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("status", response.data["errors"])
        self.assertEqual(self.client.get("/api/v1/nasabah", {"status": "semua"}).status_code, 200)

    def test_order_and_search_payloads_are_literal_and_never_override_bank_scope(self) -> None:
        response = self.client.get(
            "/api/v1/nasabah",
            {
                "urutan": "nama; DROP TABLE nasabah;--",
                "page_size": 10000,
                "bank_sampah": str(self.foreign_customer.bank_sampah_id),
                "status": "semua",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 105)
        self.assertEqual(len(response.data["results"]), 100)
        self.assertNotIn(
            str(self.foreign_customer.id), [row["id"] for row in response.data["results"]]
        )
        for search in ("' OR 1=1 --", "%", "_"):
            with self.subTest(search=search):
                response = self.client.get("/api/v1/nasabah", {"search": search})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["count"], 0)
        self.assertEqual(Nasabah.objects.count(), 106)

    def test_other_bank_customer_detail_remains_hidden(self) -> None:
        response = self.client.get(f"/api/v1/nasabah/{self.foreign_customer.id}")
        self.assertEqual(response.status_code, 404)
        self.assert_private(response)

    def test_invalid_expired_and_missing_tokens_fail_closed_without_customer_data(self) -> None:
        expired = AccessToken.for_user(self.pengurus)
        expired.set_exp(
            from_time=timezone.now() - timedelta(hours=1), lifetime=timedelta(seconds=1)
        )
        for authorization in (None, "Bearer not-a-valid-jwt", f"Bearer {expired}"):
            with self.subTest(has_token=authorization is not None):
                self.client.credentials(
                    **({"HTTP_AUTHORIZATION": authorization} if authorization else {})
                )
                response = self.client.get("/api/v1/nasabah", {"status": "semua"})
                self.assertEqual(response.status_code, 401)
                self.assertNotIn("results", response.data)
                self.assert_private(response)

    def test_wrong_role_inactive_bank_and_incomplete_profile_cannot_list(self) -> None:
        for changes in (
            {"role": User.Role.NASABAH},
            {"role": User.Role.SUPERADMIN},
            {"is_profile_complete": False},
        ):
            with self.subTest(changes=changes):
                original = {key: getattr(self.pengurus, key) for key in changes}
                User.objects.filter(pk=self.pengurus.pk).update(**changes)
                response = self.client.get("/api/v1/nasabah")
                self.assertEqual(response.status_code, 403)
                self.assert_private(response)
                User.objects.filter(pk=self.pengurus.pk).update(**original)
        BankSampah.objects.filter(pk=self.bank.pk).update(is_active=False)
        self.assertEqual(self.client.get("/api/v1/nasabah").status_code, 403)

    @override_settings(NASABAH_LIST_RATE="2/min")
    def test_quota_is_per_user_and_cannot_be_reset_with_different_query_values(self) -> None:
        self.assertEqual(self.client.get("/api/v1/nasabah", {"urutan": "nama"}).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/nasabah", {"status": "semua"}).status_code, 200)
        denied = self.client.get("/api/v1/nasabah", {"urutan": "terbaru", "page_size": 1})
        self.assertEqual(denied.status_code, 429)
        self.assertGreater(int(denied["Retry-After"]), 0)
        self.assert_private(denied)
        self.login_as(self.other_pengurus)
        self.assertEqual(self.client.get("/api/v1/nasabah").status_code, 200)
        self.login_as(self.pengurus)
        self.assertEqual(
            self.client.get(f"/api/v1/nasabah/{self.foreign_customer.id}").status_code, 404
        )
        caches["auth_rate_limit"].clear()
        self.assertEqual(self.client.get("/api/v1/nasabah").status_code, 200)

    def test_database_failure_returns_safe_retryable_error_without_exception_details(self) -> None:
        with patch(
            "apps.nasabah.views.NasabahViewSet.get_queryset",
            side_effect=DatabaseError("secret sql password"),
        ):
            response = self.client.get("/api/v1/nasabah")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret", str(response.data))
        self.assertNotIn("password", str(response.data))
        self.assert_private(response)

    def test_rejection_audit_does_not_record_tokens_search_or_customer_data(self) -> None:
        token = str(AccessToken.for_user(self.pengurus))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        with self.assertLogs("apps.nasabah.security", level="WARNING") as captured:
            response = self.client.get(
                "/api/v1/nasabah", {"search": "private-person@example.test", "status": "invalid"}
            )
        self.assertEqual(response.status_code, 422)
        logs = str([record.__dict__ for record in captured.records])
        self.assertNotIn(token, logs)
        self.assertNotIn("private-person", logs)
        self.assertNotIn("member1@example.test", logs)
        self.assertTrue(
            any(getattr(record, "status_code", None) == 422 for record in captured.records)
        )
