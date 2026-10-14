"""Aturan uang PILAH: rupiah selalu bilangan bulat, pembulatan selalu ke bawah.

Rupiah tidak mengenal sen, jadi setiap nilai uang yang disimpan maupun
ditampilkan harus berupa rupiah penuh. Pembulatan ke bawah mengikuti pola yang
sudah dipakai di repositori ini (``int()`` pada teks WhatsApp dan export Excel)
dan memastikan sistem tidak pernah mencatat nilai lebih besar dari hasil
timbangan.

Semua perhitungan nilai setoran harus lewat modul ini supaya angka di database,
aplikasi, pesan WhatsApp, dan laporan selalu sama. Pemilihan harga yang berlaku
bukan perhitungan; tempatnya ``apps.waste_catalog.api.harga_berlaku``.
"""

from collections.abc import Iterable
from decimal import ROUND_DOWN, Decimal

RUPIAH = Decimal(1)


def bulatkan_rupiah(nilai: Decimal) -> Decimal:
    """Bulatkan ``nilai`` ke bawah menjadi rupiah penuh.

    Dipakai juga untuk merapikan data lama yang terlanjur tersimpan bersen.
    """
    return nilai.quantize(RUPIAH, rounding=ROUND_DOWN)


def hitung_subtotal(harga: Decimal, berat: Decimal) -> Decimal:
    """Nilai satu item setoran, dibulatkan ke bawah ke rupiah penuh.

    Pembulatan dilakukan per item supaya total transaksi selalu sama dengan
    jumlah subtotal yang tampil di riwayat dan pesan WhatsApp.
    """
    return bulatkan_rupiah(harga * berat)


def total_setoran(subtotal: Iterable[Decimal]) -> Decimal:
    """Total satu setoran dari subtotal tiap itemnya.

    Subtotal sudah berupa rupiah penuh, jadi penjumlahannya tidak menambah
    sen baru. Dikumpulkan di sini supaya seluruh perhitungan nilai setoran
    berada di satu modul, sesuai aturan di ``AGENTS.md``.
    """
    return bulatkan_rupiah(sum(subtotal, Decimal(0)))


def format_ribuan(nilai: Decimal) -> str:
    """Tulis nilai sebagai rupiah penuh dengan pemisah ribuan, mis. "1.000".

    Dipakai pesan galat, pesan WhatsApp, dan laporan supaya konvensi angkanya
    hanya ditulis di satu tempat.
    """
    return f"{int(nilai):,}".replace(",", ".")
