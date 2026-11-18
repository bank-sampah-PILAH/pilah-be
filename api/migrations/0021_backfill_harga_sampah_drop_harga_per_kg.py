"""PIL-304: pindahkan harga jenis sampah ke HargaSampah, lalu hapus kolom lamanya.

Setiap jenis mendapat satu versi awal berisi harga kolom lama. Versi itu
berlaku sejak pemakaian paling awal yang diketahui: setoran pertama yang
memakai jenis tersebut, atau saat jenis terakhir disunting bila lebih awal.
Nilai setoran lama tidak disentuh karena tersimpan sebagai harga_snapshot
(SDS 7.1.2).

Kebalikannya mengisi kembali kolom dari harga yang berlaku saat itu.
"""

from typing import Any

from django.db import migrations, models
from django.db.models import Min
from django.utils import timezone


def isi_versi_awal(apps: Any, schema_editor: Any) -> None:
    JenisSampah = apps.get_model("api", "JenisSampah")
    HargaSampah = apps.get_model("api", "HargaSampah")
    DetailTransaksi = apps.get_model("api", "DetailTransaksi")
    # Lewati jenis yang sudah punya versi, agar menjalankan ulang migrasi
    # setelah dibalik tidak menambah versi awal kedua.
    for jenis in JenisSampah.objects.exclude(riwayat_harga__isnull=False).iterator():
        setoran_pertama = DetailTransaksi.objects.filter(jenis_sampah=jenis).aggregate(
            awal=Min("transaksi__tanggal")
        )["awal"]
        kandidat = [waktu for waktu in (setoran_pertama, jenis.updated_at) if waktu]
        HargaSampah.objects.create(
            jenis_sampah=jenis,
            bank_sampah_id=jenis.bank_sampah_id,
            harga_per_kg=jenis.harga_per_kg,
            berlaku_mulai=min(kandidat),
        )


def kembalikan_kolom(apps: Any, schema_editor: Any) -> None:
    JenisSampah = apps.get_model("api", "JenisSampah")
    HargaSampah = apps.get_model("api", "HargaSampah")
    sekarang = timezone.now()
    for jenis in JenisSampah.objects.iterator():
        riwayat = HargaSampah.objects.filter(jenis_sampah=jenis)
        versi = (
            riwayat.filter(berlaku_mulai__lte=sekarang).order_by("-berlaku_mulai", "-id").first()
            or riwayat.order_by("berlaku_mulai", "id").first()
        )
        if versi is not None:
            # update() alih-alih save(): updated_at milik pengurus, bukan migrasi.
            JenisSampah.objects.filter(pk=jenis.pk).update(harga_per_kg=versi.harga_per_kg)


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0020_harga_sampah"),
    ]

    operations = [
        migrations.AlterField(
            model_name="jenissampah",
            name="harga_per_kg",
            field=models.DecimalField(decimal_places=2, max_digits=11, null=True),
        ),
        migrations.RunPython(isi_versi_awal, kembalikan_kolom),
        migrations.RemoveField(
            model_name="jenissampah",
            name="harga_per_kg",
        ),
    ]
