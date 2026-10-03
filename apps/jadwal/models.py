"""Jadwal kegiatan: a bank sampah's activity schedule (penimbangan days,
pencairan days), with per-nasabah recipients and a status workflow.

Code-only move (PR #64 review): app_label stays "api" and db_table is frozen,
so zero migrations.
"""

import uuid

from django.db import models

from shared_kernel.models import TimestampedModel


class JadwalKegiatan(TimestampedModel):
    class JenisKegiatan(models.TextChoices):
        PENIMBANGAN = "penimbangan", "Penimbangan"
        PENCAIRAN = "pencairan", "Pencairan"

    class CakupanPenerima(models.TextChoices):
        SEMUA_NASABAH = "semua_nasabah", "Semua Nasabah"
        NASABAH_TERPILIH = "nasabah_terpilih", "Nasabah Terpilih"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        DITERBITKAN = "diterbitkan", "Diterbitkan"
        DIBATALKAN = "dibatalkan", "Dibatalkan"
        SELESAI = "selesai", "Selesai"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bank_sampah = models.ForeignKey(
        "api.BankSampah", on_delete=models.CASCADE, related_name="jadwal_kegiatan"
    )
    dibuat_oleh = models.ForeignKey(
        "api.User", on_delete=models.PROTECT, related_name="jadwal_kegiatan_dibuat"
    )
    jenis_kegiatan = models.CharField(max_length=20, choices=JenisKegiatan.choices)
    mulai_pada = models.DateTimeField()
    selesai_pada = models.DateTimeField()
    lokasi = models.CharField(max_length=255)
    keterangan = models.TextField(blank=True)
    cakupan_penerima = models.CharField(
        max_length=30,
        choices=CakupanPenerima.choices,
        default=CakupanPenerima.SEMUA_NASABAH,
    )
    penerima = models.ManyToManyField("api.Nasabah", related_name="jadwal_kegiatan", blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        app_label = "api"
        db_table = "jadwal_kegiatan"
        ordering = ["mulai_pada", "id"]
        indexes = [models.Index(fields=["bank_sampah", "status", "mulai_pada"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(selesai_pada__gt=models.F("mulai_pada")),
                name="jadwal_selesai_setelah_mulai",
            )
        ]
