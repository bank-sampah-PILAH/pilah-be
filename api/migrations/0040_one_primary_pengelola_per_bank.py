from django.db import migrations, models
from django.db.models import Count


def refuse_banks_with_several_primaries(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Fail loudly instead of letting AddConstraint die with a bare IntegrityError.

    The operator has to decide which pengurus stays Pengurus Utama; guessing
    here would silently strip someone of their role.
    """
    User = apps.get_model("api", "User")
    duplicated = (
        User.objects.filter(is_primary_pengelola=True, bank_sampah__isnull=False)
        .values("bank_sampah")
        .annotate(total=Count("pk"))
        .filter(total__gt=1)
    )
    bank_ids = sorted(str(row["bank_sampah"]) for row in duplicated)
    if bank_ids:
        raise RuntimeError(
            "Migrasi dibatalkan: bank sampah berikut memiliki lebih dari satu "
            f"Pengurus Utama: {', '.join(bank_ids)}. Sisakan satu Pengurus Utama "
            "per bank (is_primary_pengelola) lalu jalankan migrasi lagi."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0039_user_role_change_log"),
    ]

    operations = [
        migrations.RunPython(refuse_banks_with_several_primaries, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_primary_pengelola", True)),
                fields=("bank_sampah",),
                name="uniq_primary_pengelola_per_bank",
            ),
        ),
    ]
