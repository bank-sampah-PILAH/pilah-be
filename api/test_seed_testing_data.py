from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from api.models import (
    BankSampah,
    BankSampahApprovalLog,
    DetailTransaksi,
    JenisSampah,
    Nasabah,
    Saldo,
    Transaksi,
    User,
)


class SeedTestingDataCommandTests(TestCase):
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
        self.assertTrue(User.objects.filter(email="operator.demo@example.com").exists())
        self.assertTrue(User.objects.filter(email="superadmin.demo@example.com").exists())
        self.assertEqual(Nasabah.objects.count(), 2)
        self.assertEqual(JenisSampah.objects.count(), 4)
        self.assertEqual(Transaksi.objects.count(), 3)
        self.assertEqual(DetailTransaksi.objects.count(), 4)
        self.assertEqual(Saldo.objects.count(), 2)
        self.assertEqual(BankSampahApprovalLog.objects.count(), 1)

        counts = {
            "banks": BankSampah.objects.count(),
            "users": User.objects.count(),
            "nasabah": Nasabah.objects.count(),
            "jenis": JenisSampah.objects.count(),
            "transaksi": Transaksi.objects.count(),
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
            operator_email="staging.operator@example.com",
            customer_email="staging.customer@example.com",
            superadmin_email="staging.admin@example.com",
            pending_operator_email="staging.pending@example.com",
        )

        unrelated_bank.refresh_from_db()
        self.assertEqual(unrelated_bank.nama, "Bank Sampah Manual")
        self.assertTrue(User.objects.filter(email="staging.operator@example.com").exists())
        self.assertTrue(User.objects.filter(email="staging.customer@example.com").exists())
        self.assertTrue(User.objects.filter(email="staging.admin@example.com").exists())
        self.assertTrue(User.objects.filter(email="staging.pending@example.com").exists())

    @override_settings(DEBUG=False)
    def test_local_environment_requires_debug(self) -> None:
        with self.assertRaisesMessage(
            CommandError, "Local testing data requires DJANGO_DEBUG=true"
        ):
            call_command("seed_testing_data")

    @override_settings(DEBUG=True)
    def test_seed_reuses_existing_account_for_configured_email(self) -> None:
        User.objects.create_user(
            email="operator.demo@example.com",
            nama="Existing Operator",
            role=User.Role.PENGELOLA,
        )

        call_command("seed_testing_data")
        call_command("seed_testing_data")

        users = User.objects.filter(email="operator.demo@example.com")
        self.assertEqual(users.count(), 1)
        self.assertEqual(users.get().nama, "Operator PILAH E2E")

    @override_settings(DEBUG=True)
    def test_reseed_preserves_transaction_dates(self) -> None:
        call_command("seed_testing_data")

        dates = {item.pk: item.tanggal for item in Transaksi.objects.all()}
        self.assertEqual(len(dates), 3)

        call_command("seed_testing_data")

        for pk, tanggal in dates.items():
            self.assertEqual(Transaksi.objects.get(pk=pk).tanggal, tanggal)

    @override_settings(DEBUG=False)
    def test_staging_requires_explicit_confirmation(self) -> None:
        with self.assertRaisesMessage(CommandError, "SEED-PILAH-STAGING-DATA"):
            call_command("seed_testing_data", environment="staging")

        call_command(
            "seed_testing_data",
            environment="staging",
            confirm="SEED-PILAH-STAGING-DATA",
        )
