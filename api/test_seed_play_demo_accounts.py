from datetime import time, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.management.commands.seed_play_demo_accounts import (
    ACCOUNTS,
    DEMO_BANK_ID,
    DEMO_NASABAH_EMAIL,
    DEMO_NASABAH_NUMBER,
    DEMO_PENGELOLA_EMAIL,
    DETAIL_IDS,
    REVIEW_OWNER_EMAIL,
    REVIEW_OWNER_ID,
    SCHEDULE_IDS,
    TRANSACTION_IDS,
    WASTE_TYPE_FIXTURES,
    WASTE_TYPE_IDS,
    Command,
    _seed_price,
)
from api.models import (
    BankSampah,
    DetailTransaksi,
    HargaSampah,
    JadwalKegiatan,
    JenisSampah,
    Nasabah,
    Pencairan,
    Saldo,
    Transaksi,
    User,
)
from apps.bank_sampah.constants import REVIEW_BANK_ID

SUPERADMIN_EMAIL = "pilah.superadmin@pilah.com"
TEST_REVIEW_ACCOUNT_PASSWORD = "unit-test-only-password"
REVIEW_ACCOUNT_EMAILS = (
    "pilah.pengelola@pilah.com",
    "pilah.pengurus@pilah.com",
    "pilah.nasabah@pilah.com",
    SUPERADMIN_EMAIL,
)
PRODUCTION_SETTINGS = {
    "DEBUG": False,
    "PILAH_ENVIRONMENT": "production",
    "PILAH_SUPERADMIN_EMAILS": (),
    "PILAH_REVIEW_SUPERADMIN_EMAILS": (SUPERADMIN_EMAIL,),
    "PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS": REVIEW_ACCOUNT_EMAILS,
    "PILAH_REVIEW_ACCOUNT_PASSWORD": TEST_REVIEW_ACCOUNT_PASSWORD,
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
        self.assertFalse(JenisSampah.objects.exists())
        self.assertFalse(Transaksi.objects.exists())
        self.assertFalse(JadwalKegiatan.objects.exists())
        self.assertFalse(Saldo.objects.exists())

    def test_missing_review_password_fails_before_writing(self) -> None:
        with override_settings(
            PILAH_REVIEW_SUPERADMIN_EMAILS=(SUPERADMIN_EMAIL, "pilah.superadmin@gmail.com"),
            PILAH_REVIEW_ACCOUNT_PASSWORD="",
        ):
            with self.assertRaisesRegex(CommandError, "PILAH_REVIEW_ACCOUNT_PASSWORD"):
                call_command("seed_play_demo_accounts", dry_run=True, stdout=StringIO())

        self.assertFalse(User.objects.exists())
        self.assertFalse(BankSampah.objects.exists())

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

        with override_settings(
            PILAH_REVIEW_SUPERADMIN_EMAILS=(SUPERADMIN_EMAIL, "pilah.superadmin@gmail.com")
        ):
            call_command("seed_play_demo_accounts", confirm_production=True, stdout=StringIO())
        self.assertEqual(
            {email for email, _name, _role in ACCOUNTS.values()}, set(REVIEW_ACCOUNT_EMAILS)
        )
        demo_account_emails = [account[0] for account in ACCOUNTS.values()]
        demo_users_before = list(
            User.objects.filter(email__in=demo_account_emails).order_by("email").values()
        )
        demo_bank = BankSampah.objects.get(nama="Bank Sampah PILAH Demo")
        demo_bank_before = BankSampah.objects.filter(pk=demo_bank.pk).values().get()
        demo_member_before = Nasabah.objects.filter(email=DEMO_NASABAH_EMAIL).values().get()
        demo_saldo_before = Saldo.objects.filter(nasabah__email=DEMO_NASABAH_EMAIL).values().get()
        review_bank = BankSampah.objects.get(pk=REVIEW_BANK_ID)
        review_bank.status = BankSampah.Status.ACTIVE
        review_bank.is_active = True
        review_bank.save(update_fields=["status", "is_active", "updated_at"])
        call_command("seed_play_demo_accounts", confirm_production=True, stdout=StringIO())

        bank = BankSampah.objects.get(nama="Bank Sampah PILAH Demo")
        owner = User.objects.get(email=DEMO_PENGELOLA_EMAIL)
        pengurus = User.objects.get(email="pilah.pengurus@pilah.com")
        nasabah_user = User.objects.get(email="pilah.nasabah@pilah.com")
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
        self.assertFalse(superadmin.is_staff)
        self.assertFalse(superadmin.is_superuser)
        for user in (owner, pengurus, nasabah_user, superadmin):
            self.assertTrue(user.has_usable_password())
            self.assertTrue(user.check_password(TEST_REVIEW_ACCOUNT_PASSWORD))
            self.assertIsNone(user.google_id)

        membership = Nasabah.objects.get(bank_sampah=bank, user=nasabah_user)
        self.assertTrue(membership.is_active)
        self.assertEqual(membership.status, Nasabah.Status.APPROVED)
        self.assertEqual(Saldo.objects.get(nasabah=membership).total_saldo, Decimal(21250))
        self.assertEqual(BankSampah.objects.count(), 3)
        self.assertEqual(User.objects.count(), 6)
        self.assertEqual(
            BankSampah.objects.filter(pk=other_bank.pk).values().get(), other_bank_before
        )
        self.assertEqual(User.objects.filter(pk=unrelated.pk).values().get(), unrelated_before)
        self.assertEqual(
            list(User.objects.filter(email__in=demo_account_emails).order_by("email").values()),
            demo_users_before,
        )
        self.assertEqual(BankSampah.objects.filter(pk=bank.pk).values().get(), demo_bank_before)
        self.assertEqual(
            Nasabah.objects.filter(pk=membership.pk).values().get(), demo_member_before
        )
        self.assertEqual(Saldo.objects.filter(nasabah=membership).values().get(), demo_saldo_before)
        self.assertEqual(BankSampah.objects.get(pk=REVIEW_BANK_ID).status, BankSampah.Status.ACTIVE)
        self.assertEqual(Transaksi.objects.filter(nasabah=membership).count(), 3)
        self.assertEqual(DetailTransaksi.objects.filter(transaksi__nasabah=membership).count(), 4)
        self.assertEqual(HargaSampah.objects.filter(jenis_sampah__bank_sampah=bank).count(), 4)
        self.assertEqual(JadwalKegiatan.objects.filter(bank_sampah=bank).count(), 2)

    def test_migrates_prior_seed_accounts_in_place_and_clears_google_bindings(self) -> None:
        bank = BankSampah.objects.create(
            id=DEMO_BANK_ID,
            nama="Bank Sampah PILAH Demo",
            alamat="Alamat data demo PILAH",
            kota="Depok",
            no_hp_pic="",
            jenis_organisasi=BankSampah.OrganizationType.MANDIRI,
            status=BankSampah.Status.ACTIVE,
            is_active=True,
        )
        legacy = {
            "owner": User.objects.create_user(
                email="traymachi@gmail.com",
                nama="Demo Pengelola PILAH",
                role=User.Role.PENGELOLA,
                bank_sampah=bank,
                is_profile_complete=True,
                is_primary_pengelola=True,
                google_id="legacy-owner-subject",
            ),
            "pengurus": User.objects.create_user(
                email="pilah.pengurus@gmail.com",
                nama="Demo Pengurus PILAH",
                role=User.Role.PENGELOLA,
                bank_sampah=bank,
                is_profile_complete=True,
                google_id="legacy-pengurus-subject",
            ),
            "nasabah": User.objects.create_user(
                email="pilah.nasabah@gmail.com",
                nama="Demo Nasabah PILAH",
                role=User.Role.NASABAH,
                is_profile_complete=True,
                alamat="Alamat demo untuk akun nasabah PILAH",
                google_id="legacy-nasabah-subject",
            ),
            "superadmin": User.objects.create_user(
                email="pilah.superadmin@gmail.com",
                nama="SuperAdmin PILAH",
                role=User.Role.SUPERADMIN,
                is_profile_complete=True,
                is_staff=True,
                is_superuser=True,
                google_id="legacy-superadmin-subject",
            ),
        }
        membership = Nasabah.objects.create(
            id="00000000-0000-4000-8000-000000000363",
            user=legacy["nasabah"],
            bank_sampah=bank,
            nomor=DEMO_NASABAH_NUMBER,
            nama="Demo Nasabah PILAH",
            alamat="Alamat demo untuk akun nasabah PILAH",
            no_hp="",
            email="pilah.nasabah@gmail.com",
            is_active=True,
            status=Nasabah.Status.APPROVED,
        )
        identities = {key: user.pk for key, user in legacy.items()}

        with override_settings(
            PILAH_REVIEW_SUPERADMIN_EMAILS=(SUPERADMIN_EMAIL, "pilah.superadmin@gmail.com")
        ):
            call_command("seed_play_demo_accounts", confirm_production=True, stdout=StringIO())

        for key, email in zip(
            ("owner", "pengurus", "nasabah", "superadmin"), REVIEW_ACCOUNT_EMAILS, strict=True
        ):
            user = User.objects.get(email=email)
            self.assertEqual(user.pk, identities[key])
            self.assertIsNone(user.google_id)
            self.assertTrue(user.check_password(TEST_REVIEW_ACCOUNT_PASSWORD))
            self.assertFalse(User.objects.filter(email=legacy[key].email).exists())
        membership.refresh_from_db()
        self.assertEqual(membership.pk, "00000000-0000-4000-8000-000000000363")
        self.assertEqual(membership.user_id, identities["nasabah"])
        self.assertEqual(membership.email, "pilah.nasabah@pilah.com")
        superadmin = User.objects.get(email=SUPERADMIN_EMAIL)
        self.assertFalse(superadmin.is_staff)
        self.assertFalse(superadmin.is_superuser)

    def test_legacy_and_target_email_collision_fails_before_writing(self) -> None:
        bank = BankSampah.objects.create(
            id=DEMO_BANK_ID,
            nama="Bank Sampah PILAH Demo",
            alamat="Alamat data demo PILAH",
            kota="Depok",
            no_hp_pic="",
            jenis_organisasi=BankSampah.OrganizationType.MANDIRI,
            status=BankSampah.Status.ACTIVE,
            is_active=True,
        )
        legacy_owner = User.objects.create_user(
            email="traymachi@gmail.com",
            nama="Demo Pengelola PILAH",
            role=User.Role.PENGELOLA,
            bank_sampah=bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        target_owner = User.objects.create_user(
            email="pilah.pengelola@pilah.com",
            nama="Other Pengelola",
            role=User.Role.PENGELOLA,
            bank_sampah=bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        users_before = list(User.objects.order_by("pk").values())

        with self.assertRaisesRegex(CommandError, "identity conflict"):
            with override_settings(
                PILAH_REVIEW_SUPERADMIN_EMAILS=(SUPERADMIN_EMAIL, "pilah.superadmin@gmail.com")
            ):
                call_command("seed_play_demo_accounts", confirm_production=True, stdout=StringIO())

        self.assertEqual(list(User.objects.order_by("pk").values()), users_before)
        self.assertEqual(legacy_owner.email, "traymachi@gmail.com")
        self.assertEqual(target_owner.email, "pilah.pengelola@pilah.com")
        self.assertEqual(BankSampah.objects.count(), 1)

    def test_reserved_waste_type_id_collision_preserves_unrelated_data(self) -> None:
        other_bank = BankSampah.objects.create(nama="Unrelated Bank", no_hp_pic="")
        other_type = JenisSampah.objects.create(
            id=WASTE_TYPE_IDS[0],
            bank_sampah=other_bank,
            nomor="OTHER-01",
            nama_sampah="Unrelated Type",
        )
        bank_before = BankSampah.objects.filter(pk=other_bank.pk).values().get()
        type_before = JenisSampah.objects.filter(pk=other_type.pk).values().get()

        with self.assertRaisesRegex(CommandError, "waste type identity"):
            call_command("seed_play_demo_accounts", dry_run=True, stdout=StringIO())

        self.assertEqual(BankSampah.objects.filter(pk=other_bank.pk).values().get(), bank_before)
        self.assertEqual(JenisSampah.objects.filter(pk=other_type.pk).values().get(), type_before)
        self.assertEqual(BankSampah.objects.count(), 1)
        self.assertFalse(User.objects.exists())
        self.assertFalse(Nasabah.objects.exists())

    def test_reserved_review_bank_id_collision_fails_before_writing_accounts(self) -> None:
        other_bank = BankSampah.objects.create(
            id=REVIEW_BANK_ID,
            nama="Unrelated Bank",
            no_hp_pic="",
        )
        before = BankSampah.objects.filter(pk=other_bank.pk).values().get()

        with self.assertRaisesRegex(CommandError, "review bank identity"):
            call_command("seed_play_demo_accounts", dry_run=True, stdout=StringIO())

        self.assertEqual(BankSampah.objects.filter(pk=other_bank.pk).values().get(), before)
        self.assertEqual(BankSampah.objects.count(), 1)
        self.assertFalse(User.objects.exists())

    def test_existing_target_with_conflicting_role_fails_without_partial_writes(self) -> None:
        User.objects.create_user(
            email=DEMO_PENGELOLA_EMAIL,
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
        self.assertEqual(Saldo.objects.get(nasabah=membership).total_saldo, Decimal(21250))

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
        self.assertFalse(JenisSampah.objects.exists())
        self.assertFalse(Transaksi.objects.exists())
        self.assertFalse(JadwalKegiatan.objects.exists())

    def test_existing_review_superadmin_loses_django_admin_access(self) -> None:
        superadmin = User.objects.create_user(
            email=SUPERADMIN_EMAIL,
            nama="SuperAdmin PILAH",
            role=User.Role.SUPERADMIN,
            is_profile_complete=True,
            is_staff=True,
            is_superuser=True,
        )

        call_command("seed_play_demo_accounts", confirm_production=True, stdout=StringIO())

        superadmin.refresh_from_db()
        self.assertFalse(superadmin.is_staff)
        self.assertFalse(superadmin.is_superuser)

    def test_superadmin_must_be_in_review_allowlist(self) -> None:
        with override_settings(PILAH_REVIEW_SUPERADMIN_EMAILS=()):
            with self.assertRaisesRegex(CommandError, "PILAH_REVIEW_SUPERADMIN_EMAILS"):
                call_command("seed_play_demo_accounts", dry_run=True, stdout=StringIO())

        self.assertFalse(User.objects.exists())
        self.assertFalse(BankSampah.objects.exists())

    def test_review_superadmin_must_not_also_be_in_global_allowlist(self) -> None:
        with override_settings(PILAH_SUPERADMIN_EMAILS=(SUPERADMIN_EMAIL,)):
            with self.assertRaisesRegex(CommandError, "must not be in PILAH_SUPERADMIN_EMAILS"):
                call_command("seed_play_demo_accounts", dry_run=True, stdout=StringIO())

        self.assertFalse(User.objects.exists())
        self.assertFalse(BankSampah.objects.exists())

    def test_seeds_exact_synthetic_catalog_history_schedules_and_review_bank(self) -> None:
        call_command("seed_play_demo_accounts", confirm_production=True, stdout=StringIO())

        bank = BankSampah.objects.get(nama="Bank Sampah PILAH Demo")
        member = Nasabah.objects.get(email=DEMO_NASABAH_EMAIL)
        types = list(
            JenisSampah.objects.filter(bank_sampah=bank)
            .order_by("nomor")
            .values_list("nama_sampah", "kategori", "is_active")
        )
        self.assertEqual(
            types,
            [
                ("Plastik PET", JenisSampah.Kategori.PLASTIK, True),
                ("Kardus", JenisSampah.Kategori.KERTAS, True),
                ("Botol Kaca", JenisSampah.Kategori.KACA, True),
                ("Kaleng Aluminium", JenisSampah.Kategori.LOGAM, True),
            ],
        )
        prices = list(
            HargaSampah.objects.filter(jenis_sampah__bank_sampah=bank)
            .order_by("jenis_sampah__nomor")
            .values_list("jenis_sampah__nama_sampah", "harga_per_kg")
        )
        self.assertEqual(
            prices,
            [
                ("Plastik PET", Decimal("3500.00")),
                ("Kardus", Decimal("2000.00")),
                ("Botol Kaca", Decimal("1000.00")),
                ("Kaleng Aluminium", Decimal("5000.00")),
            ],
        )

        transactions = list(
            Transaksi.objects.filter(nasabah=member).order_by("tanggal").prefetch_related("items")
        )
        self.assertEqual(
            [row.total_nilai for row in transactions],
            [Decimal(value) for value in ("10750", "3000", "7500")],
        )
        snapshots = [
            [
                (
                    item.nama_sampah_snapshot,
                    item.kategori_snapshot,
                    item.harga_snapshot,
                    item.berat,
                    item.subtotal,
                )
                for item in transaction.items.all()
            ]
            for transaction in transactions
        ]
        self.assertEqual(
            snapshots,
            [
                [
                    ("Plastik PET", "plastik", Decimal("3500.00"), Decimal("2.500"), Decimal(8750)),
                    ("Kardus", "kertas", Decimal("2000.00"), Decimal("1.000"), Decimal(2000)),
                ],
                [("Botol Kaca", "kaca", Decimal("1000.00"), Decimal("3.000"), Decimal(3000))],
                [
                    (
                        "Kaleng Aluminium",
                        "logam",
                        Decimal("5000.00"),
                        Decimal("1.500"),
                        Decimal(7500),
                    )
                ],
            ],
        )
        self.assertEqual(Saldo.objects.get(nasabah=member).total_saldo, Decimal(21250))
        self.assertEqual(Nasabah.objects.filter(bank_sampah=bank).count(), 1)
        self.assertFalse(Pencairan.objects.filter(nasabah=member).exists())

        schedules = list(JadwalKegiatan.objects.filter(bank_sampah=bank).order_by("mulai_pada"))
        self.assertEqual(len(schedules), 2)
        today = timezone.localdate()
        for schedule, activity, days in zip(
            schedules,
            (
                JadwalKegiatan.JenisKegiatan.PENIMBANGAN,
                JadwalKegiatan.JenisKegiatan.PENCAIRAN,
            ),
            (7, 14),
            strict=True,
        ):
            start = timezone.localtime(schedule.mulai_pada)
            end = timezone.localtime(schedule.selesai_pada)
            self.assertEqual(schedule.jenis_kegiatan, activity)
            self.assertEqual(schedule.status, JadwalKegiatan.Status.DITERBITKAN)
            self.assertEqual(
                schedule.cakupan_penerima, JadwalKegiatan.CakupanPenerima.SEMUA_NASABAH
            )
            self.assertEqual(start.date(), today + timedelta(days=days))
            self.assertEqual(start.time().replace(tzinfo=None), time(9, 0))
            self.assertEqual(end.time().replace(tzinfo=None), time(11, 0))

        client = APIClient()
        client.force_authenticate(user=member.user)
        visible_schedules = client.get("/api/v1/jadwal")
        self.assertEqual(visible_schedules.status_code, 200, visible_schedules.data)
        self.assertEqual(visible_schedules.data["count"], 2)

        review_bank = BankSampah.objects.get(pk="00000000-0000-4000-8000-000000000364")
        review_owner = User.objects.get(email="pilah.review-owner@example.test")
        self.assertEqual(review_bank.status, BankSampah.Status.PENDING)
        self.assertFalse(review_bank.is_active)
        self.assertEqual(str(review_owner.pk), "00000000-0000-4000-8000-000000000365")
        self.assertEqual(review_owner.bank_sampah, review_bank)
        self.assertTrue(review_owner.is_primary_pengelola)
        self.assertIsNone(review_owner.google_id)
        self.assertFalse(review_owner.has_usable_password())

    def test_existing_matching_google_identity_is_preserved(self) -> None:
        user = User.objects.create_user(
            email=DEMO_PENGELOLA_EMAIL,
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

    def test_rejects_ambiguous_case_insensitive_demo_users(self) -> None:
        User.objects.create_user(
            email=DEMO_PENGELOLA_EMAIL,
            nama="Pengelola 1",
            role=User.Role.PENGELOLA,
        )
        User.objects.create_user(
            email=DEMO_PENGELOLA_EMAIL.upper(),
            nama="Pengelola 2",
            role=User.Role.PENGELOLA,
        )

        with self.assertRaisesRegex(CommandError, "multiple users"):
            Command._existing_user(DEMO_PENGELOLA_EMAIL, User.Role.PENGELOLA)

    def test_existing_demo_role_accounts_cannot_belong_to_another_bank(self) -> None:
        other_bank = BankSampah.objects.create(nama="Unrelated bank", no_hp_pic="")
        cases = (
            ("review-superadmin@example.com", User.Role.SUPERADMIN, "bank assignment"),
            ("review-nasabah@example.com", User.Role.NASABAH, "bank assignment"),
            ("other-pengelola@example.com", User.Role.PENGELOLA, "another bank"),
        )
        for email, role, message in cases:
            with self.subTest(role=role):
                User.objects.create_user(
                    email=email,
                    nama="Existing account",
                    role=role,
                    bank_sampah=other_bank,
                )
                with self.assertRaisesRegex(CommandError, message):
                    Command._existing_user(email, role)

    def test_review_owner_identity_conflicts_are_rejected(self) -> None:
        User.objects.create_user(
            id=REVIEW_OWNER_ID,
            email="identity-match@example.test",
            nama="Conflicting owner",
            role=User.Role.PENGELOLA,
        )
        User.objects.create_user(
            email=REVIEW_OWNER_EMAIL,
            nama="Conflicting owner",
            role=User.Role.PENGELOLA,
        )

        with self.assertRaisesRegex(CommandError, "review owner identity"):
            Command._existing_review_owner()

    def test_review_owner_with_reserved_email_and_wrong_role_is_rejected(self) -> None:
        User.objects.create_user(
            id=REVIEW_OWNER_ID,
            email=REVIEW_OWNER_EMAIL,
            nama="Conflicting owner",
            role=User.Role.NASABAH,
        )

        with self.assertRaisesRegex(CommandError, "review owner identity"):
            Command._existing_review_owner()

    def test_reserved_waste_number_collision_is_rejected(self) -> None:
        bank = BankSampah.objects.create(id=DEMO_BANK_ID, nama="Demo", no_hp_pic="")
        JenisSampah.objects.create(
            bank_sampah=bank,
            nomor=WASTE_TYPE_FIXTURES[0][0],
            nama_sampah="Unrelated type",
        )

        with self.assertRaisesRegex(CommandError, "waste type number"):
            Command._validate_waste_type_rows()

    def test_reserved_transaction_identity_collision_is_rejected(self) -> None:
        bank = BankSampah.objects.create(nama="Unrelated bank", no_hp_pic="")
        pengurus = User.objects.create_user(email="other-pengelola@example.test", nama="Pengurus")
        member = Nasabah.objects.create(
            bank_sampah=bank,
            nomor="OTHER-0001",
            nama="Other member",
            alamat="Depok",
            no_hp="",
            email="other-member@example.test",
        )
        Transaksi.objects.create(
            id=TRANSACTION_IDS[0],
            bank_sampah=bank,
            nasabah=member,
            dicatat_oleh=pengurus,
        )

        with self.assertRaisesRegex(CommandError, "transaction identity"):
            Command._validate_transaction_rows()

    def test_reserved_transaction_detail_identity_collision_is_rejected(self) -> None:
        bank = BankSampah.objects.create(nama="Unrelated bank", no_hp_pic="")
        pengurus = User.objects.create_user(email="other-pengelola@example.test", nama="Pengurus")
        member = Nasabah.objects.create(
            bank_sampah=bank,
            nomor="OTHER-0001",
            nama="Other member",
            alamat="Depok",
            no_hp="",
            email="other-member@example.test",
        )
        jenis = JenisSampah.objects.create(
            bank_sampah=bank,
            nomor="OTHER-01",
            nama_sampah="Other type",
        )
        transaksi = Transaksi.objects.create(
            bank_sampah=bank,
            nasabah=member,
            dicatat_oleh=pengurus,
        )
        DetailTransaksi.objects.create(
            id=DETAIL_IDS[0],
            transaksi=transaksi,
            jenis_sampah=jenis,
            nama_sampah_snapshot=jenis.nama_sampah,
            kategori_snapshot=jenis.kategori,
            harga_snapshot=Decimal(1),
            berat=Decimal(1),
            subtotal=Decimal(1),
        )

        with self.assertRaisesRegex(CommandError, "transaction detail identity"):
            Command._validate_transaction_rows()

    def test_reserved_schedule_identity_collision_is_rejected(self) -> None:
        bank = BankSampah.objects.create(nama="Unrelated bank", no_hp_pic="")
        pengurus = User.objects.create_user(email="other-pengelola@example.test", nama="Pengurus")
        starts_at = timezone.now() + timedelta(days=1)
        JadwalKegiatan.objects.create(
            id=SCHEDULE_IDS[0],
            bank_sampah=bank,
            dibuat_oleh=pengurus,
            jenis_kegiatan=JadwalKegiatan.JenisKegiatan.PENIMBANGAN,
            mulai_pada=starts_at,
            selesai_pada=starts_at + timedelta(hours=1),
            lokasi="Balai Warga",
        )

        with self.assertRaisesRegex(CommandError, "schedule identity"):
            Command._validate_schedule_rows()

    def test_existing_membership_conflicts_are_rejected(self) -> None:
        expected_user = User(id=uuid4(), email=DEMO_NASABAH_EMAIL, nama="Demo Nasabah")
        other_user_id = uuid4()
        cases = (
            ({"user_id": other_user_id}, expected_user, "another account"),
            ({"user_id": other_user_id}, None, "another account"),
            ({"user_id": expected_user.pk, "email": "wrong@example.test"}, expected_user, "email"),
            ({"nomor": "WRONG-0001"}, None, "member number"),
            ({"is_active": False}, None, "inactive or unapproved"),
        )
        for fields, user, message in cases:
            with self.subTest(message=message):
                membership_values = {
                    "bank_sampah_id": DEMO_BANK_ID,
                    "user_id": None,
                    "nomor": DEMO_NASABAH_NUMBER,
                    "email": DEMO_NASABAH_EMAIL,
                    "is_active": True,
                    "status": Nasabah.Status.APPROVED,
                    **fields,
                }
                membership = Nasabah(**membership_values)
                with self.assertRaisesRegex(CommandError, message):
                    Command._validate_membership_identity(membership, user)

    def test_membership_email_matching_multiple_rows_is_rejected(self) -> None:
        for suffix in ("one", "two"):
            bank = BankSampah.objects.create(nama=f"Bank {suffix}", no_hp_pic="")
            Nasabah.objects.create(
                bank_sampah=bank,
                nomor=f"{suffix}-0001",
                nama="Duplicate email member",
                alamat="Depok",
                no_hp="",
                email=DEMO_NASABAH_EMAIL,
            )

        with self.assertRaisesRegex(CommandError, "multiple memberships"):
            Command._existing_membership(None)

    def test_nasabah_user_linked_to_another_bank_is_rejected(self) -> None:
        bank = BankSampah.objects.create(nama="Unrelated bank", no_hp_pic="")
        user = User.objects.create_user(
            email=DEMO_NASABAH_EMAIL,
            nama="Demo Nasabah",
            role=User.Role.NASABAH,
        )
        Nasabah.objects.create(
            user=user,
            bank_sampah=bank,
            nomor="OTHER-0001",
            nama="Other member",
            alamat="Depok",
            no_hp="",
            email="other-member@example.test",
        )

        with self.assertRaisesRegex(CommandError, "already belongs to another bank"):
            Command._validate_membership_ownership(None, user)

    def test_duplicate_demo_member_number_is_rejected(self) -> None:
        bank = BankSampah.objects.create(id=DEMO_BANK_ID, nama="Demo", no_hp_pic="")
        Nasabah.objects.create(
            bank_sampah=bank,
            nomor=DEMO_NASABAH_NUMBER,
            nama="Unrelated member",
            alamat="Depok",
            no_hp="",
            email="other-member@example.test",
        )

        with self.assertRaisesRegex(CommandError, "number is already used"):
            Command._validate_membership_number(None)

    def test_existing_nasabah_profile_fields_are_completed(self) -> None:
        bank = BankSampah.objects.create(nama="Unrelated bank", no_hp_pic="")
        user = User.objects.create_user(
            email=DEMO_NASABAH_EMAIL,
            nama="",
            role=User.Role.NASABAH,
            alamat="",
        )

        Command._ensure_user(
            user,
            email=DEMO_NASABAH_EMAIL,
            display_name="Demo Nasabah PILAH",
            role=User.Role.NASABAH,
            bank=bank,
            primary=False,
        )

        user.refresh_from_db()
        self.assertEqual(user.nama, "Demo Nasabah PILAH")
        self.assertEqual(user.alamat, "Alamat demo untuk akun nasabah PILAH")
        self.assertTrue(user.is_profile_complete)

    def test_failed_seed_price_aborts_with_clear_error(self) -> None:
        jenis = JenisSampah(id=WASTE_TYPE_IDS[0])
        with (
            patch(
                "api.management.commands.seed_play_demo_accounts.harga_berlaku", return_value=None
            ),
            self.assertRaisesRegex(CommandError, "has no active price"),
        ):
            _seed_price(jenis, timezone.now())

    def test_missing_created_nasabah_account_rolls_back_seed(self) -> None:
        with (
            patch.object(Command, "_ensure_user", return_value=None),
            self.assertRaisesRegex(CommandError, "accounts could not be created"),
        ):
            call_command("seed_play_demo_accounts", confirm_production=True, stdout=StringIO())

        self.assertFalse(BankSampah.objects.exists())
        self.assertFalse(User.objects.exists())
