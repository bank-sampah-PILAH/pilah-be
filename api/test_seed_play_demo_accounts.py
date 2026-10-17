from datetime import time, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.management.commands.seed_play_demo_accounts import (
    DEMO_NASABAH_EMAIL,
    WASTE_TYPE_IDS,
)
from api.models import (
    BankSampah,
    DetailTransaksi,
    JadwalKegiatan,
    JenisSampah,
    Nasabah,
    Pencairan,
    Saldo,
    Transaksi,
    User,
)
from apps.bank_sampah.constants import REVIEW_BANK_ID

SUPERADMIN_EMAIL = "pilah.superadmin@gmail.com"
PRODUCTION_SETTINGS = {
    "DEBUG": False,
    "PILAH_ENVIRONMENT": "production",
    "PILAH_SUPERADMIN_EMAILS": (),
    "PILAH_REVIEW_SUPERADMIN_EMAILS": (SUPERADMIN_EMAIL,),
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
        review_bank = BankSampah.objects.get(pk=REVIEW_BANK_ID)
        review_bank.status = BankSampah.Status.ACTIVE
        review_bank.is_active = True
        review_bank.save(update_fields=["status", "is_active", "updated_at"])
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
        self.assertFalse(superadmin.is_staff)
        self.assertFalse(superadmin.is_superuser)
        for user in (owner, pengurus, nasabah_user, superadmin):
            self.assertFalse(user.has_usable_password())
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
            list(User.objects.filter(email__startswith="pilah.").order_by("email").values()),
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
        self.assertEqual(JadwalKegiatan.objects.filter(bank_sampah=bank).count(), 2)

    def test_reserved_waste_type_id_collision_preserves_unrelated_data(self) -> None:
        other_bank = BankSampah.objects.create(nama="Unrelated Bank", no_hp_pic="")
        other_type = JenisSampah.objects.create(
            id=WASTE_TYPE_IDS[0],
            bank_sampah=other_bank,
            nomor="OTHER-01",
            nama_sampah="Unrelated Type",
            harga_per_kg=Decimal(123),
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
            .values_list("nama_sampah", "kategori", "harga_per_kg", "is_active")
        )
        self.assertEqual(
            types,
            [
                ("Plastik PET", JenisSampah.Kategori.PLASTIK, Decimal("3500.00"), True),
                ("Kardus", JenisSampah.Kategori.KERTAS, Decimal("2000.00"), True),
                ("Botol Kaca", JenisSampah.Kategori.KACA, Decimal("1000.00"), True),
                ("Kaleng Aluminium", JenisSampah.Kategori.LOGAM, Decimal("5000.00"), True),
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
