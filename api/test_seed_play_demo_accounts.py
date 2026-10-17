from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from api.management.commands.seed_play_demo_accounts import DEMO_NASABAH_EMAIL
from api.models import BankSampah, Nasabah, Saldo, User

SUPERADMIN_EMAIL = "pilah.superadmin@gmail.com"
PRODUCTION_SETTINGS = {
    "DEBUG": False,
    "PILAH_ENVIRONMENT": "production",
    "PILAH_SUPERADMIN_EMAILS": (SUPERADMIN_EMAIL,),
}


@override_settings(**PRODUCTION_SETTINGS)
class SeedPlayDemoAccountsTests(TestCase):
    def test_requires_production_runtime_and_confirmation(self) -> None:
        with self.assertRaisesRegex(CommandError, "production"):
            with override_settings(PILAH_ENVIRONMENT="staging"):
                call_command("seed_play_demo_accounts", confirm_production=True)

        with self.assertRaisesRegex(CommandError, "--confirm-production"):
            call_command("seed_play_demo_accounts")

        self.assertFalse(User.objects.exists())
        self.assertFalse(BankSampah.objects.exists())

    def test_dry_run_validates_without_writing(self) -> None:
        output = StringIO()

        call_command("seed_play_demo_accounts", dry_run=True, stdout=output)

        self.assertIn("Dry run", output.getvalue())
        self.assertIn("4 Google accounts", output.getvalue())
        self.assertFalse(User.objects.exists())
        self.assertFalse(BankSampah.objects.exists())
        self.assertFalse(Nasabah.objects.exists())
        self.assertFalse(Saldo.objects.exists())

    def test_debug_mode_is_rejected_even_with_production_runtime(self) -> None:
        with override_settings(DEBUG=True):
            with self.assertRaisesRegex(CommandError, "production"):
                call_command("seed_play_demo_accounts", dry_run=True, stdout=StringIO())

        self.assertFalse(User.objects.exists())
        self.assertFalse(BankSampah.objects.exists())

    def test_creates_idempotent_demo_roles_and_preserves_other_tenants(self) -> None:
        other_bank = BankSampah.objects.create(
            nama="Unrelated bank",
            no_hp_pic="",
        )
        unrelated = User.objects.create_user(
            email="unrelated@example.com",
            nama="Unrelated User",
            role=User.Role.PENGELOLA,
            bank_sampah=other_bank,
            is_primary_pengelola=True,
        )
        other_bank_before = BankSampah.objects.filter(pk=other_bank.pk).values().get()
        unrelated_before = User.objects.filter(pk=unrelated.pk).values().get()

        call_command("seed_play_demo_accounts", confirm_production=True, stdout=StringIO())
        demo_users_before = list(
            User.objects.filter(email__startswith="pilah.").order_by("email").values()
        )
        demo_bank = BankSampah.objects.get(nama="Bank Sampah PILAH Demo")
        demo_bank_before = BankSampah.objects.filter(pk=demo_bank.pk).values().get()
        demo_member_before = Nasabah.objects.filter(email=DEMO_NASABAH_EMAIL).values().get()
        demo_saldo_before = Saldo.objects.filter(nasabah__email=DEMO_NASABAH_EMAIL).values().get()
        call_command("seed_play_demo_accounts", confirm_production=True, stdout=StringIO())

        bank = BankSampah.objects.get(nama="Bank Sampah PILAH Demo")
        owner = User.objects.get(email="pilah.pengelola@gmail.com")
        pengurus = User.objects.get(email="pilah.pengurus@gmail.com")
        nasabah_user = User.objects.get(email="pilah.nasabah@gmail.com")
        superadmin = User.objects.get(email=SUPERADMIN_EMAIL)

        self.assertEqual(owner.role, User.Role.PENGELOLA)
        self.assertEqual(owner.bank_sampah, bank)
        self.assertTrue(owner.is_primary_pengelola)
        self.assertTrue(owner.is_profile_complete)
        self.assertEqual(pengurus.role, User.Role.PENGELOLA)
        self.assertEqual(pengurus.bank_sampah, bank)
        self.assertFalse(pengurus.is_primary_pengelola)
        self.assertEqual(nasabah_user.role, User.Role.NASABAH)
        self.assertIsNone(nasabah_user.bank_sampah)
        self.assertEqual(superadmin.role, User.Role.SUPERADMIN)
        self.assertIsNone(superadmin.bank_sampah)
        for user in (owner, pengurus, nasabah_user, superadmin):
            self.assertFalse(user.has_usable_password())
            self.assertIsNone(user.google_id)

        membership = Nasabah.objects.get(bank_sampah=bank, user=nasabah_user)
        self.assertTrue(membership.is_active)
        self.assertEqual(membership.status, Nasabah.Status.APPROVED)
        self.assertEqual(Saldo.objects.get(nasabah=membership).total_saldo, 0)
        self.assertEqual(BankSampah.objects.count(), 2)
        self.assertEqual(User.objects.count(), 5)
        self.assertEqual(
            BankSampah.objects.filter(pk=other_bank.pk).values().get(), other_bank_before
        )
        self.assertEqual(User.objects.filter(pk=unrelated.pk).values().get(), unrelated_before)
        self.assertEqual(
            list(User.objects.filter(email__startswith="pilah.").order_by("email").values()),
            demo_users_before,
        )
        self.assertEqual(BankSampah.objects.filter(pk=bank.pk).values().get(), demo_bank_before)
        self.assertEqual(
            Nasabah.objects.filter(pk=membership.pk).values().get(), demo_member_before
        )
        self.assertEqual(Saldo.objects.filter(nasabah=membership).values().get(), demo_saldo_before)

    def test_existing_target_with_conflicting_role_fails_without_partial_writes(self) -> None:
        User.objects.create_user(
            email="pilah.pengelola@gmail.com",
            nama="Existing Nasabah",
            role=User.Role.NASABAH,
        )

        with self.assertRaisesRegex(CommandError, "conflict"):
            call_command("seed_play_demo_accounts", confirm_production=True, stdout=StringIO())

        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(BankSampah.objects.exists())

    def test_conflicting_bank_fails_before_writes(self) -> None:
        BankSampah.objects.create(
            id="00000000-0000-4000-8000-000000000362",
            nama="Unrelated bank",
            no_hp_pic="",
        )

        with self.assertRaisesRegex(CommandError, "bank identity"):
            call_command("seed_play_demo_accounts", dry_run=True, stdout=StringIO())

        self.assertFalse(User.objects.exists())
        self.assertEqual(BankSampah.objects.count(), 1)

    def test_customer_email_already_used_by_another_bank_fails_without_writes(self) -> None:
        other_bank = BankSampah.objects.create(nama="Unrelated bank", no_hp_pic="")
        Nasabah.objects.create(
            bank_sampah=other_bank,
            nomor="OTHER-0001",
            nama="Other bank member",
            alamat="Alamat anggota bank lain",
            no_hp="",
            email=DEMO_NASABAH_EMAIL,
        )

        with self.assertRaisesRegex(CommandError, "another bank"):
            call_command("seed_play_demo_accounts", dry_run=True, stdout=StringIO())

        self.assertFalse(User.objects.exists())
        self.assertEqual(BankSampah.objects.count(), 1)
        self.assertEqual(Nasabah.objects.count(), 1)

    def test_reserved_member_id_collision_fails_before_writes(self) -> None:
        other_bank = BankSampah.objects.create(nama="Unrelated bank", no_hp_pic="")
        Nasabah.objects.create(
            id="00000000-0000-4000-8000-000000000363",
            bank_sampah=other_bank,
            nomor="OTHER-0001",
            nama="Other bank member",
            alamat="Alamat anggota bank lain",
            no_hp="",
            email="other@example.com",
        )

        with self.assertRaisesRegex(CommandError, "identity conflicts"):
            call_command("seed_play_demo_accounts", dry_run=True, stdout=StringIO())

        self.assertFalse(User.objects.exists())
        self.assertEqual(BankSampah.objects.count(), 1)
        self.assertEqual(Nasabah.objects.count(), 1)

    def test_unlinked_demo_membership_is_attached_to_seeded_account(self) -> None:
        bank = BankSampah.objects.create(
            id="00000000-0000-4000-8000-000000000362",
            nama="Bank Sampah PILAH Demo",
            no_hp_pic="",
        )
        membership = Nasabah.objects.create(
            id="00000000-0000-4000-8000-000000000363",
            bank_sampah=bank,
            nomor="DEMO-0001",
            nama="Demo Nasabah PILAH",
            alamat="Alamat data demo PILAH",
            no_hp="",
            email=DEMO_NASABAH_EMAIL,
        )

        call_command("seed_play_demo_accounts", confirm_production=True, stdout=StringIO())

        membership.refresh_from_db()
        self.assertEqual(membership.user_id, User.objects.get(email=DEMO_NASABAH_EMAIL).pk)
        self.assertEqual(Saldo.objects.get(nasabah=membership).total_saldo, 0)

    def test_write_failure_rolls_back_the_whole_seed(self) -> None:
        with patch.object(Saldo.objects, "get_or_create", side_effect=RuntimeError("fail")):
            with self.assertRaisesRegex(RuntimeError, "fail"):
                call_command(
                    "seed_play_demo_accounts",
                    confirm_production=True,
                    stdout=StringIO(),
                )

        self.assertFalse(User.objects.exists())
        self.assertFalse(BankSampah.objects.exists())
        self.assertFalse(Nasabah.objects.exists())

    def test_existing_bootstrapped_superadmin_is_not_rewritten(self) -> None:
        superadmin = User.objects.create_user(
            email=SUPERADMIN_EMAIL,
            nama="SuperAdmin PILAH",
            role=User.Role.SUPERADMIN,
            is_profile_complete=True,
        )
        before = User.objects.filter(pk=superadmin.pk).values().get()

        call_command("seed_play_demo_accounts", confirm_production=True, stdout=StringIO())

        self.assertEqual(User.objects.filter(pk=superadmin.pk).values().get(), before)

    def test_superadmin_must_be_allowlisted(self) -> None:
        with override_settings(PILAH_SUPERADMIN_EMAILS=()):
            with self.assertRaisesRegex(CommandError, "PILAH_SUPERADMIN_EMAILS"):
                call_command("seed_play_demo_accounts", dry_run=True, stdout=StringIO())

        self.assertFalse(User.objects.exists())
        self.assertFalse(BankSampah.objects.exists())

    def test_existing_matching_google_identity_is_preserved(self) -> None:
        user = User.objects.create_user(
            email="pilah.pengelola@gmail.com",
            password="keep-existing-password",
            google_id="google-account-id",
            nama="Google Profile Name",
            no_hp="+628123456789",
            role=User.Role.PENGELOLA,
        )

        call_command("seed_play_demo_accounts", confirm_production=True, stdout=StringIO())

        user.refresh_from_db()
        self.assertEqual(user.google_id, "google-account-id")
        self.assertEqual(user.nama, "Google Profile Name")
        self.assertEqual(user.no_hp, "+628123456789")
        self.assertTrue(user.check_password("keep-existing-password"))
        self.assertTrue(user.is_primary_pengelola)
