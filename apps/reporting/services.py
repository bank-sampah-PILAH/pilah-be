from calendar import monthrange
from datetime import datetime, time
from decimal import Decimal
from typing import Any

from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from api.models import DetailTransaksi, Nasabah, Transaksi, User


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
