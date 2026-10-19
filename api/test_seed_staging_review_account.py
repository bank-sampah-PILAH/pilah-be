from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from api.management.commands.seed_staging_review_account import (
    CONFIRMATION,
    REVIEW_ACCOUNTS,
    REVIEW_BANK_NAME,
    REVIEW_NASABAH_ADDRESS,
    REVIEW_NASABAH_EMAIL,
    REVIEW_NASABAH_ID,
    REVIEW_NASABAH_NUMBER,
    REVIEW_NASABAH_PHONE,
    REVIEW_PENGELOLA_EMAIL,
)
from api.management.commands.seed_testing_data import ACTIVE_BANK_ID, PENDING_BANK_ID
from api.models import BankSampah, Nasabah, User
from apps.bank_sampah.constants import REVIEW_BANK_ID

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
                self.assertEqual(user.is_primary_pengelola, email == REVIEW_PENGELOLA_EMAIL)
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
        self.assertTrue(reviewer.is_primary_pengelola)

        reviewer.role = User.Role.NASABAH
        reviewer.save(update_fields=["role"])
        with self.assertRaisesMessage(CommandError, "identity conflicts"):
            call_command("seed_staging_review_account", confirm=CONFIRMATION)
        reviewer.refresh_from_db()
        self.assertEqual(reviewer.role, User.Role.NASABAH)

    def test_seeded_reviewers_can_use_their_role_endpoints(self) -> None:
        call_command("seed_staging_review_account", confirm=CONFIRMATION)
        client = APIClient()
        for email, expected_status in (
            (REVIEW_PENGELOLA_EMAIL, 201),
            ("pilah.pengurus@pilah.com", 403),
        ):
            with self.subTest(email=email):
                client.force_authenticate(User.objects.get(email=email))
                self.assertEqual(client.post("/api/v1/team/invite").status_code, expected_status)

        client.force_authenticate(User.objects.get(email=REVIEW_NASABAH_EMAIL))
        response = client.get("/api/v1/nasabah/me/beranda")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["keanggotaan"]["id"], str(REVIEW_NASABAH_ID))

    def test_seed_repairs_owner_flag_when_bank_is_already_assigned(self) -> None:
        owner = User.objects.create_user(
            email=REVIEW_PENGELOLA_EMAIL,
            nama="Existing reviewer",
            role=User.Role.PENGELOLA,
            bank_sampah_id=ACTIVE_BANK_ID,
            is_profile_complete=True,
            password=REVIEWER_PASSWORD,
        )

        call_command("seed_staging_review_account", confirm=CONFIRMATION)

        owner.refresh_from_db()
        self.assertTrue(owner.is_primary_pengelola)
        self.assertEqual(owner.nama, "Existing reviewer")

    def test_seed_rejects_primary_permissions_on_the_pengurus_identity(self) -> None:
        pengurus = User.objects.create_user(
            email="pilah.pengurus@pilah.com",
            nama="Pengurus",
            role=User.Role.PENGELOLA,
            bank_sampah_id=ACTIVE_BANK_ID,
            is_primary_pengelola=True,
            password="old-password",
        )

        with self.assertRaisesMessage(CommandError, "account identity conflicts"):
            call_command("seed_staging_review_account", confirm=CONFIRMATION)

        pengurus.refresh_from_db()
        self.assertTrue(pengurus.is_primary_pengelola)
        self.assertTrue(pengurus.check_password("old-password"))
        self.assertFalse(User.objects.filter(email=REVIEW_PENGELOLA_EMAIL).exists())

    def test_superadmin_can_approve_only_the_review_scoped_pending_bank(self) -> None:
        other_bank = BankSampah.objects.create(
            id=PENDING_BANK_ID,
            nama="Other pending E2E bank",
            no_hp_pic="",
            status=BankSampah.Status.PENDING,
            is_active=False,
        )
        call_command("seed_staging_review_account", confirm=CONFIRMATION)
        client = APIClient()
        client.force_authenticate(User.objects.get(email=REVIEWER_EMAIL))

        queue = client.get("/api/v1/superadmin/bank-sampah")
        self.assertEqual(queue.status_code, 200)
        self.assertEqual([row["id"] for row in queue.data["results"]], [str(REVIEW_BANK_ID)])
        self.assertEqual(
            client.post(f"/api/v1/superadmin/bank-sampah/{other_bank.pk}/approve").status_code,
            404,
        )
        self.assertEqual(
            client.post(f"/api/v1/superadmin/bank-sampah/{REVIEW_BANK_ID}/approve").status_code,
            200,
        )

        call_command("seed_staging_review_account", confirm=CONFIRMATION)

        bank = BankSampah.objects.get(pk=REVIEW_BANK_ID)
        self.assertEqual(bank.status, BankSampah.Status.ACTIVE)
        self.assertTrue(bank.is_active)
        self.assertEqual(bank.approval_logs.count(), 1)
        self.assertEqual(client.get("/api/v1/superadmin/bank-sampah").data["count"], 0)
        other_bank.refresh_from_db()
        self.assertEqual(other_bank.status, BankSampah.Status.PENDING)

    def test_superadmin_can_reject_the_review_bank_without_reseed_resetting_it(self) -> None:
        call_command("seed_staging_review_account", confirm=CONFIRMATION)
        client = APIClient()
        client.force_authenticate(User.objects.get(email=REVIEWER_EMAIL))
        response = client.post(
            f"/api/v1/superadmin/bank-sampah/{REVIEW_BANK_ID}/reject",
            {"catatan": "Review rejection"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        call_command("seed_staging_review_account", confirm=CONFIRMATION)

        bank = BankSampah.objects.get(pk=REVIEW_BANK_ID)
        self.assertEqual(bank.status, BankSampah.Status.REJECTED)
        self.assertFalse(bank.is_active)
        self.assertEqual(bank.approval_logs.count(), 1)
        self.assertEqual(client.get("/api/v1/superadmin/bank-sampah").data["count"], 0)

    def test_seed_rejects_conflicting_review_bank_without_creating_accounts(self) -> None:
        for name, status, active in (
            ("Unrelated bank", BankSampah.Status.PENDING, False),
            (REVIEW_BANK_NAME, BankSampah.Status.ACTIVE, False),
            (REVIEW_BANK_NAME, "invalid-status", False),
        ):
            with self.subTest(name=name, status=status, active=active):
                bank = BankSampah.objects.create(
                    id=REVIEW_BANK_ID,
                    nama=name,
                    no_hp_pic="",
                    status=status,
                    is_active=active,
                )
                with self.assertRaisesMessage(CommandError, "review bank identity conflicts"):
                    call_command("seed_staging_review_account", confirm=CONFIRMATION)
                self.assertFalse(User.objects.filter(email__in=REVIEWER_EMAILS).exists())
                bank.refresh_from_db()
                self.assertEqual((bank.nama, bank.status, bank.is_active), (name, status, active))
                bank.delete()

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

    def test_seed_rejects_an_unusable_fixture_bank_without_changing_it(self) -> None:
        for active, status in (
            (False, BankSampah.Status.ACTIVE),
            (True, BankSampah.Status.PENDING),
            (True, BankSampah.Status.REJECTED),
        ):
            with self.subTest(active=active, status=status):
                BankSampah.objects.filter(pk=ACTIVE_BANK_ID).update(is_active=active, status=status)
                with self.assertRaisesMessage(CommandError, "active staging E2E bank is required"):
                    call_command("seed_staging_review_account", confirm=CONFIRMATION)
                bank = BankSampah.objects.get(pk=ACTIVE_BANK_ID)
                self.assertEqual((bank.is_active, bank.status), (active, status))
                self.assertFalse(User.objects.filter(email__in=REVIEWER_EMAILS).exists())

    def test_seed_rejects_unusable_memberships_and_rolls_back_account_repairs(self) -> None:
        for linked in (False, True):
            for active, status in (
                (False, Nasabah.Status.APPROVED),
                (True, Nasabah.Status.PENDING),
                (True, Nasabah.Status.REJECTED),
            ):
                with self.subTest(linked=linked, active=active, status=status):
                    user = (
                        User.objects.create_user(
                            email=REVIEW_NASABAH_EMAIL,
                            nama="Existing member",
                            role=User.Role.NASABAH,
                            password="old-password",
                        )
                        if linked
                        else None
                    )
                    membership = Nasabah.objects.create(
                        id=REVIEW_NASABAH_ID,
                        user=user,
                        bank_sampah_id=ACTIVE_BANK_ID,
                        nomor=REVIEW_NASABAH_NUMBER,
                        nama="Demo Nasabah PILAH",
                        alamat=REVIEW_NASABAH_ADDRESS,
                        no_hp=REVIEW_NASABAH_PHONE,
                        email=REVIEW_NASABAH_EMAIL,
                        is_active=active,
                        status=status,
                    )

                    with self.assertRaisesMessage(CommandError, "membership identity conflicts"):
                        call_command("seed_staging_review_account", confirm=CONFIRMATION)

                    membership.refresh_from_db()
                    self.assertEqual((membership.is_active, membership.status), (active, status))
                    self.assertEqual(membership.user_id, user.pk if user else None)
                    self.assertEqual(
                        User.objects.filter(email__in=REVIEWER_EMAILS).count(), int(linked)
                    )
                    membership.delete()
                    if user is not None:
                        user.refresh_from_db()
                        self.assertFalse(user.is_profile_complete)
                        self.assertTrue(user.check_password("old-password"))
                        user.delete()

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
