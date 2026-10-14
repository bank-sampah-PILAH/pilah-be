"""Filtered operational totals; amounts are full Rupiah, weight remains decimal."""

from typing import TypedDict

from django.db.models import QuerySet, Sum
from django.http import HttpRequest

from api.models import BankSampah, DetailTransaksi, Pencairan, Transaksi
from apps.ledger.api import activity_query


class OperationalSummary(TypedDict):
    jumlah_transaksi: int
    total_berat: str
    total_setoran: int
    total_pencairan: int
    saldo: int


def operational_queries(
    bank: BankSampah, request: HttpRequest
) -> tuple[QuerySet[Transaksi], QuerySet[Pencairan]]:
    rows = list(activity_query(bank, request))
    deposits = Transaksi.objects.filter(
        bank_sampah=bank,
        id__in=[row["id"] for row in rows if row["tipe_aktivitas"] == "setoran"],
    )
    payouts = Pencairan.objects.filter(
        bank_sampah=bank,
        id__in=[row["id"] for row in rows if row["tipe_aktivitas"] == "pencairan"],
    )
    return deposits, payouts


def operational_summary(
    deposits: QuerySet[Transaksi], payouts: QuerySet[Pencairan]
) -> OperationalSummary:
    # Per-event truncation preserves legacy full-Rupiah display rules.
    total_setoran = sum(int(value) for value in deposits.values_list("total_nilai", flat=True))
    total_pencairan = sum(int(value) for value in payouts.values_list("nominal", flat=True))
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
