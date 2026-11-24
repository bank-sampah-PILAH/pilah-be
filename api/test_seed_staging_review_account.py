from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone
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
    REVIEW_OWN_BANK_ID,
    REVIEW_OWN_BANK_NAME,
    REVIEW_PENGELOLA_EMAIL,
)
from api.management.commands.seed_testing_data import (
    ACTIVE_BANK_ID,
    PENDING_BANK_ID,
)
from api.management.commands.seed_testing_data import CONFIRMATION as E2E_CONFIRMATION
from api.models import (
    BankSampah,
    DetailTransaksi,
    HargaSampah,
    JadwalKegiatan,
    JenisSampah,
    Nasabah,
    Saldo,
    Transaksi,
    User,
)
from api.seed_sample_data import REVIEWER_SAMPLE_IDS
from apps.bank_sampah.constants import REVIEW_BANK_ID
from apps.waste_catalog.services import catat_harga

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
            REVIEW_OWN_BANK_ID,
        )
        nasabah_membership = Nasabah.objects.get(pk=REVIEW_NASABAH_ID)
        self.assertEqual(nasabah_membership.bank_sampah_id, REVIEW_OWN_BANK_ID)

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
        self.assertEqual(reviewer.bank_sampah_id, REVIEW_OWN_BANK_ID)
        self.assertTrue(reviewer.is_primary_pengelola)

        reviewer.role = User.Role.NASABAH
        reviewer.roles = [User.Role.NASABAH]
        reviewer.save(update_fields=["role", "roles"])
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

    def test_seed_moves_an_existing_reviewer_out_of_the_e2e_bank(self) -> None:
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
        self.assertEqual(owner.bank_sampah_id, REVIEW_OWN_BANK_ID)
        self.assertTrue(owner.is_primary_pengelola)
        self.assertEqual(owner.nama, "Existing reviewer")

    def test_reviewer_bank_is_active_standalone_and_holds_one_primary(self) -> None:
        call_command("seed_staging_review_account", confirm=CONFIRMATION)

        bank = BankSampah.objects.get(pk=REVIEW_OWN_BANK_ID)
        self.assertEqual(bank.nama, REVIEW_OWN_BANK_NAME)
        self.assertEqual(bank.jenis_organisasi, BankSampah.OrganizationType.MANDIRI)
        self.assertEqual((bank.status, bank.is_active), (BankSampah.Status.ACTIVE, True))
        self.assertEqual(
            sorted(User.objects.filter(bank_sampah=bank).values_list("email", flat=True)),
            ["pilah.pengelola@pilah.com", "pilah.pengurus@pilah.com"],
        )
        self.assertEqual(
            list(
                User.objects.filter(bank_sampah=bank, is_primary_pengelola=True).values_list(
                    "email", flat=True
                )
            ),
            [REVIEW_PENGELOLA_EMAIL],
        )

    def _sample_counts(self) -> dict[str, int]:
        return {
            "jenis": JenisSampah.objects.filter(bank_sampah_id=REVIEW_OWN_BANK_ID).count(),
            "harga": HargaSampah.objects.filter(
                jenis_sampah__bank_sampah_id=REVIEW_OWN_BANK_ID
            ).count(),
            "transaksi": Transaksi.objects.filter(bank_sampah_id=REVIEW_OWN_BANK_ID).count(),
            "detail": DetailTransaksi.objects.filter(
                transaksi__bank_sampah_id=REVIEW_OWN_BANK_ID
            ).count(),
            "jadwal": JadwalKegiatan.objects.filter(bank_sampah_id=REVIEW_OWN_BANK_ID).count(),
        }

    def test_reviewer_bank_has_catalog_setoran_schedules_and_a_nasabah_balance(self) -> None:
        call_command("seed_staging_review_account", confirm=CONFIRMATION)

        self.assertEqual(
            self._sample_counts(),
            {"jenis": 4, "harga": 4, "transaksi": 3, "detail": 4, "jadwal": 2},
        )
        membership = Nasabah.objects.get(pk=REVIEW_NASABAH_ID)
        total = sum(
            (t.total_nilai for t in Transaksi.objects.filter(nasabah=membership)),
            start=Decimal(0),
        )
        self.assertGreater(total, 0)
        self.assertEqual(Saldo.objects.get(nasabah=membership).total_saldo, total)
        pengurus = User.objects.get(email="pilah.pengurus@pilah.com")
        self.assertEqual(
            set(
                Transaksi.objects.filter(bank_sampah_id=REVIEW_OWN_BANK_ID).values_list(
                    "dicatat_oleh", flat=True
                )
            ),
            {pengurus.pk},
        )

    def test_sample_data_is_not_duplicated_by_a_second_run(self) -> None:
        call_command("seed_staging_review_account", confirm=CONFIRMATION)
        first = self._sample_counts()
        saldo = Saldo.objects.get(nasabah_id=REVIEW_NASABAH_ID).total_saldo

        call_command("seed_staging_review_account", confirm=CONFIRMATION)

        self.assertEqual(self._sample_counts(), first)
        self.assertEqual(Saldo.objects.get(nasabah_id=REVIEW_NASABAH_ID).total_saldo, saldo)

    def test_a_waste_type_whose_only_price_is_still_in_the_future_aborts_the_seed(self) -> None:
        call_command("seed_staging_review_account", confirm=CONFIRMATION)
        jenis = JenisSampah.objects.get(pk=REVIEWER_SAMPLE_IDS.waste_types[0])
        HargaSampah.objects.filter(jenis_sampah=jenis).delete()
        catat_harga(jenis, Decimal(3500), timezone.now() + timedelta(days=30), oleh=None)

        with self.assertRaisesMessage(CommandError, f"waste type {jenis.pk} has no active price"):
            call_command("seed_staging_review_account", confirm=CONFIRMATION)

    def test_sample_data_ids_do_not_collide_with_the_production_demo_or_e2e_fixture(self) -> None:
        from api.management.commands import seed_play_demo_accounts as demo

        used = {
            *demo.WASTE_TYPE_IDS,
            *demo.TRANSACTION_IDS,
            *demo.DETAIL_IDS,
            *demo.SCHEDULE_IDS,
            demo.DEMO_NASABAH_ID,
            demo.REVIEW_OWNER_ID,
            REVIEW_NASABAH_ID,
        }
        mine = {
            *REVIEWER_SAMPLE_IDS.waste_types,
            *REVIEWER_SAMPLE_IDS.transactions,
            *REVIEWER_SAMPLE_IDS.details,
            *REVIEWER_SAMPLE_IDS.schedules,
        }
        self.assertFalse(mine & used)
        self.assertEqual(len(mine), 13)

    def test_e2e_bank_history_of_the_reviewer_nasabah_is_left_where_it_is(self) -> None:
        user = User.objects.create_user(
            email=REVIEW_NASABAH_EMAIL,
            nama="Demo Nasabah PILAH",
            role=User.Role.NASABAH,
            password=REVIEWER_PASSWORD,
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
        )
        recorder = User.objects.create_user(
            email="old.recorder@example.com",
            nama="Old recorder",
            role=User.Role.PENGELOLA,
            bank_sampah_id=ACTIVE_BANK_ID,
            password=REVIEWER_PASSWORD,
        )
        old = Transaksi.objects.create(
            dicatat_oleh=recorder,
            nasabah=membership,
            bank_sampah_id=ACTIVE_BANK_ID,
            tipe=Transaksi.Tipe.SETORAN,
            total_nilai=Decimal(1000),
        )

        call_command("seed_staging_review_account", confirm=CONFIRMATION)

        old.refresh_from_db()
        self.assertEqual(old.bank_sampah_id, ACTIVE_BANK_ID)
        membership.refresh_from_db()
        self.assertEqual(membership.bank_sampah_id, REVIEW_OWN_BANK_ID)
        self.assertEqual(
            Saldo.objects.get(nasabah=membership).total_saldo,
            old.total_nilai
            + sum(
                (
                    t.total_nilai
                    for t in Transaksi.objects.filter(bank_sampah_id=REVIEW_OWN_BANK_ID)
                ),
                start=Decimal(0),
            ),
        )

    def test_seed_does_not_need_the_e2e_bank(self) -> None:
        BankSampah.objects.filter(pk=ACTIVE_BANK_ID).delete()

        call_command("seed_staging_review_account", confirm=CONFIRMATION)

        self.assertEqual(
            User.objects.get(email=REVIEW_PENGELOLA_EMAIL).bank_sampah_id, REVIEW_OWN_BANK_ID
        )

    def test_seed_moves_the_legacy_reviewer_pair_and_leaves_other_accounts_alone(self) -> None:
        other = User.objects.create_user(
            email="someone.else@example.com",
            nama="Someone else",
            role=User.Role.PENGELOLA,
            bank_sampah_id=ACTIVE_BANK_ID,
            is_primary_pengelola=True,
            password="old-password",
        )
        for email in (REVIEW_PENGELOLA_EMAIL, "pilah.pengurus@pilah.com"):
            User.objects.create_user(
                email=email,
                nama=email,
                role=User.Role.PENGELOLA,
                bank_sampah_id=ACTIVE_BANK_ID,
                password=REVIEWER_PASSWORD,
            )

        for _ in range(2):
            call_command("seed_staging_review_account", confirm=CONFIRMATION)

        other.refresh_from_db()
        self.assertEqual((other.bank_sampah_id, other.is_primary_pengelola), (ACTIVE_BANK_ID, True))
        for email, primary in ((REVIEW_PENGELOLA_EMAIL, True), ("pilah.pengurus@pilah.com", False)):
            user = User.objects.get(email=email)
            self.assertEqual(
                (user.bank_sampah_id, user.is_primary_pengelola), (REVIEW_OWN_BANK_ID, primary)
            )

    def test_seed_rejects_a_reviewer_who_belongs_to_another_bank(self) -> None:
        elsewhere = BankSampah.objects.create(
            nama="Elsewhere", no_hp_pic="", status=BankSampah.Status.ACTIVE, is_active=True
        )
        User.objects.create_user(
            email=REVIEW_PENGELOLA_EMAIL,
            nama="Reviewer",
            role=User.Role.PENGELOLA,
            bank_sampah=elsewhere,
            password=REVIEWER_PASSWORD,
        )

        with self.assertRaisesMessage(CommandError, "identity conflicts"):
            call_command("seed_staging_review_account", confirm=CONFIRMATION)

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

    def test_seed_rejects_a_conflicting_reviewer_bank_without_creating_accounts(self) -> None:
        for name, status, active in (
            ("Unrelated bank", BankSampah.Status.ACTIVE, True),
            (REVIEW_OWN_BANK_NAME, BankSampah.Status.PENDING, False),
            (REVIEW_OWN_BANK_NAME, BankSampah.Status.ACTIVE, False),
        ):
            with self.subTest(name=name, status=status, active=active):
                bank = BankSampah.objects.create(
                    id=REVIEW_OWN_BANK_ID,
                    nama=name,
                    no_hp_pic="",
                    status=status,
                    is_active=active,
                )
                with self.assertRaisesMessage(CommandError, "reviewer bank identity conflicts"):
                    call_command("seed_staging_review_account", confirm=CONFIRMATION)
                self.assertFalse(User.objects.filter(email__in=REVIEWER_EMAILS).exists())
                bank.delete()

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
        self.assertEqual(membership.bank_sampah_id, REVIEW_OWN_BANK_ID)

    def test_seed_preserves_memberships_registered_with_other_banks(self) -> None:
        call_command("seed_staging_review_account", confirm=CONFIRMATION)
        user = User.objects.get(email=REVIEW_NASABAH_EMAIL)
        other_bank = BankSampah.objects.create(
            nama="Other Bank",
            no_hp_pic="+628222222222",
            status=BankSampah.Status.ACTIVE,
            is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user)
        response = client.post(
            "/api/v1/onboarding/nasabah",
            {"bank_sampah_id": str(other_bank.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        membership = user.keanggotaan_nasabah.get(bank_sampah=other_bank)
        self.assertEqual(membership.status, Nasabah.Status.PENDING)

        for status, active, expected_status in (
            (Nasabah.Status.PENDING, True, 403),
            (Nasabah.Status.APPROVED, True, 200),
            (Nasabah.Status.REJECTED, False, 403),
        ):
            with self.subTest(status=status, active=active):
                membership.status = status
                membership.is_active = active
                membership.save(update_fields=["status", "is_active"])

                call_command("seed_staging_review_account", confirm=CONFIRMATION)

                membership.refresh_from_db()
                self.assertEqual((membership.status, membership.is_active), (status, active))
                self.assertEqual(user.keanggotaan_nasabah.count(), 2)
                self.assertEqual(
                    client.get(
                        "/api/v1/nasabah/me/beranda", {"keanggotaan_id": str(membership.pk)}
                    ).status_code,
                    expected_status,
                )
                self.assertEqual(
                    client.get(
                        "/api/v1/nasabah/me/beranda", {"keanggotaan_id": str(REVIEW_NASABAH_ID)}
                    ).status_code,
                    200,
                )

    def test_seed_rejects_ambiguous_reviewer_memberships_in_the_fixture_bank(self) -> None:
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
        Nasabah.objects.create(
            bank_sampah=bank,
            nomor="OTHER-REVIEW",
            nama="Other reviewer member",
            alamat="Other address",
            no_hp="+628222222223",
            email=REVIEW_NASABAH_EMAIL.upper(),
        )

        with self.assertRaisesMessage(CommandError, "membership identity conflicts"):
            call_command("seed_staging_review_account", confirm=CONFIRMATION)


E2E_SUPERADMIN_EMAIL = "e2e.superadmin@example.com"


@override_settings(
    DEBUG=False,
    PILAH_ENVIRONMENT="staging",
    PILAH_SUPERADMIN_EMAILS=(E2E_SUPERADMIN_EMAIL,),
    PILAH_REVIEW_SUPERADMIN_EMAILS=(REVIEWER_EMAIL,),
    PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS=REVIEWER_EMAILS,
    PILAH_REVIEW_ACCOUNT_PASSWORD=REVIEWER_PASSWORD,
)
class SeedersKeepOnePrimaryPerBankTests(TestCase):
    """seed_testing_data and the reviewer seeder must never put two primaries in a bank."""

    @staticmethod
    def _seed_e2e() -> None:
        call_command(
            "seed_testing_data",
            environment="staging",
            confirm=E2E_CONFIRMATION,
            superadmin_email=E2E_SUPERADMIN_EMAIL,
        )

    @staticmethod
    def _seed_reviewers() -> None:
        call_command("seed_staging_review_account", confirm=CONFIRMATION)

    def _assert_one_primary_per_bank(self) -> None:
        self.assertEqual(
            list(
                User.objects.filter(
                    bank_sampah_id=ACTIVE_BANK_ID, is_primary_pengelola=True
                ).values_list("email", flat=True)
            ),
            ["pengurus.demo@example.com"],
        )
        self.assertEqual(
            list(
                User.objects.filter(
                    bank_sampah_id=REVIEW_OWN_BANK_ID, is_primary_pengelola=True
                ).values_list("email", flat=True)
            ),
            [REVIEW_PENGELOLA_EMAIL],
        )

    def test_e2e_then_reviewers(self) -> None:
        self._seed_e2e()
        self._seed_reviewers()

        self._assert_one_primary_per_bank()

    def test_reviewers_then_e2e(self) -> None:
        BankSampah.objects.create(
            id=ACTIVE_BANK_ID,
            nama="Bank Sampah PILAH E2E",
            no_hp_pic="+628111111111",
            jenis_organisasi=BankSampah.OrganizationType.MANDIRI,
            status=BankSampah.Status.ACTIVE,
            is_active=True,
        )
        self._seed_reviewers()
        self._seed_e2e()

        self._assert_one_primary_per_bank()

    def test_e2e_bank_data_is_not_touched_by_the_reviewer_seeder(self) -> None:
        self._seed_e2e()
        before = (
            JenisSampah.objects.filter(bank_sampah_id=ACTIVE_BANK_ID).count(),
            Transaksi.objects.filter(bank_sampah_id=ACTIVE_BANK_ID).count(),
            JadwalKegiatan.objects.filter(bank_sampah_id=ACTIVE_BANK_ID).count(),
        )

        self._seed_reviewers()

        after = (
            JenisSampah.objects.filter(bank_sampah_id=ACTIVE_BANK_ID).count(),
            Transaksi.objects.filter(bank_sampah_id=ACTIVE_BANK_ID).count(),
            JadwalKegiatan.objects.filter(bank_sampah_id=ACTIVE_BANK_ID).count(),
        )
        self.assertEqual(before, after)

    def test_both_twice_is_idempotent(self) -> None:
        for _ in range(2):
            self._seed_e2e()
            self._seed_reviewers()

        self._assert_one_primary_per_bank()

    def test_database_where_the_reviewer_was_primary_in_the_e2e_bank(self) -> None:
        # The state staging was in: reviewer primary in ACTIVE_BANK_ID. The
        # one-primary constraint forbids it beside the E2E primary, so the
        # migration demotes the reviewer first; the seeder then re-promotes it.
        self._seed_e2e()
        User.objects.create_user(
            email=REVIEW_PENGELOLA_EMAIL,
            nama="Demo Pengelola PILAH",
            role=User.Role.PENGELOLA,
            bank_sampah_id=ACTIVE_BANK_ID,
            is_profile_complete=True,
            is_primary_pengelola=False,
            password=REVIEWER_PASSWORD,
        )

        for _ in range(2):
            self._seed_reviewers()

        self._assert_one_primary_per_bank()

    def test_reviewer_primary_in_e2e_bank_before_e2e_pengurus_exists(self) -> None:
        BankSampah.objects.create(
            id=ACTIVE_BANK_ID,
            nama="Bank Sampah PILAH E2E",
            no_hp_pic="+628111111111",
            jenis_organisasi=BankSampah.OrganizationType.MANDIRI,
            status=BankSampah.Status.ACTIVE,
            is_active=True,
        )
        User.objects.create_user(
            email=REVIEW_PENGELOLA_EMAIL,
            nama="Demo Pengelola PILAH",
            role=User.Role.PENGELOLA,
            bank_sampah_id=ACTIVE_BANK_ID,
            is_profile_complete=True,
            is_primary_pengelola=True,
            password=REVIEWER_PASSWORD,
        )

        self._seed_reviewers()
        self._seed_e2e()

        self._assert_one_primary_per_bank()

    def test_e2e_seeder_still_refuses_to_share_a_bank_with_an_unrelated_primary(self) -> None:
        BankSampah.objects.create(
            id=ACTIVE_BANK_ID,
            nama="Bank Sampah PILAH E2E",
            no_hp_pic="+628111111111",
            jenis_organisasi=BankSampah.OrganizationType.MANDIRI,
            status=BankSampah.Status.ACTIVE,
            is_active=True,
        )
        other = User.objects.create_user(
            email="someone.else@example.com",
            nama="Someone else",
            role=User.Role.PENGELOLA,
            bank_sampah_id=ACTIVE_BANK_ID,
            is_primary_pengelola=True,
            password=REVIEWER_PASSWORD,
        )

        with self.assertRaises(IntegrityError):
            self._seed_e2e()

        other.refresh_from_db()
        self.assertTrue(other.is_primary_pengelola)
