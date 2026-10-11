from calendar import monthrange
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, Sum
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek
from django.utils import timezone

from api.models import DetailTransaksi, Nasabah, Pencairan, Transaksi, User


class DashboardService:
    @staticmethod
    def stats(user: User) -> dict[str, Any]:
        bank = user.bank_sampah
        assert bank is not None  # ponytail: views gate on IsActivePengelola
        today = timezone.localdate()
        start = today.replace(day=1)
        end = today.replace(day=monthrange(today.year, today.month)[1])
        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime.combine(start, time.min), tz)
        end_dt = timezone.make_aware(datetime.combine(end, time.max), tz)

        transaksi = Transaksi.objects.filter(bank_sampah=bank, tanggal__range=(start_dt, end_dt))
        totals = DetailTransaksi.objects.filter(transaksi__in=transaksi).aggregate(
            total_kg=Coalesce(Sum("berat"), Decimal(0)),
        )
        nilai = transaksi.aggregate(total=Coalesce(Sum("total_nilai"), Decimal(0)))["total"]
        return {
            "bank_sampah_nama": bank.nama,
            "pengelola_nama": user.nama,
            "periode": today.strftime("%Y-%m"),
            "nasabah_aktif": Nasabah.objects.filter(
                bank_sampah=bank, is_active=True, status=Nasabah.Status.APPROVED
            ).count(),
            "transaksi_bulan_ini": transaksi.count(),
            "total_sampah_kg_bulan_ini": totals["total_kg"],
            "total_nilai_bulan_ini": nilai,
        }

    @staticmethod
    def operational_trends(
        user: User, start: date, end: date, granularity: str
    ) -> dict[str, Any]:
        bank = user.bank_sampah
        assert bank is not None  # ponytail: views gate on IsActivePengelola
        truncation = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}[granularity]
        buckets: dict[date, dict[str, Any]] = {}
        period = _period_start(start, granularity)
        while period <= end:
            buckets[period] = {
                "period_start": period.isoformat(),
                "setoran_total_nilai": "0.00",
                "setoran_count": 0,
                "pencairan_total_nominal": "0.00",
                "pencairan_count": 0,
            }
            period = _next_period(period, granularity)

        start_dt, end_dt = _date_bounds(start, end)
        setoran = (
            Transaksi.objects.filter(
                bank_sampah=bank,
                tipe=Transaksi.Tipe.SETORAN,
                tanggal__range=(start_dt, end_dt),
            )
            .annotate(period=truncation("tanggal", tzinfo=timezone.get_current_timezone()))
            .values("period")
            .annotate(total=Coalesce(Sum("total_nilai"), Decimal(0)), count=Count("id"))
        )
        pencairan = (
            Pencairan.objects.filter(bank_sampah=bank, tanggal__range=(start_dt, end_dt))
            .annotate(period=truncation("tanggal", tzinfo=timezone.get_current_timezone()))
            .values("period")
            .annotate(total=Coalesce(Sum("nominal"), Decimal(0)), count=Count("id"))
        )
        for row in setoran:
            bucket = buckets.get(row["period"].date())
            if bucket is not None:
                bucket["setoran_total_nilai"] = f'{row["total"]:.2f}'
                bucket["setoran_count"] = row["count"]
        for row in pencairan:
            bucket = buckets.get(row["period"].date())
            if bucket is not None:
                bucket["pencairan_total_nominal"] = f'{row["total"]:.2f}'
                bucket["pencairan_count"] = row["count"]
        return {"granularity": granularity, "buckets": list(buckets.values())}

    @staticmethod
    def waste_categories(user: User, start: date, end: date) -> dict[str, Any]:
        bank = user.bank_sampah
        assert bank is not None  # ponytail: views gate on IsActivePengelola
        start_dt, end_dt = _date_bounds(start, end)
        categories = (
            DetailTransaksi.objects.filter(
                transaksi__bank_sampah=bank,
                transaksi__tipe=Transaksi.Tipe.SETORAN,
                transaksi__tanggal__range=(start_dt, end_dt),
            )
            .values("kategori_snapshot")
            .annotate(
                total_weight_kg=Coalesce(Sum("berat"), Decimal(0)),
                deposit_count=Count("transaksi_id", distinct=True),
            )
            .order_by("-total_weight_kg", "kategori_snapshot")
        )
        return {
            "categories": [
                {
                    "category": row["kategori_snapshot"],
                    "total_weight_kg": row["total_weight_kg"],
                    "deposit_count": row["deposit_count"],
                }
                for row in categories
            ]
        }


def _date_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    tz = timezone.get_current_timezone()
    return (
        timezone.make_aware(datetime.combine(start, time.min), tz),
        timezone.make_aware(datetime.combine(end, time.max), tz),
    )


def _period_start(day: date, granularity: str) -> date:
    if granularity == "week":
        return day - timedelta(days=day.weekday())
    if granularity == "month":
        return day.replace(day=1)
    return day


def _next_period(period: date, granularity: str) -> date:
    if granularity == "week":
        return period + timedelta(days=7)
    if granularity == "month":
        return (period.replace(day=monthrange(period.year, period.month)[1]) + timedelta(days=1))
    return period + timedelta(days=1)
