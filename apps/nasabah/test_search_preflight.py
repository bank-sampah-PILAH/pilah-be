"""Deployment preflight must reject missing pg_trgm before migrations run."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection
from django.test import TestCase


class SearchPreflightTests(TestCase):
    def test_installed_extension_check_does_not_change_the_database(self) -> None:
        with (
            patch.object(connection, "vendor", "postgresql"),
            patch.object(connection, "cursor") as cursor,
        ):
            db = cursor.return_value.__enter__.return_value
            db.fetchone.return_value = (True,)
            output = StringIO()
            call_command("check_search_prerequisites", stdout=output)
            self.assertIn("pg_trgm is installed", output.getvalue())
            self.assertEqual(db.execute.call_count, 1)
            self.assertTrue(db.execute.call_args.args[0].startswith("SELECT"))

    def test_explicit_bootstrap_installs_and_then_checks_the_extension(self) -> None:
        with (
            patch.object(connection, "vendor", "postgresql"),
            patch.object(connection, "cursor") as cursor,
        ):
            db = cursor.return_value.__enter__.return_value
            db.fetchone.return_value = (True,)
            call_command("check_search_prerequisites", install_extension=True, stdout=StringIO())
            self.assertEqual(
                db.execute.call_args_list[0].args[0], "CREATE EXTENSION IF NOT EXISTS pg_trgm"
            )
            self.assertEqual(db.execute.call_count, 2)

    def test_bootstrap_permission_failure_has_actionable_instructions(self) -> None:
        with (
            patch.object(connection, "vendor", "postgresql"),
            patch.object(connection, "cursor") as cursor,
        ):
            cursor.return_value.__enter__.return_value.execute.side_effect = DatabaseError(
                "permission denied"
            )
            with self.assertRaisesRegex(CommandError, "authorized database role"):
                call_command("check_search_prerequisites", install_extension=True)

    def test_sqlite_never_attempts_extension_installation(self) -> None:
        with (
            patch.object(connection, "vendor", "sqlite"),
            patch.object(connection, "cursor") as cursor,
        ):
            call_command("check_search_prerequisites", install_extension=True, stdout=StringIO())
            cursor.assert_not_called()

    def test_missing_extension_fails_with_bootstrap_instructions(self) -> None:
        with (
            patch.object(connection, "vendor", "postgresql"),
            patch.object(connection, "cursor") as cursor,
        ):
            cursor.return_value.__enter__.return_value.fetchone.return_value = (False,)
            with self.assertRaisesRegex(CommandError, "pg_trgm.*bootstrap"):
                call_command("check_search_prerequisites")
