"""Physical Postgres indexes must match Django's icontains expressions."""

from unittest import skipUnless
from unittest.mock import Mock

from django.db import connection
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations.special import RunPython
from django.test import SimpleTestCase, TestCase


@skipUnless(connection.vendor == "sqlite", "SQLite migration compatibility")
class NasabahSearchSQLiteMigrationTests(SimpleTestCase):
    def test_forward_and_reverse_never_execute_postgres_sql(self) -> None:
        loader = MigrationLoader(None)
        migration = loader.disk_migrations[("api", "0028_nasabah_search_trigrams")]
        operation = migration.operations[0]
        assert isinstance(operation, RunPython)
        reverse_code = operation.reverse_code
        assert reverse_code is not None
        editor = Mock(spec=BaseDatabaseSchemaEditor)
        editor.connection = connection
        apps = loader.project_state().apps
        operation.code(apps, editor)
        reverse_code(apps, editor)
        editor.execute.assert_not_called()


@skipUnless(connection.vendor == "postgresql", "Postgres-specific search indexes")
class NasabahSearchIndexTests(TestCase):
    def test_search_index_build_is_non_atomic(self) -> None:
        migration = MigrationLoader(connection).disk_migrations[
            ("api", "0028_nasabah_search_trigrams")
        ]
        self.assertFalse(migration.atomic)

    def test_index_migration_can_be_reversed_and_reapplied(self) -> None:
        loader = MigrationLoader(connection)
        migration = loader.disk_migrations[("api", "0028_nasabah_search_trigrams")]
        operation = migration.operations[0]
        state = loader.project_state()
        with connection.schema_editor() as editor:
            operation.database_backwards("api", editor, state, state)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM pg_indexes "
                    "WHERE tablename = 'nasabah' AND indexname LIKE 'nasabah_%%_trgm_idx'"
                )
                self.assertEqual(cursor.fetchone()[0], 0)
            operation.database_forwards("api", editor, state, state)
        self.test_all_search_fields_have_upper_trigram_indexes()

    def test_all_search_fields_have_upper_trigram_indexes(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'nasabah'")
            indexes = dict(cursor.fetchall())
        for field in ("nomor", "nama", "no_hp", "email"):
            with self.subTest(field=field):
                definition = indexes[f"nasabah_{field}_trgm_idx"].lower()
                self.assertIn("using gin", definition)
                self.assertIn("upper(", definition)
                self.assertIn(field, definition)
                self.assertIn("gin_trgm_ops", definition)
