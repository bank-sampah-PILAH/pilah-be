import uuid

from django.db import models
from django.utils import timezone

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


class Transaksi(TimestampedModel):
    class Tipe(models.TextChoices):
        SETORAN = "setoran", "Setoran"

    class StatusWA(models.TextChoices):
        BELUM_DIKIRIM = "belum_dikirim", "Belum Dikirim"
        TERKIRIM = "terkirim", "Terkirim"
        GAGAL = "gagal", "Gagal"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nasabah = models.ForeignKey("api.Nasabah", on_delete=models.PROTECT, related_name="transaksi")
    bank_sampah = models.ForeignKey(
        "api.BankSampah", on_delete=models.PROTECT, related_name="transaksi"
    )
    dicatat_oleh = models.ForeignKey(
        "api.User", on_delete=models.PROTECT, related_name="transaksi_dicatat"
    )
    tanggal = models.DateTimeField(default=timezone.now)
    total_nilai = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tipe = models.CharField(max_length=20, choices=Tipe.choices, default=Tipe.SETORAN)
    catatan = models.TextField(blank=True, null=True)
    status_wa = models.CharField(
        max_length=20, choices=StatusWA.choices, default=StatusWA.BELUM_DIKIRIM
    )

    class Meta:
        # ponytail: single Django app label until the squash migration; db_table
        # frozen so this move is code-only with zero migrations.
        app_label = "api"
        db_table = "transaksi"
        ordering = ["-tanggal"]


class DetailTransaksi(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaksi = models.ForeignKey(Transaksi, on_delete=models.CASCADE, related_name="items")
    jenis_sampah = models.ForeignKey(
        "api.JenisSampah", on_delete=models.PROTECT, related_name="detail_transaksi"
    )
    nama_sampah_snapshot = models.CharField(max_length=50)
    kategori_snapshot = models.CharField(max_length=20)
    harga_snapshot = models.DecimalField(max_digits=11, decimal_places=2)
    berat = models.DecimalField(max_digits=10, decimal_places=3)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        app_label = "api"
        db_table = "detail_transaksi"


class Pencairan(TimestampedModel):
    class Metode(models.TextChoices):
        TUNAI = "tunai", "Tunai"
        TRANSFER = "transfer", "Transfer"

    class Status(models.TextChoices):
        TERCATAT = "tercatat", "Tercatat"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nasabah = models.ForeignKey("api.Nasabah", on_delete=models.PROTECT, related_name="pencairan")
    bank_sampah = models.ForeignKey(
        "api.BankSampah", on_delete=models.PROTECT, related_name="pencairan"
    )
    dicatat_oleh = models.ForeignKey(
        "api.User", on_delete=models.PROTECT, related_name="pencairan_dicatat"
    )
    tanggal = models.DateTimeField(default=timezone.now)
    nominal = models.DecimalField(max_digits=14, decimal_places=2)
    metode = models.CharField(max_length=20, choices=Metode.choices)
    keterangan = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TERCATAT)
    # Receipt snapshots at record time; PIL-230 decides how edits affect them.
    saldo_sebelum = models.DecimalField(max_digits=14, decimal_places=2)
    saldo_sesudah = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        app_label = "api"
        db_table = "pencairan"
        ordering = ["-tanggal"]
        indexes = [models.Index(fields=["bank_sampah", "nasabah", "tanggal"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(nominal__gt=0), name="pencairan_nominal_positive"
            ),
        ]


class PencairanRevisi(models.Model):
    """A replaced version of a pencairan (PIL-230). Append-only: never edited or deleted."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pencairan = models.ForeignKey(Pencairan, on_delete=models.PROTECT, related_name="revisi")
    versi = models.PositiveIntegerField()
    tanggal = models.DateTimeField()
    nominal = models.DecimalField(max_digits=14, decimal_places=2)
    metode = models.CharField(max_length=20, choices=Pencairan.Metode.choices)
    keterangan = models.TextField(blank=True)
    saldo_sebelum = models.DecimalField(max_digits=14, decimal_places=2)
    saldo_sesudah = models.DecimalField(max_digits=14, decimal_places=2)
    # Why this version was replaced, by whom and when.
    alasan = models.CharField(max_length=255)
    diubah_oleh = models.ForeignKey(
        "api.User", on_delete=models.PROTECT, related_name="pencairan_revisi_dibuat"
    )
    diubah_pada = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "api"
        db_table = "pencairan_revisi"
        ordering = ["pencairan", "versi"]
        constraints = [
            models.UniqueConstraint(fields=["pencairan", "versi"], name="pencairan_revisi_unik"),
        ]
