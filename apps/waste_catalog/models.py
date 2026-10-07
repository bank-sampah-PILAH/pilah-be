import uuid

from django.db import models


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
        "api.BankSampah", on_delete=models.CASCADE, related_name="jenis_sampah"
    )
    nomor = models.CharField(max_length=30)
    nama_sampah = models.CharField(max_length=50)
    kategori = models.CharField(max_length=20, choices=Kategori.choices, default=Kategori.PLASTIK)
    deskripsi = models.TextField(blank=True)
    harga_per_kg = models.DecimalField(max_digits=11, decimal_places=2)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # ponytail: single Django app label until the squash migration; db_table
        # frozen so this move is code-only with zero migrations.
        app_label = "api"
        db_table = "jenis_sampah"
        unique_together = (("bank_sampah", "nomor"),)
        ordering = ["nomor"]

    def __str__(self) -> str:
        return self.nama_sampah


class HargaSampah(models.Model):
    """Satu versi harga per kg sebuah jenis sampah, berlaku mulai ``berlaku_mulai``.

    Tabel ``waste_prices`` pada SDS 7.1.2: riwayat untuk penetapan harga dan
    audit. Baris tidak pernah diubah; perubahan harga adalah baris baru.
    """

    jenis_sampah = models.ForeignKey(
        JenisSampah, on_delete=models.PROTECT, related_name="riwayat_harga"
    )
    # Redundan dengan jenis_sampah.bank_sampah, sengaja: penyaringan lingkup
    # memakai kolom organisasi langsung (SDS 7.4.5).
    bank_sampah = models.ForeignKey(
        "api.BankSampah", on_delete=models.PROTECT, related_name="harga_sampah"
    )
    harga_per_kg = models.DecimalField(max_digits=11, decimal_places=2)
    berlaku_mulai = models.DateTimeField()
    # Jejak audit perubahan harga (BR-11): siapa dan kapan.
    dibuat_oleh = models.ForeignKey(
        "api.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="harga_sampah_dibuat",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "api"
        db_table = "harga_sampah"
        indexes = [models.Index(fields=["jenis_sampah", "berlaku_mulai"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(harga_per_kg__gt=0), name="harga_sampah_harga_positif"
            )
        ]

    def __str__(self) -> str:
        return f"{self.jenis_sampah_id} {self.harga_per_kg} @ {self.berlaku_mulai}"
