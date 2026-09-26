import uuid
from typing import Any

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


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
        BankSampah, on_delete=models.PROTECT, related_name="users", blank=True, null=True
    )
    is_primary_pengelola = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: "list[str]" = []  # type: ignore[misc]  # stubs declare class var on base

    class Meta:
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
        User,
        on_delete=models.PROTECT,
        related_name="keanggotaan_nasabah",
        blank=True,
        null=True,
    )
    bank_sampah = models.ForeignKey(BankSampah, on_delete=models.CASCADE, related_name="nasabah")
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
        db_table = "saldo"


class JenisSampah(models.Model):
    class Kategori(models.TextChoices):
        KERTAS = "kertas", "Kertas"
        PLASTIK = "plastik", "Plastik"
        LOGAM = "logam", "Logam"
        KACA = "kaca", "Kaca"
        DLL = "dll", "Dll"
        ORGANIK = "organik", "Organik"
        ANORGANIK = "anorganik", "Anorganik"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bank_sampah = models.ForeignKey(
        BankSampah, on_delete=models.CASCADE, related_name="jenis_sampah"
    )
    nomor = models.CharField(max_length=30)
    nama_sampah = models.CharField(max_length=50)
    kategori = models.CharField(max_length=20, choices=Kategori.choices, default=Kategori.PLASTIK)
    deskripsi = models.TextField(blank=True)
    harga_per_kg = models.DecimalField(max_digits=11, decimal_places=2)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "jenis_sampah"
        unique_together = (("bank_sampah", "nomor"),)
        ordering = ["nomor"]

    def __str__(self) -> str:
        return self.nama_sampah


class Transaksi(TimestampedModel):
    class Tipe(models.TextChoices):
        SETORAN = "setoran", "Setoran"

    class StatusWA(models.TextChoices):
        BELUM_DIKIRIM = "belum_dikirim", "Belum Dikirim"
        TERKIRIM = "terkirim", "Terkirim"
        GAGAL = "gagal", "Gagal"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nasabah = models.ForeignKey(Nasabah, on_delete=models.PROTECT, related_name="transaksi")
    bank_sampah = models.ForeignKey(BankSampah, on_delete=models.PROTECT, related_name="transaksi")
    dicatat_oleh = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="transaksi_dicatat"
    )
    tanggal = models.DateTimeField(default=timezone.now)
    total_nilai = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tipe = models.CharField(max_length=20, choices=Tipe.choices, default=Tipe.SETORAN)
    catatan = models.TextField(blank=True, null=True)
    status_wa = models.CharField(
        max_length=20, choices=StatusWA.choices, default=StatusWA.BELUM_DIKIRIM
    )

    class Meta:
        db_table = "transaksi"
        ordering = ["-tanggal"]


class DetailTransaksi(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaksi = models.ForeignKey(Transaksi, on_delete=models.CASCADE, related_name="items")
    jenis_sampah = models.ForeignKey(
        JenisSampah, on_delete=models.PROTECT, related_name="detail_transaksi"
    )
    nama_sampah_snapshot = models.CharField(max_length=50)
    kategori_snapshot = models.CharField(max_length=20)
    harga_snapshot = models.DecimalField(max_digits=11, decimal_places=2)
    berat = models.DecimalField(max_digits=10, decimal_places=3)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        db_table = "detail_transaksi"


class BankSampahApprovalLog(models.Model):
    class Status(models.TextChoices):
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bank_sampah = models.ForeignKey(
        BankSampah, on_delete=models.CASCADE, related_name="approval_logs"
    )
    superadmin = models.ForeignKey(User, on_delete=models.PROTECT, related_name="approval_logs")
    status = models.CharField(max_length=20, choices=Status.choices)
    catatan = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bs_approval_log"


class NasabahApprovalLog(models.Model):
    class Status(models.TextChoices):
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nasabah = models.ForeignKey(Nasabah, on_delete=models.CASCADE, related_name="approval_logs")
    pengurus = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="nasabah_approval_logs"
    )
    status = models.CharField(max_length=20, choices=Status.choices)
    catatan = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "nasabah_approval_log"
        ordering = ["-created_at"]
