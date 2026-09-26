import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from shared_kernel.models import TimestampedModel


class BankSampah(TimestampedModel):
    class OrganizationType(models.TextChoices):
        MANDIRI = "mandiri", "Mandiri"
        INDUK = "induk", "Induk"
        UNIT = "unit", "Unit"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nama = models.CharField(max_length=150)
    alamat = models.TextField(blank=True)
    kota = models.CharField(max_length=100, blank=True)
    no_hp_pic = models.CharField(max_length=20)
    jenis_organisasi = models.CharField(
        max_length=20, choices=OrganizationType.choices, default=OrganizationType.MANDIRI
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="units",
        blank=True,
        null=True,
    )
    wa_gateway_token = models.TextField(blank=True, null=True)
    wa_template = models.TextField(blank=True)
    foto_logo = models.FileField(upload_to="bank_sampah/logo/", blank=True)
    foto_kegiatan = models.FileField(upload_to="bank_sampah/kegiatan/", blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    invite_token = models.CharField(max_length=120, blank=True)
    invite_token_expires = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        # ponytail: single Django app label until the squash migration; db_table
        # frozen so this move is code-only with zero migrations.
        app_label = "api"
        db_table = "bank_sampah"
        ordering = ["nama"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        jenis_organisasi__in=["mandiri", "induk"],
                        parent__isnull=True,
                    )
                    | models.Q(
                        jenis_organisasi="unit",
                        parent__isnull=False,
                    )
                ),
                name="banksampah_type_parent_consistent",
            ),
            models.CheckConstraint(
                condition=~models.Q(id=models.F("parent_id")),
                name="banksampah_not_own_parent",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if (
            not self._state.adding
            and self.jenis_organisasi != self.OrganizationType.INDUK
            and self.units.exists()
        ):
            raise ValidationError(
                {"jenis_organisasi": "Bank Sampah Induk yang memiliki unit tidak dapat diturunkan."}
            )
        if self.jenis_organisasi == self.OrganizationType.UNIT and not self.parent_id:
            raise ValidationError({"parent": "Unit harus berada di bawah Bank Sampah Induk."})
        if self.jenis_organisasi != self.OrganizationType.UNIT and self.parent_id:
            raise ValidationError({"parent": "Hanya Bank Sampah Unit yang memiliki induk."})
        if self.parent_id:
            parent_type = (
                BankSampah.objects.filter(pk=self.parent_id)
                .values_list("jenis_organisasi", flat=True)
                .first()
            )
            if parent_type and parent_type != self.OrganizationType.INDUK:
                raise ValidationError({"parent": "Unit harus berada di bawah Bank Sampah Induk."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Keep hierarchy validation on the write path without running all field
        # validators and uniqueness queries for unrelated updates. Bulk writes
        # still bypass model validation and must not be used for hierarchy changes.
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.nama


class BankSampahApprovalLog(models.Model):
    class Status(models.TextChoices):
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bank_sampah = models.ForeignKey(
        BankSampah, on_delete=models.CASCADE, related_name="approval_logs"
    )
    superadmin = models.ForeignKey(
        "api.User", on_delete=models.PROTECT, related_name="approval_logs"
    )
    status = models.CharField(max_length=20, choices=Status.choices)
    catatan = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "api"
        db_table = "bs_approval_log"
