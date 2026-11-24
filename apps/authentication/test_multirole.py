from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection, models
from django.test import TestCase
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from api.models import BankSampah, Nasabah, User
from apps.authentication.services import AuthService, OnboardingService
from shared_kernel.permissions import IsNasabah, IsPengelola


class AssignedRolesTest(TestCase):
    def test_role_queries_without_json_containment_match_assignments_in_any_order(self) -> None:
        manager = User.objects.create_user(email="fallback-manager@example.com")
        customer = User.objects.create_user(
            email="fallback-customer@example.com", role=User.Role.NASABAH
        )
        dual = User.objects.create_user(
            email="fallback-dual@example.com",
            role=User.Role.NASABAH,
            roles=[User.Role.NASABAH, User.Role.PENGELOLA],
        )
        with patch.object(connection.features, "supports_json_field_contains", False):
            self.assertEqual(
                set(User.objects.with_role(User.Role.PENGELOLA).values_list("pk", flat=True)),
                {manager.pk, dual.pk},
            )
            self.assertEqual(
                set(User.objects.with_role(User.Role.NASABAH).values_list("pk", flat=True)),
                {customer.pk, dual.pk},
            )
            self.assertFalse(User.objects.with_role(User.Role.SUPERADMIN).exists())

    def test_refresh_rejects_tokens_for_missing_or_inactive_accounts(self) -> None:
        client = APIClient()
        for state in ("missing", "inactive"):
            with self.subTest(state=state):
                user = User.objects.create_user(email=f"refresh-{state}@example.com")
                token = RefreshToken.for_user(user)
                if state == "missing":
                    user.delete()
                else:
                    user.is_active = False
                    user.save(update_fields=["is_active"])
                response = client.post(
                    "/api/v1/auth/refresh", {"refresh_token": str(token)}, format="json"
                )
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.data, {"error": "Refresh token invalid / expired"})

    def test_removing_nasabah_role_with_existing_membership_is_rejected(self) -> None:
        user = User.objects.create_user(
            email="keep-membership@example.com",
            roles=["pengelola", "nasabah"],
        )
        bank = BankSampah.objects.create(nama="Bank A", no_hp_pic="+628123456789")
        member = Nasabah.objects.create(
            user=user,
            bank_sampah=bank,
            nomor="NAS-001",
            nama="Member",
            alamat="Jl. Test",
            no_hp="+628123456789",
            email=user.email,
        )
        user.roles = ["pengelola"]
        with self.assertRaises(ValidationError):
            user.save(update_fields=["roles"])
        user.refresh_from_db()
        self.assertEqual(user.roles, ["pengelola", "nasabah"])
        self.assertTrue(Nasabah.objects.filter(pk=member.pk, user=user).exists())

    def test_existing_access_token_is_rejected_after_role_revocation(self) -> None:
        user = User.objects.create_user(email="revoke@example.com", roles=["pengelola", "nasabah"])
        token = AccessToken.for_user(user)
        token["role"] = "nasabah"
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)
        user.roles = ["pengelola"]
        user.save(update_fields=["roles"])
        self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)

    def test_refresh_legacy_fallback_and_invalid_claims(self) -> None:
        user = User.objects.create_user(email="legacy-refresh@example.com")
        client = APIClient()
        token = RefreshToken.for_user(user)
        response = client.post("/api/v1/auth/refresh", {"refresh_token": str(token)}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AccessToken(response.data["access_token"])["role"], "pengelola")
        for role in (None, "", "unknown", "nasabah", ["pengelola"]):
            with self.subTest(role=role):
                token["role"] = role
                response = client.post(
                    "/api/v1/auth/refresh", {"refresh_token": str(token)}, format="json"
                )
                self.assertEqual(response.status_code, 401)

    def test_existing_dual_role_account_can_register_membership_without_changing_roles(
        self,
    ) -> None:
        user = User.objects.create_user(
            email="register-dual@example.com",
            nama="Dual Member",
            alamat="Jl. Test",
            no_hp="+628123456789",
            roles=[User.Role.PENGELOLA, User.Role.NASABAH],
        )
        bank = BankSampah.objects.create(nama="Bank A", no_hp_pic="+628123456789")
        member = OnboardingService.register_nasabah(user, {"bank_sampah_id": bank.pk})
        self.assertEqual(member.user_id, user.pk)
        self.assertEqual(member.status, Nasabah.Status.PENDING)
        self.assertEqual(member.saldo.total_saldo, 0)
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.PENGELOLA)
        self.assertEqual(user.roles, [User.Role.PENGELOLA, User.Role.NASABAH])

    def test_bulk_created_single_role_accounts_get_independent_role_lists(self) -> None:
        users = [User(email=f"bulk-{role}@example.com", role=role) for role in User.Role.values]
        User.objects.bulk_create(users)
        for user in users:
            user.refresh_from_db()
            self.assertEqual(user.roles, [user.role])
        users[0].roles.append("nasabah")
        self.assertEqual(users[1].roles, [users[1].role])

    def test_prefill_links_existing_membership_for_an_account_assigned_nasabah(self) -> None:
        user = User.objects.create_user(
            email="prefill-dual@example.com",
            roles=[User.Role.PENGELOLA, User.Role.NASABAH],
        )
        bank = BankSampah.objects.create(nama="Bank A", no_hp_pic="+628123456789")
        member = Nasabah.objects.create(
            bank_sampah=bank,
            nomor="NAS-001",
            nama="Member",
            alamat="Jl. Test",
            no_hp="+628123456789",
            email=user.email,
        )
        AuthService._sync_nasabah_prefill(user)
        member.refresh_from_db()
        self.assertEqual(member.user_id, user.pk)
        self.assertEqual(user.role, User.Role.PENGELOLA)

    def test_roles_are_json_and_preserve_single_and_dual_role_accounts(self) -> None:
        self.assertIsInstance(User._meta.get_field("roles"), models.JSONField)
        for role in User.Role.values:
            with self.subTest(role=role):
                user = User.objects.create_user(email=f"{role}@example.com", role=role)
                user.refresh_from_db()
                self.assertEqual(user.roles, [role])
                self.assertEqual(user.role, role)
        dual = User.objects.create_user(
            email="dual@example.com",
            role=User.Role.PENGELOLA,
            roles=[User.Role.PENGELOLA, User.Role.NASABAH],
        )
        dual.refresh_from_db()
        self.assertEqual(dual.roles, [User.Role.PENGELOLA, User.Role.NASABAH])
        self.assertEqual(dual.role, User.Role.PENGELOLA)

    def test_pengelola_with_nasabah_role_can_keep_membership_when_primary_role_changes(
        self,
    ) -> None:
        user = User.objects.create_user(
            email="member@example.com",
            role=User.Role.PENGELOLA,
            roles=[User.Role.PENGELOLA, User.Role.NASABAH],
        )
        bank = BankSampah.objects.create(nama="Bank A", no_hp_pic="+628123456789")
        member = Nasabah.objects.create(
            user=user,
            bank_sampah=bank,
            nomor="NAS-001",
            nama="Member",
            alamat="Jl. Test",
            no_hp="+628123456789",
            email=user.email,
        )
        user.role = User.Role.NASABAH
        user.save(update_fields=["role"])
        user.role = User.Role.PENGELOLA
        user.save(update_fields=["role"])
        user.refresh_from_db()
        member.refresh_from_db()
        self.assertEqual(member.user_id, user.pk)
        self.assertEqual(user.role, User.Role.PENGELOLA)
        self.assertIn(User.Role.NASABAH, user.roles)

    def test_permissions_use_each_devices_active_role_without_mutating_account(self) -> None:
        user = User.objects.create_user(
            email="devices@example.com",
            role=User.Role.PENGELOLA,
            roles=[User.Role.PENGELOLA, User.Role.NASABAH],
            is_profile_complete=True,
        )
        factory = APIRequestFactory()
        for active_role in user.roles:
            with self.subTest(active_role=active_role):
                request = Request(factory.get("/"))
                request.user = user
                request.auth = {"role": active_role}
                self.assertEqual(
                    IsPengelola().has_permission(request, APIView()), active_role == "pengelola"
                )
                self.assertEqual(
                    IsNasabah().has_permission(request, APIView()), active_role == "nasabah"
                )
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.PENGELOLA)
        self.assertEqual(user.roles, [User.Role.PENGELOLA, User.Role.NASABAH])

    def test_authentication_rejects_unowned_and_malformed_claims_but_accepts_legacy_token(
        self,
    ) -> None:
        user = User.objects.create_user(email="claims@example.com")
        client = APIClient()
        legacy = AccessToken.for_user(user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {legacy}")
        self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)
        for claim in ("nasabah", "superadmin", "unknown", "", None, ["pengelola"], 1):
            with self.subTest(claim=claim):
                token = AccessToken.for_user(user)
                token["role"] = claim
                client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
                self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)

    def test_refresh_preserves_assigned_active_role_and_rejects_revoked_role(self) -> None:
        user = User.objects.create_user(
            email="refresh-roles@example.com",
            roles=[User.Role.PENGELOLA, User.Role.NASABAH],
        )
        refresh = RefreshToken.for_user(user)
        refresh["role"] = User.Role.NASABAH
        client = APIClient()
        response = client.post(
            "/api/v1/auth/refresh", {"refresh_token": str(refresh)}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AccessToken(response.data["access_token"])["role"], "nasabah")
        user.roles = [User.Role.PENGELOLA]
        user.save(update_fields=["roles"])
        self.assertEqual(
            client.post(
                "/api/v1/auth/refresh", {"refresh_token": str(refresh)}, format="json"
            ).status_code,
            401,
        )

    def test_new_sessions_put_primary_role_on_both_tokens(self) -> None:
        user = User.objects.create_user(
            email="session@example.com",
            role=User.Role.NASABAH,
            roles=[User.Role.NASABAH, User.Role.PENGELOLA],
        )
        session = AuthService._session_response(user, is_new_user=False)
        self.assertEqual(AccessToken(session["access_token"])["role"], "nasabah")
        self.assertEqual(RefreshToken(session["refresh_token"])["role"], "nasabah")
        self.assertEqual(session["user"]["role"], "nasabah")
        self.assertEqual(session["user"]["roles"], [User.Role.NASABAH, User.Role.PENGELOLA])

    def test_invalid_assigned_role_lists_cannot_be_saved(self) -> None:
        user = User.objects.create_user(email="invalid-roles@example.com")
        for roles in (
            [],
            "pengelola",
            {"pengelola": True},
            [None],
            ["unknown"],
            ["pengelola", "pengelola"],
            ["nasabah"],
        ):
            with self.subTest(roles=roles):
                user.roles = roles
                with self.assertRaises(ValidationError):
                    user.save(update_fields=["roles"])
                user.refresh_from_db()
                self.assertEqual(user.roles, ["pengelola"])
