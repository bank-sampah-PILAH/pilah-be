import uuid

from django.db import models
from django.utils import timezone

# ponytail: canonical homes are apps.*.models.
from apps.catalog.models import JenisSampah  # noqa: F401
from apps.identity.models import User, UserManager  # noqa: F401
from apps.membership.models import Nasabah, NasabahApprovalLog, Saldo  # noqa: F401
from apps.organization.models import BankSampah, BankSampahApprovalLog  # noqa: F401
from shared_kernel.models import TimestampedModel


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
