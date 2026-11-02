"""Physical Postgres indexes must match Django's icontains expressions."""

from unittest import skipUnless

from django.db import connection
from django.test import TestCase


@skipUnless(connection.vendor == "postgresql", "Postgres-specific search indexes")
class NasabahSearchIndexTests(TestCase):
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
