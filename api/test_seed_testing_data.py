import os
from argparse import ArgumentParser, Namespace
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from api.management.commands.seed_testing_data import Command
from api.models import (
    BankSampah,
    BankSampahApprovalLog,
    DetailTransaksi,
    JenisSampah,
    Nasabah,
    Pencairan,
    Saldo,
    Transaksi,
    User,
)


class SeedTestingDataCommandTests(TestCase):
    @staticmethod
    def _parse_seed_arguments(*arguments: str) -> Namespace:
        parser = ArgumentParser()
        Command().add_arguments(parser)
        return parser.parse_args(arguments)

    def test_pengurus_email_defaults_and_legacy_aliases(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            defaults = self._parse_seed_arguments()
        self.assertEqual(defaults.pengurus_email, "pengurus.demo@example.com")
        self.assertEqual(defaults.pending_pengurus_email, "pending.pengurus.demo@example.com")
        self.assertEqual(defaults.induk_email, "induk.demo@example.com")

        with patch.dict(
            os.environ,
            {"PILAH_SEED_INDUK_EMAIL": "configured.induk@example.com"},
            clear=True,
        ):
            configured_induk = self._parse_seed_arguments()
        self.assertEqual(configured_induk.induk_email, "configured.induk@example.com")

        with patch.dict(
            os.environ,
            {
                "PILAH_SEED_OPERATOR_EMAIL": "legacy.pengurus@example.com",
                "PILAH_SEED_PENDING_OPERATOR_EMAIL": "legacy.pending@example.com",
            },
            clear=True,
        ):
            legacy_defaults = self._parse_seed_arguments()
        self.assertEqual(legacy_defaults.pengurus_email, "legacy.pengurus@example.com")
        self.assertEqual(legacy_defaults.pending_pengurus_email, "legacy.pending@example.com")

        with patch.dict(
            os.environ,
            {
                "PILAH_SEED_PENGURUS_EMAIL": "pengurus@example.com",
                "PILAH_SEED_OPERATOR_EMAIL": "legacy.pengurus@example.com",
                "PILAH_SEED_PENDING_PENGURUS_EMAIL": "pending@example.com",
                "PILAH_SEED_PENDING_OPERATOR_EMAIL": "legacy.pending@example.com",
            },
            clear=True,
        ):
            preferred_defaults = self._parse_seed_arguments()
        self.assertEqual(preferred_defaults.pengurus_email, "pengurus@example.com")
        self.assertEqual(preferred_defaults.pending_pengurus_email, "pending@example.com")

        legacy_flags = self._parse_seed_arguments(
            "--operator-email",
            "flag.pengurus@example.com",
            "--pending-operator-email",
            "flag.pending@example.com",
        )
        self.assertEqual(legacy_flags.pengurus_email, "flag.pengurus@example.com")
        self.assertEqual(legacy_flags.pending_pengurus_email, "flag.pending@example.com")

        new_flags = self._parse_seed_arguments(
            "--pengurus-email",
            "new.pengurus@example.com",
            "--pending-pengurus-email",
            "new.pending@example.com",
        )
        self.assertEqual(new_flags.pengurus_email, "new.pengurus@example.com")
        self.assertEqual(new_flags.pending_pengurus_email, "new.pending@example.com")

    @override_settings(DEBUG=True)
    def test_seed_creates_full_fixture_and_can_be_rerun(self) -> None:
        first_output = StringIO()

        call_command("seed_testing_data", stdout=first_output)

        self.assertIn("Seeded testing data for local environment", first_output.getvalue())
        self.assertTrue(
            BankSampah.objects.filter(
                nama="Bank Sampah PILAH E2E", status=BankSampah.Status.ACTIVE
            ).exists()
        )
        self.assertTrue(
            BankSampah.objects.filter(
                nama="Bank Sampah PILAH E2E Pending", status=BankSampah.Status.PENDING
            ).exists()
        )
        self.assertTrue(
            BankSampah.objects.filter(
                nama="Bank Sampah Induk PILAH E2E",
                jenis_organisasi=BankSampah.OrganizationType.INDUK,
                status=BankSampah.Status.ACTIVE,
            ).exists()
        )
        self.assertTrue(User.objects.filter(email="pengurus.demo@example.com").exists())
        self.assertTrue(
            User.objects.filter(
                email="induk.demo@example.com", role=User.Role.PENGELOLA_INDUK
            ).exists()
        )
        self.assertTrue(User.objects.filter(email="superadmin.demo@example.com").exists())
        self.assertEqual(Nasabah.objects.count(), 62)
        self.assertEqual(
            Nasabah.objects.filter(
                nomor__startswith="NAS-DEMO-",
                status=Nasabah.Status.APPROVED,
                is_active=True,
            ).count(),
            20,
        )
        self.assertEqual(
            Nasabah.objects.filter(
                nomor__startswith="NAS-DEMO-",
                status=Nasabah.Status.APPROVED,
                is_active=False,
            ).count(),
            20,
        )
        self.assertEqual(
            Nasabah.objects.filter(
                nomor__startswith="NAS-DEMO-", status=Nasabah.Status.PENDING
            ).count(),
            20,
        )
        self.assertEqual(JenisSampah.objects.count(), 4)
        self.assertEqual(Transaksi.objects.count(), 223)
        self.assertEqual(Pencairan.objects.count(), 220)
        self.assertEqual(DetailTransaksi.objects.count(), 224)
        self.assertEqual(Saldo.objects.count(), 2)
        self.assertEqual(BankSampahApprovalLog.objects.count(), 1)

        for customer in Nasabah.objects.filter(user__isnull=False):
            self.assertGreaterEqual(Transaksi.objects.filter(nasabah=customer).count(), 100)
            payouts = Pencairan.objects.filter(nasabah=customer)
            self.assertGreaterEqual(payouts.count(), 100)
            setoran_total = sum(
                Transaksi.objects.filter(nasabah=customer).values_list("total_nilai", flat=True),
                Decimal("0.00"),
            )
            payout_total = sum(
                (payout.saldo_sebelum - payout.saldo_sesudah for payout in payouts),
                Decimal("0.00"),
            )
            self.assertEqual(
                Saldo.objects.get(nasabah=customer).total_saldo,
                setoran_total - payout_total,
            )
        now = timezone.now()
        oldest_setoran = Transaksi.objects.earliest("tanggal").tanggal
        oldest_pencairan = Pencairan.objects.earliest("tanggal").tanggal
        for oldest in (oldest_setoran, oldest_pencairan):
            self.assertGreater(oldest, now - timedelta(days=366))
            self.assertLessEqual(oldest, now - timedelta(days=365))

        counts = {
            "banks": BankSampah.objects.count(),
            "users": User.objects.count(),
            "nasabah": Nasabah.objects.count(),
            "jenis": JenisSampah.objects.count(),
            "transaksi": Transaksi.objects.count(),
            "pencairan": Pencairan.objects.count(),
            "details": DetailTransaksi.objects.count(),
            "saldo": Saldo.objects.count(),
            "approval_logs": BankSampahApprovalLog.objects.count(),
        }

        second_output = StringIO()
        call_command("seed_testing_data", stdout=second_output)

        self.assertIn("Seeded testing data for local environment", second_output.getvalue())
        self.assertEqual(
            counts,
            {
                "banks": BankSampah.objects.count(),
                "users": User.objects.count(),
                "nasabah": Nasabah.objects.count(),
                "jenis": JenisSampah.objects.count(),
                "transaksi": Transaksi.objects.count(),
                "pencairan": Pencairan.objects.count(),
                "details": DetailTransaksi.objects.count(),
                "saldo": Saldo.objects.count(),
                "approval_logs": BankSampahApprovalLog.objects.count(),
            },
        )

    @override_settings(DEBUG=True)
    def test_seed_preserves_unrelated_data_and_accepts_configured_emails(self) -> None:
        unrelated_bank = BankSampah.objects.create(
            nama="Bank Sampah Manual",
            alamat="Jl. Manual No. 1",
            kota="Depok",
            no_hp_pic="+628111111111",
        )

        call_command(
            "seed_testing_data",
            pengurus_email="staging.pengurus@example.com",
            customer_email="staging.customer@example.com",
            customer_two_email="staging.customer.two@example.com",
            superadmin_email="staging.admin@example.com",
            pending_pengurus_email="staging.pending@example.com",
            induk_email="staging.induk@example.com",
        )

        unrelated_bank.refresh_from_db()
        self.assertEqual(unrelated_bank.nama, "Bank Sampah Manual")
        self.assertTrue(User.objects.filter(email="staging.pengurus@example.com").exists())
        self.assertTrue(User.objects.filter(email="staging.customer@example.com").exists())
        self.assertTrue(User.objects.filter(email="staging.customer.two@example.com").exists())
        self.assertTrue(User.objects.filter(email="staging.admin@example.com").exists())
        self.assertTrue(User.objects.filter(email="staging.pending@example.com").exists())
        self.assertTrue(User.objects.filter(email="staging.induk@example.com").exists())

    @override_settings(DEBUG=False)
    def test_local_environment_requires_debug(self) -> None:
        with self.assertRaisesRegex(CommandError, "Local testing data requires DJANGO_DEBUG=true"):
            call_command("seed_testing_data")

    @override_settings(DEBUG=True)
    def test_seed_rejects_non_fixture_email_collision(self) -> None:
        user = User.objects.create_user(
            email="pengurus.demo@example.com",
            nama="Existing Pengurus",
            role=User.Role.PENGELOLA,
            is_profile_complete=True,
        )

        with self.assertRaisesRegex(CommandError, "non-fixture account"):
            call_command("seed_testing_data")

        user.refresh_from_db()
        self.assertEqual(user.nama, "Existing Pengurus")

    @override_settings(DEBUG=True)
    def test_seed_reuses_existing_account_for_configured_email(self) -> None:
        User.objects.create_user(
            email="pengurus.demo@example.com",
            nama="Existing Pengurus",
            role=User.Role.PENGELOLA,
        )

        call_command("seed_testing_data")
        call_command("seed_testing_data")

        users = User.objects.filter(email="pengurus.demo@example.com")
        self.assertEqual(users.count(), 1)
        self.assertEqual(users.get().nama, "Pengurus PILAH E2E")

    @override_settings(DEBUG=True)
    def test_reseed_preserves_history_dates_and_does_not_duplicate_rows(self) -> None:
        call_command("seed_testing_data")

        setoran_dates = {item.pk: item.tanggal for item in Transaksi.objects.all()}
        pencairan_dates = {item.pk: item.tanggal for item in Pencairan.objects.all()}
        self.assertEqual(len(setoran_dates), 223)
        self.assertEqual(len(pencairan_dates), 220)

        call_command("seed_testing_data")

        for pk, tanggal in setoran_dates.items():
            self.assertEqual(Transaksi.objects.get(pk=pk).tanggal, tanggal)
        for pk, tanggal in pencairan_dates.items():
            self.assertEqual(Pencairan.objects.get(pk=pk).tanggal, tanggal)
        self.assertEqual(Nasabah.objects.filter(nomor__startswith="NAS-DEMO-").count(), 60)

    @override_settings(DEBUG=False)
    def test_staging_requires_explicit_confirmation(self) -> None:
        with self.assertRaisesRegex(CommandError, "SEED-PILAH-STAGING-DATA"):
            call_command("seed_testing_data", environment="staging")

        call_command(
            "seed_testing_data",
            environment="staging",
            confirm="SEED-PILAH-STAGING-DATA",
        )
