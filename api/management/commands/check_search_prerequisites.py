"""Check search prerequisites before migrations; bootstrap is explicit."""

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection


class Command(BaseCommand):
    help = "Check pg_trgm before deployment; a database owner can explicitly bootstrap it."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--install-extension", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        if connection.vendor != "postgresql":
            self.stdout.write("Search prerequisites: PostgreSQL extension not needed.")
            return
        try:
            with connection.cursor() as cursor:
                if options["install_extension"]:
                    cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')"
                )
                installed = cursor.fetchone()
        except DatabaseError as exc:
            raise CommandError(
                "Cannot prepare pg_trgm; run bootstrap with an authorized database role: "
                "python manage.py check_search_prerequisites --install-extension"
            ) from exc
        if not installed or not installed[0]:
            raise CommandError(
                "pg_trgm missing; bootstrap before deployment with an authorized role: "
                "python manage.py check_search_prerequisites --install-extension"
            )
        self.stdout.write("Search prerequisites: pg_trgm is installed.")
