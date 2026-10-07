"""Filter and page the combined ledger in SQL before fetching detail rows."""

from typing import Any, cast

from django.db.models import CharField, QuerySet, Value
from django.http import HttpRequest
from rest_framework import serializers

from api.models import BankSampah, Nasabah, Pencairan, Transaksi
from apps.ledger.serializers import PencairanDetailSerializer, TransactionListSerializer
from apps.ledger.services import PencairanService, TransactionFilterService

PERIODS = {
    "semua",
    "hari_ini",
    "minggu_ini",
    "bulan_ini",
    "bulan_lalu",
    "1_bulan",
    "3_bulan",
    "6_bulan",
    "12_bulan",
    "custom",
}


def activity_query(
    bank: BankSampah, request: HttpRequest, member: Nasabah | None = None
) -> QuerySet[Any]:
    period = request.GET.get("periode", "semua")
    kind = request.GET.get("tipe", "semua")
    if period not in PERIODS:
        raise serializers.ValidationError({"periode": "Periode tidak valid"})
    if kind not in {"semua", "setoran", "pencairan"}:
        raise serializers.ValidationError({"tipe": "Tipe harus semua, setoran, atau pencairan"})
    deposits = Transaksi.objects.filter(bank_sampah=bank)
    payouts = Pencairan.objects.filter(bank_sampah=bank)
    if member is not None:
        deposits = deposits.filter(nasabah=member)
        payouts = payouts.filter(nasabah=member)
    search = request.GET.get("search", "").strip()
    if search:
        deposits = deposits.filter(nasabah__nama__icontains=search)
        payouts = payouts.filter(nasabah__nama__icontains=search)
    deposits = TransactionFilterService.apply_period(deposits, request, default=None)
    payouts = TransactionFilterService.apply_period(payouts, request, default=None)
    fields = ("id", "tanggal", "created_at", "tipe_aktivitas")
    deposit_rows = (
        deposits.order_by()
        .annotate(tipe_aktivitas=Value("setoran", output_field=CharField()))
        .values(*fields)
    )
    payout_rows = (
        payouts.order_by()
        .annotate(tipe_aktivitas=Value("pencairan", output_field=CharField()))
        .values(*fields)
    )
    if kind == "setoran":
        rows = deposit_rows
    elif kind == "pencairan":
        rows = payout_rows
    else:
        rows = deposit_rows.union(payout_rows, all=True)
    return cast(QuerySet[Any], rows.order_by("-tanggal", "-created_at", "-tipe_aktivitas", "-id"))


def serialize_activity_page(rows: list[dict[str, Any]], bank: BankSampah) -> list[dict[str, Any]]:
    deposit_ids = [row["id"] for row in rows if row["tipe_aktivitas"] == "setoran"]
    payout_ids = [row["id"] for row in rows if row["tipe_aktivitas"] == "pencairan"]
    deposits = (
        Transaksi.objects.filter(bank_sampah=bank, id__in=deposit_ids)
        .select_related("nasabah", "dicatat_oleh")
        .prefetch_related("items")
    )
    payouts = PencairanService.dengan_info_revisi(
        Pencairan.objects.filter(bank_sampah=bank, id__in=payout_ids).select_related(
            "nasabah", "bank_sampah", "dicatat_oleh"
        )
    )
    payloads = {
        ("setoran", str(row["id"])): row
        for row in TransactionListSerializer(deposits, many=True).data
    }
    payloads.update(
        {
            ("pencairan", str(row["id"])): row
            for row in PencairanDetailSerializer(payouts, many=True).data
        }
    )
    return [
        {"tipe": row["tipe_aktivitas"], "data": payloads[(row["tipe_aktivitas"], str(row["id"]))]}
        for row in rows
    ]
