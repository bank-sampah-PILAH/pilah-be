from django.apps.registry import Apps
from django.core.management import call_command
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def create_auth_rate_limit_cache_table(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    call_command(
        "createcachetable",
        "auth_rate_limit_cache",
        database=schema_editor.connection.alias,
        verbosity=0,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0025_user_email_verified"),
    ]

    operations = [
        migrations.RunPython(create_auth_rate_limit_cache_table, migrations.RunPython.noop),
    ]
