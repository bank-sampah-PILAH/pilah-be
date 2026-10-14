"""Filtered operational totals; amounts are full Rupiah, weight remains decimal."""

from typing import TypedDict

from django.db.models import QuerySet, Sum
from django.http import HttpRequest

from api.models import BankSampah, DetailTransaksi, Pencairan, Transaksi
from apps.ledger.api import activity_sources
from shared_kernel.kalkulasi import bulatkan_rupiah


class OperationalSummary(TypedDict):
    jumlah_transaksi: int
    total_berat: str
    total_setoran: int
    total_pencairan: int
    saldo: int


def operational_queries(
    bank: BankSampah, request: HttpRequest
) -> tuple[QuerySet[Transaksi], QuerySet[Pencairan]]:
    return activity_sources(bank, request)


def operational_summary(
    deposits: QuerySet[Transaksi], payouts: QuerySet[Pencairan]
) -> OperationalSummary:
    # Per-event truncation preserves legacy full-Rupiah display rules.
    total_setoran = sum(
        int(bulatkan_rupiah(value))
        for value in deposits.values_list("total_nilai", flat=True).iterator()
    )
    total_pencairan = sum(
        int(bulatkan_rupiah(value))
        for value in payouts.values_list("nominal", flat=True).iterator()
    )
    weight = DetailTransaksi.objects.filter(transaksi__in=deposits).aggregate(total=Sum("berat"))[
        "total"
    ]
    return {
        "jumlah_transaksi": deposits.count() + payouts.count(),
        "total_berat": f"{weight or 0:.3f}",
        "total_setoran": total_setoran,
        "total_pencairan": total_pencairan,
        "saldo": total_setoran - total_pencairan,
    }
