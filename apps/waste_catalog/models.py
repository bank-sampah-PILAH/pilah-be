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
