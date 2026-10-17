"""Filtered operational totals; amounts are full Rupiah, weight remains decimal."""

from typing import TypedDict

from django.db.models import Count, QuerySet, Sum
from django.http import HttpRequest

from api.models import BankSampah, DetailTransaksi, Pencairan, Transaksi
from apps.ledger.api import activity_sources
from apps.reporting.money import sum_full_rupiah


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
    # Each ledger returns one row regardless of history size. Round per event,
    # not after summing, to preserve legacy full-Rupiah display rules.
    deposit_totals = deposits.aggregate(count=Count("id"), total=sum_full_rupiah("total_nilai"))
    payout_totals = payouts.aggregate(count=Count("id"), total=sum_full_rupiah("nominal"))
    total_setoran = int(deposit_totals["total"] or 0)
    total_pencairan = int(payout_totals["total"] or 0)
    weight = DetailTransaksi.objects.filter(transaksi__in=deposits).aggregate(total=Sum("berat"))[
        "total"
    ]
    return {
        "jumlah_transaksi": deposit_totals["count"] + payout_totals["count"],
        "total_berat": f"{weight or 0:.3f}",
        "total_setoran": total_setoran,
        "total_pencairan": total_pencairan,
        "saldo": total_setoran - total_pencairan,
    }
