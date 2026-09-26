import uuid

from django.db import models
from django.utils import timezone

# ponytail: canonical homes are apps.identity.models, apps.organization.models
# and apps.membership.models.
from apps.identity.models import User, UserManager  # noqa: F401
from apps.membership.models import Nasabah, NasabahApprovalLog, Saldo  # noqa: F401
from apps.organization.models import BankSampah, BankSampahApprovalLog  # noqa: F401
from shared_kernel.models import TimestampedModel


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
