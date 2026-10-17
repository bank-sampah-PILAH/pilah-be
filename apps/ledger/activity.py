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


def activity_sources(
    bank: BankSampah, request: HttpRequest, member: Nasabah | None = None
) -> tuple[QuerySet[Transaksi], QuerySet[Pencairan]]:
    """One authorization/filter policy for history, totals and exports."""
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
    member_id = request.GET.get("nasabah_id")
    if member_id:
        # Intersect with the authorized bank/member scope; never replace it.
        try:
            member_id = serializers.UUIDField().run_validation(member_id)
        except serializers.ValidationError as exc:
            raise serializers.ValidationError({"nasabah_id": exc.detail}) from exc
        deposits = deposits.filter(nasabah_id=member_id)
        payouts = payouts.filter(nasabah_id=member_id)
    search = request.GET.get("search", "").strip()
    if search:
        deposits = deposits.filter(nasabah__nama__icontains=search)
        payouts = payouts.filter(nasabah__nama__icontains=search)
    deposits = TransactionFilterService.apply_period(deposits, request, default=None)
    payouts = TransactionFilterService.apply_period(payouts, request, default=None)
    if kind == "pencairan":
        deposits = deposits.none()
    elif kind == "setoran":
        payouts = payouts.none()
    return deposits, payouts


def activity_query(
    bank: BankSampah, request: HttpRequest, member: Nasabah | None = None
) -> QuerySet[Any]:
    deposits, payouts = activity_sources(bank, request, member)
    kind = request.GET.get("tipe", "semua")
    return activity_rows(deposits, payouts, kind)


def activity_rows(
    deposits: QuerySet[Transaksi], payouts: QuerySet[Pencairan], kind: str
) -> QuerySet[Any]:
    """Build feed rows from already authorized and filtered ledger sources."""
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
