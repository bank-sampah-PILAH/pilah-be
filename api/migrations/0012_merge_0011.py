# Merge the duplicate 0011 leaves (both branched from 0010 with independent
# operations). No-op: only unifies the migration graph into a single leaf.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0011_nasabah_email"),
        ("api", "0011_nasabah_status_nasabahapprovallog"),
    ]

    operations = []
