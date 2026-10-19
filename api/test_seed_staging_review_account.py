from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from api.management.commands.seed_staging_review_account import (
    CONFIRMATION,
    REVIEW_ACCOUNTS,
    REVIEW_NASABAH_ADDRESS,
    REVIEW_NASABAH_ID,
    REVIEW_NASABAH_NUMBER,
    REVIEW_NASABAH_PHONE,
)
from api.management.commands.seed_testing_data import ACTIVE_BANK_ID
from api.models import BankSampah, Nasabah, User

REVIEWER_EMAIL = "pilah.superadmin@pilah.com"
REVIEWER_EMAILS = tuple(email for email, _name, _role in REVIEW_ACCOUNTS)
REVIEWER_PASSWORD = "ReviewerLogin-Test-74!"


@override_settings(
    DEBUG=False,
    PILAH_ENVIRONMENT="staging",
    PILAH_SUPERADMIN_EMAILS=(),
    PILAH_REVIEW_SUPERADMIN_EMAILS=(REVIEWER_EMAIL,),
    PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS=REVIEWER_EMAILS,
    PILAH_REVIEW_ACCOUNT_PASSWORD=REVIEWER_PASSWORD,
)
class SeedStagingReviewAccountTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        BankSampah.objects.create(
            id=ACTIVE_BANK_ID,
            nama="Bank Sampah PILAH E2E",
            no_hp_pic="+628111111111",
            jenis_organisasi=BankSampah.OrganizationType.MANDIRI,
            status=BankSampah.Status.ACTIVE,
            is_active=True,
        )

    def test_seed_rejects_invalid_runtime_configuration(self) -> None:
        invalid_settings: tuple[tuple[dict[str, object], str, str], ...] = (
            ({"DEBUG": True}, CONFIRMATION, "only be seeded in staging"),
            ({}, "incorrect", "Pass --confirm="),
            (
                {"PILAH_REVIEW_SUPERADMIN_EMAILS": ()},
                CONFIRMATION,
                "PILAH_REVIEW_SUPERADMIN_EMAILS",
            ),
            (
                {"PILAH_SUPERADMIN_EMAILS": (REVIEWER_EMAIL,)},
                CONFIRMATION,
                "PILAH_REVIEW_SUPERADMIN_EMAILS",
            ),
            (
                {"PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS": (REVIEWER_EMAIL,)},
                CONFIRMATION,
                "PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS",
            ),
            (
                {"PILAH_REVIEW_ACCOUNT_PASSWORD": ""},
                CONFIRMATION,
                "PILAH_REVIEW_ACCOUNT_PASSWORD must be configured",
            ),
            (
                {"PILAH_REVIEW_ACCOUNT_PASSWORD": "short"},
                CONFIRMATION,
                "does not meet password requirements",
            ),
        )
        for overrides, confirmation, message in invalid_settings:
            with self.subTest(overrides=overrides):
                with self.settings(**overrides):
                    with self.assertRaisesMessage(CommandError, message):
                        call_command("seed_staging_review_account", confirm=confirmation)

    def test_seeded_reviewer_accounts_can_log_in_with_password(self) -> None:
        call_command("seed_staging_review_account", confirm=CONFIRMATION)
        call_command("seed_staging_review_account", confirm=CONFIRMATION)

        self.assertEqual(User.objects.filter(email__in=REVIEWER_EMAILS).count(), 4)
        client = APIClient()
        for email, _name, role in REVIEW_ACCOUNTS:
            with self.subTest(email=email):
                user = User.objects.get(email=email)
                self.assertEqual(User.objects.filter(email__iexact=email).count(), 1)
                self.assertEqual(user.role, role)
                self.assertFalse(user.is_staff)
                self.assertFalse(user.is_superuser)
                response = client.post(
                    "/api/v1/auth/login",
                    {"email": email, "password": REVIEWER_PASSWORD},
                    format="json",
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["user"]["email"], email)
                self.assertEqual(response.data["user"]["role"], role)
                self.assertEqual(
                    response.data["next_step"],
                    {
                        User.Role.PENGELOLA: "dashboard",
                        User.Role.NASABAH: "nasabah_dashboard",
                        User.Role.SUPERADMIN: "superadmin_dashboard",
                    }[role],
                )
        nasabah = User.objects.get(email="pilah.nasabah@pilah.com")
        self.assertEqual(
            nasabah.keanggotaan_nasabah.get().id,
            REVIEW_NASABAH_ID,
        )
        self.assertEqual(
            User.objects.get(email="pilah.pengelola@pilah.com").bank_sampah_id,
            ACTIVE_BANK_ID,
        )

    def test_seed_repairs_safe_existing_account_but_rejects_role_conflict(self) -> None:
        email, name, _role = REVIEW_ACCOUNTS[0]
        reviewer = User.objects.create_user(
            email=email.upper(),
            nama="",
            role=User.Role.PENGELOLA,
            is_profile_complete=False,
            password="old-password",
        )
        call_command("seed_staging_review_account", confirm=CONFIRMATION)
        reviewer.refresh_from_db()
        self.assertEqual(reviewer.email, email)
        self.assertEqual(reviewer.nama, name)
        self.assertTrue(reviewer.is_profile_complete)
        self.assertTrue(reviewer.check_password(REVIEWER_PASSWORD))
        self.assertEqual(reviewer.bank_sampah_id, ACTIVE_BANK_ID)

        reviewer.role = User.Role.NASABAH
        reviewer.save(update_fields=["role"])
        with self.assertRaisesMessage(CommandError, "identity conflicts"):
            call_command("seed_staging_review_account", confirm=CONFIRMATION)
        reviewer.refresh_from_db()
        self.assertEqual(reviewer.role, User.Role.NASABAH)

    def test_seed_repairs_existing_nasabah_profile(self) -> None:
        email, name, role = REVIEW_ACCOUNTS[2]
        nasabah = User.objects.create_user(
            email=email.upper(),
            nama="",
            role=role,
            is_profile_complete=False,
            password="old-password",
        )

        call_command("seed_staging_review_account", confirm=CONFIRMATION)

        nasabah.refresh_from_db()
        self.assertEqual(nasabah.email, email)
        self.assertEqual(nasabah.nama, name)
        self.assertTrue(nasabah.is_profile_complete)
        self.assertEqual(nasabah.no_hp, REVIEW_NASABAH_PHONE)
        self.assertEqual(nasabah.alamat, REVIEW_NASABAH_ADDRESS)
        self.assertTrue(nasabah.check_password(REVIEWER_PASSWORD))
        self.assertEqual(nasabah.keanggotaan_nasabah.get().id, REVIEW_NASABAH_ID)

    def test_seed_rejects_duplicate_case_insensitive_identities(self) -> None:
        for email in (REVIEWER_EMAIL, REVIEWER_EMAIL.upper()):
            User.objects.create_user(
                email=email,
                nama="Reviewer",
                role=User.Role.SUPERADMIN,
                password=REVIEWER_PASSWORD,
            )
        with self.assertRaisesMessage(CommandError, "identity conflicts"):
            call_command("seed_staging_review_account", confirm=CONFIRMATION)

    def test_seed_rejects_account_linked_to_google_identity(self) -> None:
        email, _name, role = REVIEW_ACCOUNTS[0]
        reviewer = User.objects.create_user(
            email=email,
            nama="Reviewer",
            role=role,
            password=REVIEWER_PASSWORD,
        )
        reviewer.google_id = "google-reviewer-id"
        reviewer.save(update_fields=["google_id"])

        with self.assertRaisesMessage(CommandError, "identity conflicts"):
            call_command("seed_staging_review_account", confirm=CONFIRMATION)

    def test_seed_requires_the_staging_e2e_bank(self) -> None:
        BankSampah.objects.filter(pk=ACTIVE_BANK_ID).delete()

        with self.assertRaisesMessage(CommandError, "staging E2E bank is required"):
            call_command("seed_staging_review_account", confirm=CONFIRMATION)

    def test_seed_rejects_conflicting_reviewer_membership(self) -> None:
        bank = BankSampah.objects.get(pk=ACTIVE_BANK_ID)
        Nasabah.objects.create(
            id=REVIEW_NASABAH_ID,
            bank_sampah=bank,
            nomor="WRONG-NUMBER",
            nama="Other member",
            alamat="Address",
            no_hp="+6289990000000",
            email="other@example.com",
        )

        with self.assertRaisesMessage(CommandError, "reviewer membership identity conflicts"):
            call_command("seed_staging_review_account", confirm=CONFIRMATION)
        self.assertFalse(User.objects.filter(email__in=REVIEWER_EMAILS).exists())

    def test_seed_links_an_existing_reviewer_membership_to_its_user(self) -> None:
        bank = BankSampah.objects.get(pk=ACTIVE_BANK_ID)
        membership = Nasabah.objects.create(
            id=REVIEW_NASABAH_ID,
            bank_sampah=bank,
            nomor=REVIEW_NASABAH_NUMBER,
            nama="Demo Nasabah PILAH",
            alamat=REVIEW_NASABAH_ADDRESS,
            no_hp=REVIEW_NASABAH_PHONE,
            email="pilah.nasabah@pilah.com",
        )

        call_command("seed_staging_review_account", confirm=CONFIRMATION)

        membership.refresh_from_db()
        self.assertEqual(
            membership.user_id,
            User.objects.get(email="pilah.nasabah@pilah.com").pk,
        )

    def test_seed_rejects_duplicate_reviewer_memberships(self) -> None:
        bank = BankSampah.objects.get(pk=ACTIVE_BANK_ID)
        Nasabah.objects.create(
            id=REVIEW_NASABAH_ID,
            bank_sampah=bank,
            nomor=REVIEW_NASABAH_NUMBER,
            nama="Demo Nasabah PILAH",
            alamat=REVIEW_NASABAH_ADDRESS,
            no_hp=REVIEW_NASABAH_PHONE,
            email="pilah.nasabah@pilah.com",
        )
        other_bank = BankSampah.objects.create(
            nama="Other Bank",
            no_hp_pic="+628222222222",
            status=BankSampah.Status.ACTIVE,
            is_active=True,
        )
        Nasabah.objects.create(
            bank_sampah=other_bank,
            nomor="OTHER-REVIEW",
            nama="Other reviewer member",
            alamat="Other address",
            no_hp="+628222222223",
            email="pilah.nasabah@pilah.com",
        )

        with self.assertRaisesMessage(CommandError, "membership identity conflicts"):
            call_command("seed_staging_review_account", confirm=CONFIRMATION)
