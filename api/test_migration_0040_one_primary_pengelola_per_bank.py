from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from api.models import BankSampah, User

BEFORE = [("api", "0039_user_role_change_log")]
AFTER = [("api", "0040_one_primary_pengelola_per_bank")]


def _migrate(target: list[tuple[str, str]]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(target)
    return MigrationExecutor(connection)


class OnePrimaryPerBankConstraintTests(TestCase):
    def _bank(self, nama: str) -> BankSampah:
        return BankSampah.objects.create(
            nama=nama, alamat="Depok", kota="Depok", no_hp_pic="+628111111111"
        )

    def _pengelola(self, email: str, bank: BankSampah, *, primary: bool) -> User:
        return User.objects.create(
            email=email,
            nama=email,
            role=User.Role.PENGELOLA,
            bank_sampah=bank,
            is_primary_pengelola=primary,
        )

    def test_second_primary_in_same_bank_is_rejected(self) -> None:
        bank = self._bank("Bank A")
        self._pengelola("a@example.com", bank, primary=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._pengelola("b@example.com", bank, primary=True)

    def test_many_non_primary_members_are_allowed(self) -> None:
        bank = self._bank("Bank A")
        self._pengelola("a@example.com", bank, primary=True)
        self._pengelola("b@example.com", bank, primary=False)
        self._pengelola("c@example.com", bank, primary=False)
        self.assertEqual(User.objects.filter(bank_sampah=bank).count(), 3)

    def test_each_bank_has_its_own_primary(self) -> None:
        self._pengelola("a@example.com", self._bank("Bank A"), primary=True)
        self._pengelola("b@example.com", self._bank("Bank B"), primary=True)
        self.assertEqual(User.objects.filter(is_primary_pengelola=True).count(), 2)


class OnePrimaryMigrationTests(TransactionTestCase):
    def tearDown(self) -> None:
        # The failing-migration test leaves duplicates behind; clean them so
        # the final migrate (and later tests) start from valid data.
        _migrate(BEFORE)
        executor = MigrationExecutor(connection)
        User = executor.loader.project_state(BEFORE).apps.get_model("api", "User")
        User.objects.all().delete()
        BankSampah = executor.loader.project_state(BEFORE).apps.get_model("api", "BankSampah")
        BankSampah.objects.all().delete()
        call_command("migrate", verbosity=0)

    def _seed(self, primaries: int) -> str:
        executor = _migrate(BEFORE)
        apps = executor.loader.project_state(BEFORE).apps
        bank = apps.get_model("api", "BankSampah").objects.create(
            nama="Bank Ganda", alamat="Depok", kota="Depok", no_hp_pic="+628111111111"
        )
        for i in range(primaries):
            apps.get_model("api", "User").objects.create(
                email=f"p{i}@example.com",
                nama=f"P{i}",
                role="pengelola",
                bank_sampah=bank,
                is_primary_pengelola=True,
            )
        return str(bank.pk)

    def test_clean_data_migrates(self) -> None:
        self._seed(primaries=1)
        _migrate(AFTER)

    def test_duplicates_abort_with_the_offending_bank_id(self) -> None:
        bank_id = self._seed(primaries=2)
        with self.assertRaises(RuntimeError) as ctx:
            _migrate(AFTER)
        self.assertIn(bank_id, str(ctx.exception))
        self.assertIn("lebih dari satu Pengurus Utama", str(ctx.exception))
