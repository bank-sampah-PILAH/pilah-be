import uuid
from typing import Any

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models

from shared_kernel.models import TimestampedModel


class UserManager(BaseUserManager["User"]):
    def create_user(self, email: str, password: str | None = None, **extra_fields: Any) -> "User":
        if not email:
            raise ValueError("Email wajib diisi")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self, email: str, password: str | None = None, **extra_fields: Any
    ) -> "User":
        extra_fields.setdefault("role", User.Role.SUPERADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, TimestampedModel):
    class Gender(models.TextChoices):
        MALE = "laki-laki", "Laki-laki"
        FEMALE = "perempuan", "Perempuan"

    class Role(models.TextChoices):
        PENGELOLA = "pengelola", "Pengelola"
        PENGELOLA_INDUK = "pengelola_induk", "Pengelola Induk"
        NASABAH = "nasabah", "Nasabah"
        SUPERADMIN = "superadmin", "Superadmin"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    google_id = models.CharField(max_length=255, blank=True, unique=True, null=True)
    email = models.EmailField(unique=True)
    nama = models.CharField(max_length=150)
    no_hp = models.CharField(max_length=20, blank=True)
    jenis_kelamin = models.CharField(max_length=20, choices=Gender.choices, blank=True)
    tanggal_lahir = models.DateField(blank=True, null=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PENGELOLA)
    is_profile_complete = models.BooleanField(default=False)
    bank_sampah = models.ForeignKey(
        "api.BankSampah",
        on_delete=models.PROTECT,
        related_name="users",
        blank=True,
        null=True,
    )
    is_primary_pengelola = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: "list[str]" = []  # type: ignore[misc]  # stubs declare class var on base

    class Meta:
        # ponytail: single Django app label until the squash migration; db_table
        # frozen so this move is code-only with zero migrations.
        app_label = "api"
        db_table = "users"
        ordering = ["nama"]

    def clean(self) -> None:
        super().clean()
        if self._state.adding or self.role == self.Role.NASABAH:
            return
        previous_role = type(self).objects.filter(pk=self.pk).values_list("role", flat=True).first()
        if previous_role == self.Role.NASABAH and self.keanggotaan_nasabah.exists():
            raise ValidationError(
                {
                    "role": "Pengguna Nasabah yang masih memiliki keanggotaan tidak dapat berganti peran."
                }
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        update_fields = kwargs.get("update_fields")
        if update_fields is None or "role" in update_fields:
            self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.email
