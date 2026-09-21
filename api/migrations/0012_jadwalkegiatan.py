import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("api", "0011_nasabah_status_nasabahapprovallog")]

    operations = [
        migrations.CreateModel(
            name="JadwalKegiatan",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "jenis_kegiatan",
                    models.CharField(
                        choices=[("penimbangan", "Penimbangan"), ("pencairan", "Pencairan")],
                        max_length=20,
                    ),
                ),
                ("mulai_pada", models.DateTimeField()),
                ("selesai_pada", models.DateTimeField()),
                ("lokasi", models.CharField(max_length=255)),
                ("keterangan", models.TextField(blank=True)),
                (
                    "cakupan_penerima",
                    models.CharField(
                        choices=[
                            ("semua_nasabah", "Semua Nasabah"),
                            ("nasabah_terpilih", "Nasabah Terpilih"),
                        ],
                        default="semua_nasabah",
                        max_length=30,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("diterbitkan", "Diterbitkan"),
                            ("dibatalkan", "Dibatalkan"),
                            ("selesai", "Selesai"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                (
                    "bank_sampah",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="jadwal_kegiatan",
                        to="api.banksampah",
                    ),
                ),
                (
                    "dibuat_oleh",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="jadwal_kegiatan_dibuat",
                        to="api.user",
                    ),
                ),
                (
                    "penerima",
                    models.ManyToManyField(
                        blank=True, related_name="jadwal_kegiatan", to="api.nasabah"
                    ),
                ),
            ],
            options={
                "db_table": "jadwal_kegiatan",
                "ordering": ["mulai_pada", "id"],
                "indexes": [
                    models.Index(
                        fields=["bank_sampah", "status", "mulai_pada"],
                        name="jadwal_kegi_bank_sa_4380db_idx",
                    )
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("selesai_pada__gt", models.F("mulai_pada"))),
                        name="jadwal_selesai_setelah_mulai",
                    )
                ],
            },
        )
    ]
