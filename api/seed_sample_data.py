"""Sample data both reviewer seeders put into a bank.

``seed_play_demo_accounts`` (production) and ``seed_staging_review_account``
(staging) build the same minimal, reviewable catalog, setoran history, schedules
and saldo here, each with its own fixed IDs so the two never collide with each
other or with the E2E fixture.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from django.core.management.base import CommandError
from django.db.models import F, Sum
from django.utils import timezone

from api.models import (
    BankSampah,
    DetailTransaksi,
    HargaSampah,
    JadwalKegiatan,
    JenisSampah,
    Nasabah,
    Pencairan,
    Saldo,
    Transaksi,
    User,
)
from apps.waste_catalog.api import harga_berlaku
from apps.waste_catalog.services import catat_harga
from shared_kernel.kalkulasi import hitung_subtotal, total_setoran

SEED_HARGA_SEJAK_HARI = 400
PriceFn = Callable[[JenisSampah, datetime], Decimal]


@dataclass(frozen=True)
class SampleIds:
    waste_types: tuple[UUID, ...]
    transactions: tuple[UUID, ...]
    details: tuple[UUID, ...]
    schedules: tuple[UUID, ...]


WASTE_TYPE_FIXTURES = (
    (
        "JS-0001",
        "Plastik PET",
        JenisSampah.Kategori.PLASTIK,
        "Botol plastik bening",
        Decimal("3500.00"),
    ),
    (
        "JS-0002",
        "Kardus",
        JenisSampah.Kategori.KERTAS,
        "Kardus dan kertas tebal",
        Decimal("2000.00"),
    ),
    ("JS-0003", "Botol Kaca", JenisSampah.Kategori.KACA, "Botol kaca bersih", Decimal("1000.00")),
    (
        "JS-0004",
        "Kaleng Aluminium",
        JenisSampah.Kategori.LOGAM,
        "Kaleng aluminium",
        Decimal("5000.00"),
    ),
)


def seed_price(jenis: JenisSampah, pada: datetime) -> Decimal:
    price = harga_berlaku(jenis, pada)
    if price is None:
        raise CommandError(f"Seeded waste type {jenis.pk} has no active price")
    return price


def ensure_waste_types(bank: BankSampah, ids: SampleIds) -> dict[str, JenisSampah]:
    result = {}
    for type_id, fixture in zip(ids.waste_types, WASTE_TYPE_FIXTURES, strict=True):
        number, name, category, description, price = fixture
        jenis, _ = JenisSampah.objects.update_or_create(
            pk=type_id,
            defaults={
                "bank_sampah": bank,
                "nomor": number,
                "nama_sampah": name,
                "kategori": category,
                "deskripsi": description,
                "is_active": True,
            },
        )
        if not HargaSampah.objects.filter(jenis_sampah=jenis).exists():
            catat_harga(
                jenis,
                price,
                timezone.now() - timedelta(days=SEED_HARGA_SEJAK_HARI),
                oleh=None,
            )
        result[name] = jenis
    return result


def ensure_transactions(
    bank: BankSampah,
    pengurus: User,
    membership: Nasabah,
    waste_types: dict[str, JenisSampah],
    ids: SampleIds,
    price_fn: PriceFn | None = None,
) -> None:
    price_of = price_fn or seed_price
    now = timezone.now()
    fixtures = (
        (
            ids.transactions[0],
            (ids.details[0], ids.details[1]),
            now - timedelta(days=3),
            "Setoran demo PET dan Kardus",
            (("Plastik PET", Decimal("2.500")), ("Kardus", Decimal("1.000"))),
        ),
        (
            ids.transactions[1],
            (ids.details[2],),
            now - timedelta(days=1),
            "Setoran demo Botol Kaca",
            (("Botol Kaca", Decimal("3.000")),),
        ),
        (
            ids.transactions[2],
            (ids.details[3],),
            now - timedelta(hours=4),
            "Setoran demo Kaleng Aluminium",
            (("Kaleng Aluminium", Decimal("1.500")),),
        ),
    )
    for transaction_id, detail_ids, date, note, items in fixtures:
        priced_items = tuple((waste_types[name], weight) for name, weight in items)
        transaction_date = (
            Transaksi.objects.filter(pk=transaction_id).values_list("tanggal", flat=True).first()
            or date
        )
        prices = tuple(price_of(jenis, transaction_date) for jenis, _weight in priced_items)
        subtotals = tuple(
            hitung_subtotal(price, weight)
            for price, (_jenis, weight) in zip(prices, priced_items, strict=True)
        )
        total = total_setoran(subtotals)
        transaksi, created = Transaksi.objects.get_or_create(
            pk=transaction_id,
            defaults={
                "nasabah": membership,
                "bank_sampah": bank,
                "dicatat_oleh": pengurus,
                "tanggal": date,
                "total_nilai": total,
                "tipe": Transaksi.Tipe.SETORAN,
                "catatan": note,
            },
        )
        if not created:
            transaksi.nasabah = membership
            transaksi.bank_sampah = bank
            transaksi.dicatat_oleh = pengurus
            transaksi.total_nilai = total
            transaksi.tipe = Transaksi.Tipe.SETORAN
            transaksi.catatan = note
            transaksi.save(
                update_fields=[
                    "nasabah",
                    "bank_sampah",
                    "dicatat_oleh",
                    "total_nilai",
                    "tipe",
                    "catatan",
                    "updated_at",
                ]
            )
        for detail_id, (jenis, weight), price, subtotal in zip(
            detail_ids, priced_items, prices, subtotals, strict=True
        ):
            DetailTransaksi.objects.update_or_create(
                pk=detail_id,
                defaults={
                    "transaksi": transaksi,
                    "jenis_sampah": jenis,
                    "nama_sampah_snapshot": jenis.nama_sampah,
                    "kategori_snapshot": jenis.kategori,
                    "harga_snapshot": price,
                    "berat": weight,
                    "subtotal": subtotal,
                },
            )


def ensure_schedules(bank: BankSampah, pengurus: User, ids: SampleIds, lokasi: str) -> None:
    today = timezone.localdate()
    fixtures = (
        (ids.schedules[0], JadwalKegiatan.JenisKegiatan.PENIMBANGAN, 7),
        (ids.schedules[1], JadwalKegiatan.JenisKegiatan.PENCAIRAN, 14),
    )
    tz = timezone.get_current_timezone()
    for schedule_id, activity, days in fixtures:
        date = today + timedelta(days=days)
        starts_at = timezone.make_aware(datetime.combine(date, time(9, 0)), tz)
        ends_at = timezone.make_aware(datetime.combine(date, time(11, 0)), tz)
        JadwalKegiatan.objects.update_or_create(
            pk=schedule_id,
            defaults={
                "bank_sampah": bank,
                "dibuat_oleh": pengurus,
                "jenis_kegiatan": activity,
                "mulai_pada": starts_at,
                "selesai_pada": ends_at,
                "lokasi": lokasi,
                "keterangan": "Jadwal sintetis untuk akun review PILAH",
                "cakupan_penerima": JadwalKegiatan.CakupanPenerima.SEMUA_NASABAH,
                "status": JadwalKegiatan.Status.DITERBITKAN,
            },
        )


def recalculate_balance(membership: Nasabah) -> None:
    # A voided setoran stays in the table but not in the saldo (PIL-428).
    setoran = Transaksi.objects.tercatat().filter(
        nasabah=membership, tipe=Transaksi.Tipe.SETORAN
    ).aggregate(total=Sum("total_nilai"))["total"] or Decimal("0.00")
    pencairan = Pencairan.objects.filter(nasabah=membership).aggregate(
        total=Sum(F("saldo_sebelum") - F("saldo_sesudah"))
    )["total"] or Decimal("0.00")
    saldo, _ = Saldo.objects.get_or_create(
        nasabah=membership, defaults={"total_saldo": Decimal("0.00")}
    )
    total_saldo = setoran - pencairan
    if saldo.total_saldo != total_saldo:
        saldo.total_saldo = total_saldo
        saldo.save(update_fields=["total_saldo", "updated_at"])
