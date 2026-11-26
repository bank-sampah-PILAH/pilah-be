from typing import Any

from django.db import migrations, models


def convert_pengelola_induk_users(apps: Any, schema_editor: Any) -> None:
    User = apps.get_model("api", "User")
    User.objects.using(schema_editor.connection.alias).filter(role="pengelola_induk").update(
        role="pengelola"
    )


class Migration(migrations.Migration):
    dependencies = [("api", "0037_add_schedule_reminder")]

    operations = [
        migrations.RunPython(convert_pengelola_induk_users, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("pengelola", "Pengelola"),
                    ("nasabah", "Nasabah"),
                    ("superadmin", "Superadmin"),
                ],
                default="pengelola",
                max_length=20,
            ),
        ),
    ]
