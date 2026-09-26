import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from shared_kernel.models import TimestampedModel


class Nasabah(TimestampedModel):
    class Gender(models.TextChoices):
        MALE = "laki-laki", "Laki-laki"
        FEMALE = "perempuan", "Perempuan"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "api.User",
        on_delete=models.PROTECT,
        related_name="keanggotaan_nasabah",
        blank=True,
        null=True,
    )
    bank_sampah = models.ForeignKey(
        "api.BankSampah", on_delete=models.CASCADE, related_name="nasabah"
    )
    nomor = models.CharField(max_length=30)
    nama = models.CharField(max_length=100)
    jenis_kelamin = models.CharField(max_length=20, choices=Gender.choices, blank=True)
    tanggal_lahir = models.DateField(blank=True, null=True)
    alamat = models.TextField()
    no_hp = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True, unique=True)
    tanggal_daftar = models.DateField(default=timezone.localdate)
    is_active = models.BooleanField(default=True)
    # Approval state of the membership (PIL-188): pending = self-registered
    # awaiting pengurus decision, approved = active membership, rejected =
    # kept as audit record. is_active stays the manual toggle on top.
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.APPROVED)

    class Meta:
        # ponytail: single Django app label until the squash migration; db_table
        # frozen so this move is code-only with zero migrations.
        app_label = "api"
        db_table = "nasabah"
        unique_together = (("bank_sampah", "nomor"), ("bank_sampah", "no_hp"))
        ordering = ["nomor"]
        constraints = [
            models.UniqueConstraint(
                fields=["bank_sampah", "user"],
                condition=models.Q(user__isnull=False),
                name="nasabah_user_once_per_bank",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.user_id:
            from api.models import User

            user_role = User.objects.filter(pk=self.user_id).values_list("role", flat=True).first()
            if user_role != User.Role.NASABAH:
                raise ValidationError({"user": "Keanggotaan hanya dapat dikaitkan dengan Nasabah."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.nomor} - {self.nama}"


class Saldo(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nasabah = models.OneToOneField(Nasabah, on_delete=models.CASCADE, related_name="saldo")
    total_saldo = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "saldo"


class NasabahApprovalLog(models.Model):
    class Status(models.TextChoices):
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nasabah = models.ForeignKey(Nasabah, on_delete=models.CASCADE, related_name="approval_logs")
    pengurus = models.ForeignKey(
        "api.User", on_delete=models.PROTECT, related_name="nasabah_approval_logs"
    )
    status = models.CharField(max_length=20, choices=Status.choices)
    catatan = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "api"
        db_table = "nasabah_approval_log"
        ordering = ["-created_at"]
