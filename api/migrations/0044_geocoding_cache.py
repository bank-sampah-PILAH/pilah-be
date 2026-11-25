from django.apps.registry import Apps
from django.core.management import call_command
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def create_geocoding_cache(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    call_command(
        "createcachetable",
        "geocoding_cache",
        database=schema_editor.connection.alias,
        verbosity=0,
    )


def drop_geocoding_cache(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    schema_editor.execute("DROP TABLE IF EXISTS geocoding_cache")


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0042_merge_pil326_staging"),
        ("api", "0043_merge_20261123_1455"),
    ]

    operations = [migrations.RunPython(create_geocoding_cache, drop_geocoding_cache)]
