from datetime import datetime
from decimal import Decimal

from api.models import HargaSampah, JenisSampah, User


def catat_harga(
    jenis: JenisSampah, harga_per_kg: Decimal, berlaku_mulai: datetime, oleh: User
) -> HargaSampah:
    """Tambah satu versi harga. Versi lama tidak pernah diubah (SDS 7.1.2)."""
    return HargaSampah.objects.create(
        jenis_sampah=jenis,
        bank_sampah=jenis.bank_sampah,
        harga_per_kg=harga_per_kg,
        berlaku_mulai=berlaku_mulai,
        dibuat_oleh=oleh,
    )
