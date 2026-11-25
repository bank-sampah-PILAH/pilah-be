from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class RolesMigrationTest(TransactionTestCase):
    def test_existing_accounts_receive_their_primary_role(self) -> None:
        executor = MigrationExecutor(connection)
        before = [("api", "0041_pengurus_dikeluarkan")]
        executor.migrate(before)
        try:
            OldUser = executor.loader.project_state(before).apps.get_model("api", "User")
            ids = {}
            for role in ("nasabah", "pengelola", "superadmin"):
                user = OldUser.objects.create(email=f"old-{role}@example.com", role=role)
                ids[user.pk] = role
            executor = MigrationExecutor(connection)
            after = [("api", "0042_user_roles")]
            executor.migrate(after)
            NewUser = executor.loader.project_state(after).apps.get_model("api", "User")
            for pk, role in ids.items():
                user = NewUser.objects.get(pk=pk)
                self.assertEqual(user.roles, [role])
                self.assertEqual(user.role, role)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
