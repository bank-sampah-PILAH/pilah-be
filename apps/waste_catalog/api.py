"""Public port of the catalog context."""

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from api.models import BankSampah, HargaSampah, JenisSampah, User


def get_active_jenis(bank: BankSampah, jenis_sampah_id: UUID) -> JenisSampah | None:
    return JenisSampah.objects.filter(id=jenis_sampah_id, bank_sampah=bank, is_active=True).first()


@transaction.atomic
def buat_jenis_sampah(
    bank_sampah: BankSampah,
    *,
    harga_per_kg: Decimal | str | int,
    oleh: User | None = None,
    berlaku_mulai: datetime | None = None,
    **fields: Any,
) -> JenisSampah:
    """Buat jenis sampah beserta versi harga pertamanya dalam satu transaksi."""
    jenis = JenisSampah.objects.create(bank_sampah=bank_sampah, **fields)
    HargaSampah.objects.create(
        jenis_sampah=jenis,
        bank_sampah=bank_sampah,
        harga_per_kg=Decimal(str(harga_per_kg)),
        berlaku_mulai=berlaku_mulai or timezone.now(),
        dibuat_oleh=oleh,
    )
    return jenis


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


def ringkas_harga(
    riwayat: Iterable[HargaSampah], pada: datetime
) -> tuple[HargaSampah | None, HargaSampah | None]:
    """Versi yang berlaku pada ``pada`` dan versi berikutnya yang terjadwal.

    Bekerja atas riwayat yang sudah dimuat (mis. lewat ``prefetch_related``),
    sehingga daftar jenis sampah tidak membutuhkan query per jenis. Aturan
    pemilihannya sama dengan ``harga_berlaku``.
    """
    berlaku: HargaSampah | None = None
    terjadwal: HargaSampah | None = None
    for versi in riwayat:
        if versi.berlaku_mulai <= pada:
            if berlaku is None or (versi.berlaku_mulai, versi.id) > (
                berlaku.berlaku_mulai,
                berlaku.id,
            ):
                berlaku = versi
        elif terjadwal is None or (versi.berlaku_mulai, -versi.id) < (
            terjadwal.berlaku_mulai,
            -terjadwal.id,
        ):
            terjadwal = versi
    return berlaku, terjadwal
