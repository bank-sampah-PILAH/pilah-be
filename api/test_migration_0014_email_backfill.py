from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class Nasabah0014EmailBackfillTests(TransactionTestCase):
    """Migration 0014 makes Nasabah.email required. Rows written while the
    column was nullable (seeded fixtures, pengurus-entered rows created
    before PIL-204) must be backfilled, not left to break `migrate`."""

    # Both targets applied together: this is the real pre-0014 production
    # state, where the sibling 0011 branches (status, alamat) have already
    # merged via 0012 alongside the independent 0011_nasabah_email branch.
    migrate_from = [
        ("api", "0012_merge_20260921_1833"),
        ("api", "0011_nasabah_email"),
    ]
    migrate_to = [("api", "0015_merge_20260925_1833")]

    def setUp(self) -> None:
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        self.old_apps = executor.loader.project_state(self.migrate_from).apps
        self._seed_old_state()

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.migrate_to)
        self.new_apps = executor.loader.project_state(self.migrate_to).apps

    def _seed_old_state(self) -> None:
        BankSampah = self.old_apps.get_model("api", "BankSampah")
        User = self.old_apps.get_model("api", "User")
        Nasabah = self.old_apps.get_model("api", "Nasabah")

        bank_a = BankSampah.objects.create(
            nama="Bank A", alamat="Jl A", kota="Depok", no_hp_pic="+6281"
        )
        bank_b = BankSampah.objects.create(
            nama="Bank B", alamat="Jl B", kota="Depok", no_hp_pic="+6282"
        )
        shared_user = User.objects.create(
            email="shared.user@example.com",
            nama="Shared",
            no_hp="+62800",
            role="nasabah",
            is_profile_complete=True,
        )

        # NULL email, unlinked.
        Nasabah.objects.create(
            bank_sampah=bank_a, nomor="N1", nama="Nasabah 1", no_hp="+6288881", email=None
        )
        # Blank-string email, unlinked.
        Nasabah.objects.create(
            bank_sampah=bank_a, nomor="N2", nama="Nasabah 2", no_hp="+6288882", email=""
        )
        # NULL email, linked in bank A, but the linked user's email is already
        # taken by another row in the same bank -> must fall back to a
        # synthetic placeholder instead of violating the new per-bank
        # unique_together.
        Nasabah.objects.create(
            bank_sampah=bank_a,
            nomor="N3",
            nama="Nasabah 3",
            no_hp="+6288883",
            email=None,
            user=shared_user,
        )
        Nasabah.objects.create(
            bank_sampah=bank_a,
            nomor="N6",
            nama="Nasabah 6",
            no_hp="+6288886",
            email="shared.user@example.com",
        )
        # NULL email, linked in bank B (different bank -> no collision, takes
        # the linked user's email).
        Nasabah.objects.create(
            bank_sampah=bank_b,
            nomor="N4",
            nama="Nasabah 4",
            no_hp="+6288884",
            email=None,
            user=shared_user,
        )

        self.bank_a_id = bank_a.pk
        self.bank_b_id = bank_b.pk

    def tearDown(self) -> None:
        call_command("migrate", verbosity=0)

    def test_unlinked_rows_get_synthetic_placeholder(self) -> None:
        Nasabah = self.new_apps.get_model("api", "Nasabah")
        n1 = Nasabah.objects.get(nomor="N1")
        n2 = Nasabah.objects.get(nomor="N2")
        self.assertTrue(n1.email.endswith("@pengguna.invalid"))
        self.assertTrue(n2.email.endswith("@pengguna.invalid"))

    def test_linked_row_without_collision_takes_user_email(self) -> None:
        Nasabah = self.new_apps.get_model("api", "Nasabah")
        n4 = Nasabah.objects.get(nomor="N4")
        self.assertEqual(n4.email, "shared.user@example.com")

    def test_linked_row_with_same_bank_collision_falls_back_to_placeholder(self) -> None:
        Nasabah = self.new_apps.get_model("api", "Nasabah")
        n3 = Nasabah.objects.get(nomor="N3")
        n6 = Nasabah.objects.get(nomor="N6")
        self.assertTrue(n3.email.endswith("@pengguna.invalid"))
        self.assertEqual(n6.email, "shared.user@example.com")

    def test_migration_leaves_email_not_null_and_scoped_unique(self) -> None:
        field = connection.introspection.get_table_description(connection.cursor(), "nasabah")
        email_field = next(f for f in field if f.name == "email")
        self.assertFalse(email_field.null_ok)
