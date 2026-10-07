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
    """
    versi = (
        HargaSampah.objects.filter(jenis_sampah=jenis, berlaku_mulai__lte=pada)
        .order_by("-berlaku_mulai", "-id")
        .first()
    )
    return versi.harga_per_kg if versi else None
