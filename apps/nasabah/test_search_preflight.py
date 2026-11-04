"""Deployment preflight must reject missing pg_trgm before migrations run."""

from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase


class SearchPreflightTests(TestCase):
    def test_missing_extension_fails_with_bootstrap_instructions(self) -> None:
        with patch.object(connection, "vendor", "postgresql"), patch.object(
            connection, "cursor"
        ) as cursor:
            cursor.return_value.__enter__.return_value.fetchone.return_value = (False,)
            with self.assertRaisesRegex(CommandError, "pg_trgm.*bootstrap"):
                call_command("check_search_prerequisites")
