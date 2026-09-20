"""Aturan uang PILAH: rupiah selalu bilangan bulat, pembulatan selalu ke bawah.

Rupiah tidak mengenal sen, jadi setiap nilai uang yang disimpan maupun
ditampilkan harus berupa rupiah penuh. Pembulatan ke bawah mengikuti pola yang
sudah dipakai di repositori ini (``int()`` pada teks WhatsApp dan export Excel)
dan memastikan sistem tidak pernah mencatat nilai lebih besar dari hasil
timbangan.

Semua perhitungan nilai setoran harus lewat modul ini supaya angka di database,
aplikasi, pesan WhatsApp, dan laporan selalu sama.
"""

from decimal import ROUND_DOWN, Decimal

from api.models import JenisSampah

RUPIAH = Decimal("1")


def bulatkan_rupiah(nilai: Decimal) -> Decimal:
    """Bulatkan ``nilai`` ke bawah menjadi rupiah penuh.

    Dipakai juga untuk merapikan data lama yang terlanjur tersimpan bersen.
    """
    return nilai.quantize(RUPIAH, rounding=ROUND_DOWN)


def harga_berlaku(jenis: JenisSampah) -> Decimal:
    """Harga per kg yang berlaku untuk ``jenis`` saat ini.

    Satu-satunya sumber harga untuk transaksi adalah harga master milik bank
    sampah, bukan nilai yang dikirim client. Ketika riwayat harga berlaku per
    tanggal ditambahkan (PIL-137), pemilihan harga cukup diubah di sini.
    """
    return bulatkan_rupiah(jenis.harga_per_kg)


def hitung_subtotal(harga: Decimal, berat: Decimal) -> Decimal:
    """Nilai satu item setoran, dibulatkan ke bawah ke rupiah penuh.

    Pembulatan dilakukan per item supaya total transaksi selalu sama dengan
    jumlah subtotal yang tampil di riwayat dan pesan WhatsApp.
    """
    return bulatkan_rupiah(harga * berat)
