"""Pengumuman: a bank sampah's announcements to its nasabah (PIL-243).

The pengurus authors announcements for all nasabah of their own bank sampah.
`terjadwal`, `terbit`, and `kedaluwarsa` are derived from the publish and
expiry times at query time, so no scheduled job is needed to move an
announcement between states.
"""

import uuid

from django.db import models
from django.utils import timezone

from shared_kernel.models import TimestampedModel

_USER_API = "api.User"


class Pengumuman(TimestampedModel):
    class Status(models.TextChoices):
        # Persisted state: draft before the publish action, terbit after it,
        # ditarik once withdrawn. terjadwal/kedaluwarsa are never persisted.
        DRAFT = "draft", "Draft"
        TERBIT = "terbit", "Terbit"
        DITARIK = "ditarik", "Ditarik"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bank_sampah = models.ForeignKey(
        "api.BankSampah", on_delete=models.CASCADE, related_name="pengumuman"
    )
    judul = models.CharField(max_length=150)
    isi = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    terbit_pada = models.DateTimeField(null=True, blank=True)
    masa_berlaku_hingga = models.DateTimeField(null=True, blank=True)
    dibuat_oleh = models.ForeignKey(
        _USER_API, on_delete=models.PROTECT, related_name="pengumuman_dibuat"
    )
    diterbitkan_oleh = models.ForeignKey(
        _USER_API,
        on_delete=models.PROTECT,
        related_name="pengumuman_diterbitkan",
        null=True,
        blank=True,
    )
    ditarik_oleh = models.ForeignKey(
        _USER_API,
        on_delete=models.PROTECT,
        related_name="pengumuman_ditarik",
        null=True,
        blank=True,
    )
    ditarik_pada = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "api"
        db_table = "pengumuman"
        ordering = ["-terbit_pada", "-created_at", "id"]
        indexes = [models.Index(fields=["bank_sampah", "status", "terbit_pada"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(masa_berlaku_hingga__isnull=True, terbit_pada__isnull=True)
                | models.Q(masa_berlaku_hingga__gt=models.F("terbit_pada")),
                name="pengumuman_berlaku_setelah_terbit",
            )
        ]

    def status_efektif(self) -> str:
        """Derived display status. terjadwal = not yet due (whether a plain
        draft with a schedule or published ahead of its publish time)."""
        if self.status == self.Status.DITARIK:
            return "ditarik"
        now = timezone.now()
        if self.terbit_pada is not None and self.terbit_pada > now:
            return "terjadwal"
        if self.status == self.Status.DRAFT:
            return "draft"
        if self.masa_berlaku_hingga is not None and now >= self.masa_berlaku_hingga:
            return "kedaluwarsa"
        return "terbit"

    @classmethod
    def aktif(cls) -> models.QuerySet["Pengumuman"]:
        """The single nasabah-visibility rule (PIL-244/333): published with the
        publish time arrived, not expired, not withdrawn."""
        now = timezone.now()
        return cls.objects.filter(
            status=cls.Status.TERBIT,
            terbit_pada__lte=now,
        ).filter(models.Q(masa_berlaku_hingga__isnull=True) | models.Q(masa_berlaku_hingga__gt=now))


class PengumumanDibaca(TimestampedModel):
    """Per-user read receipt (PIL-244). Unique per (pengumuman, user)."""

    pengumuman = models.ForeignKey(Pengumuman, on_delete=models.CASCADE, related_name="dibaca_rows")
    user = models.ForeignKey(_USER_API, on_delete=models.PROTECT, related_name="pengumuman_dibaca")
    dibaca_pada = models.DateTimeField(default=timezone.now)

    class Meta:
        app_label = "api"
        db_table = "pengumuman_dibaca"
        constraints = [
            models.UniqueConstraint(fields=["pengumuman", "user"], name="pengumuman_dibaca_unik")
        ]
