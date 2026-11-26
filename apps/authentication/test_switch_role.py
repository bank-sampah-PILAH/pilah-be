import logging
from datetime import timedelta
from io import StringIO
from typing import Any
from unittest.mock import patch

from django.core.cache import caches
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from api.models import BankSampah, Nasabah, User
from apps.authentication.services import AuthService, AuthServiceError
from apps.authentication.views import SwitchRoleThrottle, SwitchRoleView


class SwitchRoleTest(TestCase):
    client: APIClient

    def setUp(self) -> None:
        cache = caches["auth_rate_limit"]
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(
            email="switch@example.com",
            roles=[User.Role.PENGELOLA, User.Role.NASABAH],
            is_profile_complete=True,
        )
        self.refresh = RefreshToken.for_user(self.user)
        self.refresh["role"] = User.Role.PENGELOLA
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.refresh.access_token}")

    def test_session_organisation_follows_role_across_switch_restore_and_refresh(self) -> None:
        managed = BankSampah.objects.create(nama="Managed Bank A", no_hp_pic="+628111111111")
        member_bank = BankSampah.objects.create(nama="Member Bank B", no_hp_pic="+628222222222")
        self.user.bank_sampah = managed
        self.user.save(update_fields=["bank_sampah"])
        membership = Nasabah.objects.create(
            user=self.user,
            bank_sampah=member_bank,
            nomor="NAS-001",
            nama="Member",
            alamat="Jl. Test",
            no_hp="+628123456789",
            email=self.user.email,
        )
        for role, bank in ((User.Role.NASABAH, member_bank), (User.Role.PENGELOLA, managed)):
            with self.subTest(role=role):
                switched = self.client.post(
                    "/api/v1/auth/switch-role", {"role": role}, format="json"
                )
                self.assertEqual(switched.status_code, 200)
                expected = {
                    "bank_sampah_id": str(bank.pk),
                    "bank_sampah_nama": bank.nama,
                    "bank_sampah_status": bank.status,
                }
                for field, value in expected.items():
                    self.assertEqual(switched.data["user"][field], value)
                self.assertEqual(
                    AccessToken(switched.data["access_token"])["bank_sampah_id"], str(bank.pk)
                )
                self.client.credentials(
                    HTTP_AUTHORIZATION=f"Bearer {switched.data['access_token']}"
                )
                restored = self.client.get("/api/v1/auth/me")
                self.assertEqual(restored.status_code, 200)
                for field, value in expected.items():
                    self.assertEqual(restored.data[field], value)
                refreshed = APIClient().post(
                    "/api/v1/auth/refresh",
                    {"refresh_token": switched.data["refresh_token"]},
                    format="json",
                )
                self.assertEqual(refreshed.status_code, 200)
                self.assertEqual(
                    AccessToken(refreshed.data["access_token"])["bank_sampah_id"], str(bank.pk)
                )
        self.user.refresh_from_db()
        membership.refresh_from_db()
        self.assertEqual(self.user.bank_sampah_id, managed.pk)
        self.assertEqual(membership.bank_sampah_id, member_bank.pk)

    def test_nasabah_without_one_eligible_membership_never_inherits_managed_bank(self) -> None:
        managed = BankSampah.objects.create(nama="Managed", no_hp_pic="+628111111111")
        self.user.bank_sampah = managed
        self.user.save(update_fields=["bank_sampah"])
        for case in ("none", "inactive", "pending", "rejected", "multiple"):
            with self.subTest(case=case):
                self.user.keanggotaan_nasabah.all().delete()
                if case != "none":
                    for index in range(2 if case == "multiple" else 1):
                        bank = BankSampah.objects.create(
                            nama=f"{case}-{index}", no_hp_pic="+628111111111"
                        )
                        Nasabah.objects.create(
                            user=self.user,
                            bank_sampah=bank,
                            nomor="NAS-001",
                            nama="Member",
                            alamat="Jl. Test",
                            no_hp="+628123456789",
                            email=self.user.email,
                            is_active=case != "inactive",
                            status=case
                            if case in ("pending", "rejected")
                            else Nasabah.Status.APPROVED,
                        )
                switched = self.client.post(
                    "/api/v1/auth/switch-role", {"role": User.Role.NASABAH}, format="json"
                )
                self.assertEqual(switched.status_code, 200)
                for field in ("bank_sampah_id", "bank_sampah_nama", "bank_sampah_status"):
                    self.assertIsNone(switched.data["user"][field])
                self.assertNotIn(
                    "bank_sampah_id", AccessToken(switched.data["access_token"]).payload
                )
                # A stale legacy refresh claim must not reintroduce a bank.
                refresh = RefreshToken(switched.data["refresh_token"])
                refresh["bank_sampah_id"] = str(managed.pk)
                refreshed = APIClient().post(
                    "/api/v1/auth/refresh", {"refresh_token": str(refresh)}, format="json"
                )
                self.assertEqual(refreshed.status_code, 200)
                self.assertNotIn(
                    "bank_sampah_id", AccessToken(refreshed.data["access_token"]).payload
                )

    def test_rate_limit_is_shared_per_account_despite_token_and_ip_changes(self) -> None:
        other_session = RefreshToken.for_user(self.user)
        other_session["role"] = "nasabah"
        with patch("apps.authentication.views.AuthService.switch_role", return_value={}) as switch:
            for index in range(11):
                token = self.refresh.access_token if index % 2 else other_session.access_token
                self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
                response = self.client.post(
                    "/api/v1/auth/switch-role",
                    {"role": "nasabah"},
                    format="json",
                    HTTP_X_FORWARDED_FOR=f"192.0.2.{index}, 198.51.100.1, 35.191.0.1, 35.191.0.2",
                )
                self.assertEqual(response.status_code, 200 if index < 10 else 429)
            self.assertEqual(switch.call_count, 10)
        self.assertIn("Retry-After", response)
        self.assertIn("no-store", response.get("Cache-Control", ""))
        self.assertIsInstance(SwitchRoleView().get_throttles()[0], SwitchRoleThrottle)
        self.assertIs(SwitchRoleThrottle.cache, caches["auth_rate_limit"])
        other_user = User.objects.create_user(email="other-limit@example.com")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(other_user).access_token}"
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/switch-role", {"role": "pengelola"}, format="json"
            ).status_code,
            200,
        )

    def test_owned_role_issues_new_token_pair_without_changing_account(self) -> None:
        response = self.client.post(
            "/api/v1/auth/switch-role", {"role": User.Role.NASABAH}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        for token in (
            AccessToken(response.data["access_token"]),
            RefreshToken(response.data["refresh_token"]),
        ):
            self.assertEqual(token["role"], User.Role.NASABAH)
            self.assertEqual(str(token["user_id"]), str(self.user.pk))
        self.assertNotEqual(response.data["refresh_token"], str(self.refresh))
        self.assertEqual(response.data["user"]["roles"], [User.Role.PENGELOLA, User.Role.NASABAH])
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.PENGELOLA)
        self.assertEqual(self.user.roles, [User.Role.PENGELOLA, User.Role.NASABAH])

    @override_settings(PILAH_SUPERADMIN_EMAILS=(), PILAH_REVIEW_SUPERADMIN_EMAILS=())
    def test_unallowlisted_superadmin_switch_is_denied_for_primary_and_secondary_roles(
        self,
    ) -> None:
        for primary in (User.Role.SUPERADMIN, User.Role.NASABAH):
            with self.subTest(primary=primary):
                account = User.objects.create_user(
                    email=f"blocked-{primary}@example.com",
                    role=primary,
                    roles=[User.Role.SUPERADMIN, User.Role.NASABAH],
                    is_profile_complete=True,
                )
                access = AccessToken.for_user(account)
                access["role"] = User.Role.NASABAH
                self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
                count = OutstandingToken.objects.count()
                response = self.client.post(
                    "/api/v1/auth/switch-role", {"role": User.Role.SUPERADMIN}, format="json"
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.data["code"], "superadmin_not_allowlisted")
                self.assertNotIn("access_token", response.data)
                self.assertEqual(OutstandingToken.objects.count(), count)

    @override_settings(
        PILAH_SUPERADMIN_EMAILS=("secondary-admin@example.com",), PILAH_REVIEW_SUPERADMIN_EMAILS=()
    )
    def test_secondary_superadmin_refresh_enforces_allowlist_after_successful_switch(self) -> None:
        account = User.objects.create_user(
            email="secondary-admin@example.com",
            role=User.Role.NASABAH,
            roles=[User.Role.NASABAH, User.Role.SUPERADMIN],
            is_profile_complete=True,
        )
        access = AccessToken.for_user(account)
        access["role"] = User.Role.NASABAH
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        switched = self.client.post(
            "/api/v1/auth/switch-role", {"role": User.Role.SUPERADMIN}, format="json"
        )
        self.assertEqual(switched.status_code, 200)
        self.assertEqual(AccessToken(switched.data["access_token"])["role"], User.Role.SUPERADMIN)
        self.assertEqual(RefreshToken(switched.data["refresh_token"])["role"], User.Role.SUPERADMIN)
        self.assertEqual(switched.data["next_step"], "superadmin_dashboard")
        account.refresh_from_db()
        self.assertEqual(account.role, User.Role.NASABAH)
        self.assertFalse(account.is_staff)
        self.assertFalse(account.is_superuser)
        with self.settings(PILAH_SUPERADMIN_EMAILS=()):
            refreshed = APIClient().post(
                "/api/v1/auth/refresh",
                {"refresh_token": switched.data["refresh_token"]},
                format="json",
            )
        self.assertEqual(refreshed.status_code, 403)
        self.assertEqual(refreshed.data["code"], "superadmin_not_allowlisted")
        self.assertNotIn("access_token", refreshed.data)

    def test_switch_responses_cannot_be_cached_including_errors(self) -> None:
        for payload, expected in (
            ({"role": "nasabah"}, 200),
            ({"role": "superadmin"}, 403),
            ({}, 422),
        ):
            response = self.client.post("/api/v1/auth/switch-role", payload, format="json")
            self.assertEqual(response.status_code, expected)
            self.assertIn("no-store", response.get("Cache-Control", ""))
            self.assertIn("private", response.get("Cache-Control", ""))
        response = APIClient().post("/api/v1/auth/switch-role", {"role": "nasabah"}, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertIn("no-store", response.get("Cache-Control", ""))

    def test_response_routes_to_selected_role_without_nasabah_membership(self) -> None:
        response = self.client.post(
            "/api/v1/auth/switch-role", {"role": User.Role.NASABAH}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["role"], User.Role.NASABAH)
        self.assertEqual(response.data["user"]["state"], "register_nasabah")
        self.assertEqual(response.data["next_step"], "register_nasabah")

    def test_unknown_fields_cannot_override_identity_or_token_claims(self) -> None:
        for field, value in (
            ("user_id", "other-account"),
            ("roles", ["superadmin"]),
            ("is_superuser", True),
            ("bank_sampah_id", "other-bank"),
            ("exp", 9999999999),
        ):
            with self.subTest(field=field):
                response = self.client.post(
                    "/api/v1/auth/switch-role", {"role": "nasabah", field: value}, format="json"
                )
                self.assertEqual(response.status_code, 422)
                self.assertNotIn("access_token", response.data)
                self.assertIn("errors", response.data)
        self.assertEqual(self.client.get("/api/v1/auth/me").data["role"], "pengelola")

    def test_me_preserves_selected_role_and_routing(self) -> None:
        switched = self.client.post(
            "/api/v1/auth/switch-role", {"role": User.Role.NASABAH}, format="json"
        )
        self.assertEqual(switched.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {switched.data['access_token']}")
        response = self.client.get("/api/v1/auth/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["role"], User.Role.NASABAH)
        self.assertEqual(response.data["roles"], [User.Role.PENGELOLA, User.Role.NASABAH])
        self.assertNotIn("user", response.data)
        self.assertEqual(response.data["state"], "register_nasabah")

    def test_switch_security_events_omit_tokens_and_untrusted_input(self) -> None:
        with self.assertLogs("pilah.security.role_switch", level="INFO") as events:
            response = self.client.post(
                "/api/v1/auth/switch-role", {"role": "nasabah"}, format="json"
            )
            self.assertEqual(response.status_code, 200)
            with self.assertRaises(AuthServiceError):
                AuthService.switch_role(self.user, "forged\nrole_switch.succeeded")
        self.assertEqual(len(events.records), 2)
        self.assertIn("role_switch.succeeded", events.records[0].getMessage())
        self.assertIn("role_switch.denied", events.records[1].getMessage())
        self.assertIn(str(self.user.pk), events.records[0].getMessage())
        logs = " ".join(events.output)
        for secret in (
            response.data["access_token"],
            response.data["refresh_token"],
            str(self.refresh),
            self.user.email,
            "forged",
            "\n",
        ):
            self.assertNotIn(secret, logs)

    def test_effective_audit_logger_emits_info_with_request_id_without_level_override(self) -> None:
        logger = logging.getLogger("pilah.security.role_switch")
        self.assertTrue(logger.isEnabledFor(logging.INFO))
        handler = next(h for h in logger.handlers if h.name == "console")
        self.assertIn(handler, logging.getLogger().handlers)
        assert isinstance(handler, logging.StreamHandler)
        stream = StringIO()
        original = handler.setStream(stream)
        request_id = "7127cc89-e204-4ee6-81b3-a57998001431"
        try:
            response = self.client.post(
                "/api/v1/auth/switch-role",
                {"role": "nasabah"},
                format="json",
                HTTP_X_REQUEST_ID=request_id,
            )
        finally:
            handler.setStream(original)
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"[{request_id}]", stream.getvalue())
        self.assertIn("INFO pilah.security.role_switch", stream.getvalue())
        self.assertIn("role_switch.succeeded", stream.getvalue())
        self.assertNotIn(response.data["access_token"], stream.getvalue())

    def test_service_rechecks_role_revoked_after_authentication(self) -> None:
        User.objects.filter(pk=self.user.pk).update(roles=[User.Role.PENGELOLA])
        with patch.object(AuthService, "_session_response") as issue:
            with self.assertRaises(AuthServiceError) as denied:
                AuthService.switch_role(self.user, User.Role.NASABAH)
        self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual(denied.exception.code, "role_not_owned")
        issue.assert_not_called()

    def test_service_rejects_disabled_or_deleted_accounts_without_issuance(self) -> None:
        for state in ("disabled", "deleted"):
            with self.subTest(state=state):
                account = User.objects.create_user(email=f"{state}@switch.example.com")
                if state == "disabled":
                    User.objects.filter(pk=account.pk).update(is_active=False)
                else:
                    User.objects.filter(pk=account.pk).delete()
                with patch.object(AuthService, "_session_response") as issue:
                    with self.assertRaises(AuthServiceError) as denied:
                        AuthService.switch_role(account, "pengelola")
                self.assertEqual(denied.exception.status_code, 401)
                self.assertEqual(denied.exception.code, "account_unavailable")
                issue.assert_not_called()

    def test_token_issuance_failure_rolls_back_outstanding_token_and_emits_no_success(self) -> None:
        count = OutstandingToken.objects.count()

        def failing_issuance(*args: Any, **kwargs: Any) -> dict[str, Any]:
            RefreshToken.for_user(self.user)
            raise RuntimeError("Token response could not be built")

        with self.assertNoLogs("pilah.security.role_switch", level="INFO"):
            with patch.object(AuthService, "_session_response", side_effect=failing_issuance):
                with self.assertRaises(RuntimeError):
                    AuthService.switch_role(self.user, "nasabah")
        self.assertEqual(OutstandingToken.objects.count(), count)
        self.assertEqual(self.client.get("/api/v1/auth/me").data["role"], "pengelola")

    def test_unowned_role_is_forbidden_and_preserves_existing_session(self) -> None:
        response = self.client.post(
            "/api/v1/auth/switch-role", {"role": User.Role.SUPERADMIN}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "role_not_owned")
        self.assertIn("error", response.data)
        self.assertNotIn("access_token", response.data)
        self.assertNotIn("refresh_token", response.data)
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 200)
        refreshed = self.client.post(
            "/api/v1/auth/refresh", {"refresh_token": str(self.refresh)}, format="json"
        )
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(AccessToken(refreshed.data["access_token"])["role"], User.Role.PENGELOLA)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.PENGELOLA)
        self.assertEqual(self.user.roles, [User.Role.PENGELOLA, User.Role.NASABAH])

    def test_refresh_and_other_device_preserve_independent_roles(self) -> None:
        other_refresh = RefreshToken.for_user(self.user)
        other_refresh["role"] = User.Role.PENGELOLA
        other = APIClient()
        other.credentials(HTTP_AUTHORIZATION=f"Bearer {other_refresh.access_token}")
        switched = self.client.post(
            "/api/v1/auth/switch-role", {"role": User.Role.NASABAH}, format="json"
        )
        self.assertEqual(switched.status_code, 200)
        for raw, expected in (
            (switched.data["refresh_token"], User.Role.NASABAH),
            (str(other_refresh), User.Role.PENGELOLA),
        ):
            for _ in range(2):
                response = APIClient().post(
                    "/api/v1/auth/refresh", {"refresh_token": raw}, format="json"
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(AccessToken(response.data["access_token"])["role"], expected)
        self.assertEqual(other.get("/api/v1/auth/me").data["role"], User.Role.PENGELOLA)

    def test_switch_round_trip_and_same_role_issue_fresh_pairs(self) -> None:
        previous = str(self.refresh)
        for role, state in (
            (User.Role.NASABAH, "register_nasabah"),
            (User.Role.PENGELOLA, "register_bank_sampah"),
            (User.Role.PENGELOLA, "register_bank_sampah"),
        ):
            response = self.client.post("/api/v1/auth/switch-role", {"role": role}, format="json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["user"]["role"], role)
            self.assertEqual(response.data["next_step"], state)
            self.assertEqual(RefreshToken(response.data["refresh_token"])["role"], role)
            self.assertEqual(AccessToken(response.data["access_token"])["role"], role)
            self.assertNotEqual(response.data["refresh_token"], previous)
            previous = response.data["refresh_token"]
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access_token']}")

    def test_invalid_payloads_are_rejected_without_changing_session(self) -> None:
        payloads: list[Any] = [
            {},
            {"role": ""},
            {"role": None},
            {"role": "unknown"},
            {"role": 1},
            {"role": []},
            {"role": {}},
            [],
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                response = self.client.post("/api/v1/auth/switch-role", payload, format="json")
                self.assertEqual(response.status_code, 422)
                self.assertIn("errors", response.data)
                self.assertNotIn("access_token", response.data)
        self.assertEqual(self.client.get("/api/v1/auth/me").data["role"], User.Role.PENGELOLA)

    def test_invalid_authentication_cannot_switch(self) -> None:
        expired = self.refresh.access_token
        expired.set_exp(lifetime=timedelta(seconds=-1))
        inactive = User.objects.create_user(email="inactive-switch@example.com")
        inactive_token = AccessToken.for_user(inactive)
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        for raw in (
            None,
            "invalid",
            str(expired),
            str(self.refresh),
            str(self.refresh.access_token) + "tampered",
            str(inactive_token),
        ):
            with self.subTest(raw=raw):
                client = APIClient()
                if raw is not None:
                    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
                response = client.post(
                    "/api/v1/auth/switch-role", {"role": User.Role.PENGELOLA}, format="json"
                )
                self.assertEqual(response.status_code, 401)
                self.assertNotIn("access_token", response.data)

    def test_new_token_has_nasabah_permissions_and_rejects_manager_endpoint(self) -> None:
        bank = BankSampah.objects.create(nama="Permission Bank", no_hp_pic="+628123456789")
        Nasabah.objects.create(
            user=self.user,
            bank_sampah=bank,
            nomor="NAS-001",
            nama="Member",
            alamat="Jl. Test",
            no_hp="+628123456789",
            email=self.user.email,
        )
        response = self.client.post(
            "/api/v1/auth/switch-role", {"role": User.Role.NASABAH}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access_token']}")
        self.assertEqual(self.client.get("/api/v1/nasabah/me/beranda").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/nasabah").status_code, 403)

    def test_membership_routes_to_nasabah_dashboard(self) -> None:
        bank = BankSampah.objects.create(nama="Switch Bank", no_hp_pic="+628123456789")
        Nasabah.objects.create(
            user=self.user,
            bank_sampah=bank,
            nomor="NAS-001",
            nama="Member",
            alamat="Jl. Test",
            no_hp="+628123456789",
            email=self.user.email,
        )
        response = self.client.post(
            "/api/v1/auth/switch-role", {"role": User.Role.NASABAH}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["next_step"], "nasabah_dashboard")

    def test_refresh_rejects_role_removed_after_switch(self) -> None:
        switched = self.client.post(
            "/api/v1/auth/switch-role", {"role": User.Role.NASABAH}, format="json"
        )
        self.assertEqual(switched.status_code, 200)
        self.user.roles = [User.Role.PENGELOLA]
        self.user.save(update_fields=["roles"])
        response = APIClient().post(
            "/api/v1/auth/refresh", {"refresh_token": switched.data["refresh_token"]}, format="json"
        )
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("access_token", response.data)

    def test_supplied_identity_and_roles_cannot_grant_permissions(self) -> None:
        victim = User.objects.create_user(email="other-switch@example.com", role=User.Role.NASABAH)
        response = self.client.post(
            "/api/v1/auth/switch-role",
            {"role": User.Role.SUPERADMIN, "user_id": str(victim.pk), "roles": ["superadmin"]},
            format="json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("access_token", response.data)
        victim.refresh_from_db()
        self.assertEqual(victim.roles, [User.Role.NASABAH])
