from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class RemovePengelolaIndukRoleMigrationTests(TransactionTestCase):
    migrate_from = [("api", "0037_add_schedule_reminder")]
    migrate_to = [("api", "0038_remove_pengelola_induk_role")]

    def setUp(self) -> None:
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        self.old_apps = executor.loader.project_state(self.migrate_from).apps
        self._seed_legacy_user()

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.new_apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self) -> None:
        call_command("migrate", verbosity=0)

    def _seed_legacy_user(self) -> None:
        BankSampah = self.old_apps.get_model("api", "BankSampah")
        User = self.old_apps.get_model("api", "User")
        bank = BankSampah.objects.create(
            nama="Bank Induk", alamat="Depok", kota="Depok", no_hp_pic="+628111111111"
        )
        self.user_id = User.objects.create(
            email="induk@example.com",
            nama="Pengelola Induk",
            no_hp="+628123456789",
            jenis_kelamin="perempuan",
            tanggal_lahir="1990-01-02",
            alamat="Jl. Melati",
            role="pengelola_induk",
            is_profile_complete=True,
            bank_sampah=bank,
            is_primary_pengelola=True,
            is_active=True,
        ).pk
        self.bank_id = bank.pk

    def test_legacy_role_becomes_pengelola_without_changing_user_data(self) -> None:
        User = self.new_apps.get_model("api", "User")
        user = User.objects.get(pk=self.user_id)

        self.assertEqual(user.role, "pengelola")
        self.assertEqual(user.email, "induk@example.com")
        self.assertEqual(user.nama, "Pengelola Induk")
        self.assertEqual(user.no_hp, "+628123456789")
        self.assertEqual(user.jenis_kelamin, "perempuan")
        self.assertEqual(str(user.tanggal_lahir), "1990-01-02")
        self.assertEqual(user.alamat, "Jl. Melati")
        self.assertEqual(user.bank_sampah_id, self.bank_id)
        self.assertTrue(user.is_primary_pengelola)
        self.assertTrue(user.is_active)
