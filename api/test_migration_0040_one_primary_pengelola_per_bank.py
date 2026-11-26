from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from api.models import BankSampah, User

BEFORE = [("api", "0039_user_role_change_log")]
AFTER = [("api", "0040_one_primary_pengelola_per_bank")]
# Rolling back the team constraint leaves the independent coordinate fields
# applied. Include them in the historical model state used to write fixtures.
FIXTURE_STATE = [*BEFORE, ("api", "0041_banksampah_koordinat_sumber_akurasi")]


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
        User = executor.loader.project_state(FIXTURE_STATE).apps.get_model("api", "User")
        User.objects.all().delete()
        BankSampah = executor.loader.project_state(FIXTURE_STATE).apps.get_model(
            "api", "BankSampah"
        )
        BankSampah.objects.all().delete()
        call_command("migrate", verbosity=0)

    def _seed(self, primaries: int) -> str:
        executor = _migrate(BEFORE)
        apps = executor.loader.project_state(FIXTURE_STATE).apps
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

    def _add_primary(self, bank_id: str, email: str) -> None:
        apps = MigrationExecutor(connection).loader.project_state(FIXTURE_STATE).apps
        apps.get_model("api", "User").objects.create(
            email=email,
            nama=email,
            role="pengelola",
            bank_sampah_id=bank_id,
            is_primary_pengelola=True,
        )

    def test_duplicate_of_the_staging_reviewer_and_another_primary_is_resolved(self) -> None:
        bank_id = self._seed(primaries=1)
        self._add_primary(bank_id, "Pilah.Pengelola@pilah.com")

        _migrate(AFTER)

        primaries = User.objects.filter(is_primary_pengelola=True, bank_sampah__pk=bank_id)
        self.assertEqual([user.email for user in primaries], ["p0@example.com"])
        reviewer = User.objects.get(email__iexact="pilah.pengelola@pilah.com")
        self.assertEqual(str(reviewer.bank_sampah_id), bank_id)
        self.assertFalse(reviewer.is_primary_pengelola)

    def test_other_duplicates_are_still_refused_with_the_bank_id(self) -> None:
        bank_id = self._seed(primaries=2)

        with self.assertRaises(RuntimeError) as ctx:
            _migrate(AFTER)

        self.assertIn(bank_id, str(ctx.exception))
        self.assertEqual(User.objects.filter(is_primary_pengelola=True).count(), 2)

    def test_reviewer_with_two_other_primaries_is_demoted_but_the_bank_is_still_refused(
        self,
    ) -> None:
        bank_id = self._seed(primaries=2)
        self._add_primary(bank_id, "pilah.pengelola@pilah.com")

        with self.assertRaises(RuntimeError) as ctx:
            _migrate(AFTER)

        self.assertIn(bank_id, str(ctx.exception))

    def test_sole_reviewer_primary_in_its_own_bank_is_untouched(self) -> None:
        executor = _migrate(BEFORE)
        apps = executor.loader.project_state(FIXTURE_STATE).apps
        bank = apps.get_model("api", "BankSampah").objects.create(
            nama="Bank Review", alamat="Depok", kota="Depok", no_hp_pic="+628111111111"
        )
        self._add_primary(str(bank.pk), "pilah.pengelola@pilah.com")

        _migrate(AFTER)

        self.assertTrue(User.objects.get(email="pilah.pengelola@pilah.com").is_primary_pengelola)
