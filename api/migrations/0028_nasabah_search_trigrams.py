"""PostgreSQL-only physical indexes; SQLite keeps identical search semantics.

These expression indexes are database-specific rather than model state: adding
Postgres opclasses to model Meta would break SQLite table rebuilds. Django's
icontains compiles to UPPER(column::text) LIKE UPPER(parameter) on Postgres.
"""

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

SEARCH_FIELDS = ("nomor", "nama", "no_hp", "email")


def create_indexes(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for field in SEARCH_FIELDS:
        schema_editor.execute(
            f'CREATE INDEX CONCURRENTLY "nasabah_{field}_trgm_idx" '
            f'ON "nasabah" USING gin (UPPER("{field}"::text) gin_trgm_ops)'
        )


def drop_indexes(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    if schema_editor.connection.vendor != "postgresql":
        return
    for field in SEARCH_FIELDS:
        schema_editor.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "nasabah_{field}_trgm_idx"')
    # pg_trgm may be shared by other features; rollback never removes it.


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("api", "0027_merge_conflicting_leaves")]
    operations = [migrations.RunPython(create_indexes, drop_indexes, atomic=False)]
