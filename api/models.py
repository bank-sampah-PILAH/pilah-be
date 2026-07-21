import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BankSampah(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nama = models.CharField(max_length=150)
    alamat = models.TextField(blank=True)
    kota = models.CharField(max_length=100, blank=True)
    no_hp_pic = models.CharField(max_length=20)
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

    def __str__(self):
        return self.nama


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email wajib diisi")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
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
    bank_sampah = models.ForeignKey(BankSampah, on_delete=models.PROTECT, related_name="users", blank=True, null=True)
    is_primary_pengelola = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"
        ordering = ["nama"]

    def __str__(self):
        return self.email


class Nasabah(TimestampedModel):
    class Gender(models.TextChoices):
        MALE = "laki-laki", "Laki-laki"
        FEMALE = "perempuan", "Perempuan"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bank_sampah = models.ForeignKey(BankSampah, on_delete=models.CASCADE, related_name="nasabah")
    nomor = models.CharField(max_length=30)
    nama = models.CharField(max_length=100)
    jenis_kelamin = models.CharField(max_length=20, choices=Gender.choices, blank=True)
    tanggal_lahir = models.DateField(blank=True, null=True)
    alamat = models.TextField()
    no_hp = models.CharField(max_length=20)
    tanggal_daftar = models.DateField(default=timezone.localdate)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "nasabah"
        unique_together = (("bank_sampah", "nomor"), ("bank_sampah", "no_hp"))
        ordering = ["nomor"]

    def __str__(self):
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
    bank_sampah = models.ForeignKey(BankSampah, on_delete=models.CASCADE, related_name="jenis_sampah")
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

    def __str__(self):
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
    dicatat_oleh = models.ForeignKey(User, on_delete=models.PROTECT, related_name="transaksi_dicatat")
    tanggal = models.DateTimeField(default=timezone.now)
    total_nilai = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tipe = models.CharField(max_length=20, choices=Tipe.choices, default=Tipe.SETORAN)
    catatan = models.TextField(blank=True, null=True)
    status_wa = models.CharField(max_length=20, choices=StatusWA.choices, default=StatusWA.BELUM_DIKIRIM)

    class Meta:
        db_table = "transaksi"
        ordering = ["-tanggal"]


class DetailTransaksi(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaksi = models.ForeignKey(Transaksi, on_delete=models.CASCADE, related_name="items")
    jenis_sampah = models.ForeignKey(JenisSampah, on_delete=models.PROTECT, related_name="detail_transaksi")
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
    bank_sampah = models.ForeignKey(BankSampah, on_delete=models.CASCADE, related_name="approval_logs")
    superadmin = models.ForeignKey(User, on_delete=models.PROTECT, related_name="approval_logs")
    status = models.CharField(max_length=20, choices=Status.choices)
    catatan = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bs_approval_log"
