import uuid
from collections.abc import Iterable
from typing import Any

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import connections, models

from shared_kernel.models import TimestampedModel


class UserManager(BaseUserManager["User"]):
    def bulk_create(self, objs: Iterable["User"], *args: Any, **kwargs: Any) -> list["User"]:
        users = list(objs)
        for user in users:
            if not user.roles:
                user.roles = [user.role]
            user.clean()
        return super().bulk_create(users, *args, **kwargs)

    def with_role(self, role: str) -> models.QuerySet["User"]:
        if connections[self.db].features.supports_json_field_contains:
            return self.filter(roles__contains=[role])
        # SQLite supports JSON array indexes, but not JSON containment. A valid
        # role list has at most one entry per declared role.
        predicate = models.Q()
        for index in range(len(User.Role)):
            predicate |= models.Q(**{f"roles__{index}": role})
        return self.filter(predicate)

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
        NASABAH = "nasabah", "Nasabah"
        SUPERADMIN = "superadmin", "Superadmin"

    GOOGLE_REGISTRATION_ROLES = (Role.PENGELOLA, Role.NASABAH)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    google_id = models.CharField(max_length=255, blank=True, unique=True, null=True)
    email = models.EmailField(unique=True)
    email_verified = models.BooleanField(default=False)
    nama = models.CharField(max_length=150)
    no_hp = models.CharField(max_length=20, blank=True)
    jenis_kelamin = models.CharField(max_length=20, choices=Gender.choices, blank=True)
    tanggal_lahir = models.DateField(blank=True, null=True)
    # Personal address, collected on complete_profile for nasabah accounts only
    # (PIL-204) — copied onto each Nasabah membership row at registration time.
    alamat = models.TextField(blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PENGELOLA)
    roles = models.JSONField(default=list)
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
        if (
            not isinstance(self.roles, list)
            or not self.roles
            or any(not isinstance(role, str) or role not in self.Role.values for role in self.roles)
            or len(set(self.roles)) != len(self.roles)
        ):
            raise ValidationError(
                {"roles": "Daftar peran harus berisi peran valid tanpa duplikasi."}
            )
        if (
            not self._state.adding
            and self.keanggotaan_nasabah.exists()
            and (self.Role.NASABAH not in self.roles or self.role not in self.roles)
        ):
            raise ValidationError(
                {
                    "role": "Pengguna Nasabah yang masih memiliki keanggotaan tidak dapat berganti peran."
                }
            )
        if self.role not in self.roles:
            raise ValidationError({"role": "Peran utama harus termasuk dalam daftar peran akun."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self._state.adding and not self.roles:
            self.roles = [self.role]
        update_fields = kwargs.get("update_fields")
        if update_fields is None or "role" in update_fields or "roles" in update_fields:
            self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.email
