"""Public port of the catalog context."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from api.models import BankSampah, HargaSampah, JenisSampah


def get_active_jenis(bank: BankSampah, jenis_sampah_id: UUID) -> JenisSampah | None:
    return JenisSampah.objects.filter(id=jenis_sampah_id, bank_sampah=bank, is_active=True).first()


def harga_berlaku(jenis: JenisSampah, pada: datetime) -> Decimal | None:
    """Harga per kg ``jenis`` yang berlaku pada waktu ``pada``.

    Versi terbaru yang sudah mulai berlaku pada waktu itu (BR-03). Dua versi
    dengan ``berlaku_mulai`` sama diputus oleh yang dibuat terakhir, karena
    koreksi harga terjadwal adalah baris baru. ``None`` berarti belum ada
    harga yang berlaku.

    Harga dikembalikan apa adanya, termasuk sennya. Harga per kg adalah tarif,
    bukan nilai uang yang disimpan, jadi pembulatan ke rupiah penuh dilakukan
    pada subtotal (``shared_kernel.kalkulasi``). Membulatkan tarifnya lebih dulu
    membuang presisi dan membuat transaksi menyimpan harga yang tidak
    benar-benar dipakai (BR-03).
    """
    versi = versi_berlaku(jenis, pada)
    return versi.harga_per_kg if versi else None


def versi_berlaku(jenis: JenisSampah, pada: datetime) -> HargaSampah | None:
    """Versi harga ``jenis`` yang berlaku pada waktu ``pada``."""
    return (
        HargaSampah.objects.filter(jenis_sampah=jenis, berlaku_mulai__lte=pada)
        .order_by("-berlaku_mulai", "-id")
        .first()
    )


def versi_terjadwal(jenis: JenisSampah, pada: datetime) -> HargaSampah | None:
    """Versi harga ``jenis`` berikutnya yang baru berlaku setelah ``pada``."""
    return (
        HargaSampah.objects.filter(jenis_sampah=jenis, berlaku_mulai__gt=pada)
        .order_by("berlaku_mulai", "-id")
        .first()
    )
