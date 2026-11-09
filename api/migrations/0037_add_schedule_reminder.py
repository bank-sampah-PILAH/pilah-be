from datetime import timedelta
from typing import Any

from django.db import migrations, models
from django.utils import timezone


def skip_reminders_already_due(apps: Any, schema_editor: Any) -> None:
    JadwalKegiatan = apps.get_model("api", "JadwalKegiatan")
    now = timezone.now()
    JadwalKegiatan.objects.using(schema_editor.connection.alias).filter(
        status="diterbitkan",
        reminder_queued_at__isnull=True,
        mulai_pada__gt=now,
        mulai_pada__lte=now + timedelta(hours=2),
    ).update(reminder_queued_at=now)


class Migration(migrations.Migration):
    dependencies = [("api", "0036_pushnotification_hidden_at")]

    operations = [
        migrations.AddField(
            model_name="jadwalkegiatan",
            name="reminder_queued_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(skip_reminders_already_due, migrations.RunPython.noop),
    ]
