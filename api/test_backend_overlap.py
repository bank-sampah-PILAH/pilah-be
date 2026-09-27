from django.contrib.auth.models import AnonymousUser
from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from api.models import BankSampah, User
from api.permissions import IsActiveNasabah, IsActivePengelolaOrNasabah, IsNasabah


class BackendOverlapTests(SimpleTestCase):
    def test_all_feature_migrations_reach_one_leaf(self) -> None:
        loader = MigrationLoader(None)
        self.assertEqual(loader.detect_conflicts(), {})
        leaves = loader.graph.leaf_nodes("api")
        self.assertEqual(len(leaves), 1)
        ancestors = loader.graph.forwards_plan(leaves[0])
        for name in (
            "0013_merge_nasabah_migration_branches",
            "0013_merge_pencairan_and_nasabah_email",
            "0014_alter_nasabah_unique_together_alter_nasabah_email_and_more",
        ):
            self.assertIn(("api", name), ancestors)

    def test_combined_permission_uses_active_account_without_profile_gate(self) -> None:
        for active in (True, False):
            with self.subTest(active=active):
                user = User(role=User.Role.NASABAH, is_active=active, is_profile_complete=False)
                raw = APIRequestFactory().get("/api/v1/pencairan")
                force_authenticate(raw, user=user)
                request = Request(raw)
                self.assertEqual(IsActiveNasabah().has_permission(request, APIView()), active)
                self.assertEqual(
                    IsActivePengelolaOrNasabah().has_permission(request, APIView()), active
                )
                # Registration still has its separate, complete-profile requirement.
                self.assertFalse(IsNasabah().has_permission(request, APIView()))

    def test_combined_permission_preserves_manager_bank_gate_and_denies_anonymous(self) -> None:
        bank = BankSampah(status=BankSampah.Status.ACTIVE, is_active=True)
        user = User(role=User.Role.PENGELOLA, bank_sampah=bank, is_profile_complete=True)
        for active in (True, False):
            bank.is_active = active
            raw = APIRequestFactory().get("/api/v1/pencairan")
            force_authenticate(raw, user=user)
            self.assertEqual(
                IsActivePengelolaOrNasabah().has_permission(Request(raw), APIView()), active
            )
        raw = APIRequestFactory().get("/api/v1/pencairan")
        force_authenticate(raw, user=AnonymousUser())
        self.assertFalse(IsActivePengelolaOrNasabah().has_permission(Request(raw), APIView()))
