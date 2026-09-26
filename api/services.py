from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone
from rest_framework import serializers

from api.models import (
    DetailTransaksi,
    JenisSampah,
    Nasabah,
    Saldo,
    Transaksi,
    User,
)

# ponytail: compat shims — canonical homes are apps.identity.services,
# apps.membership.services, apps.notify.services, apps.reporting.services,
# apps.reporting.exporter and shared_kernel.numbering.
from apps.identity.services import (  # noqa: F401
    AuthService,
    OnboardingService,
    TeamService,
)
from apps.membership.services import NasabahApprovalService  # noqa: F401
from apps.notify.services import (  # noqa: F401
    DEFAULT_WA_TEMPLATE,
    WhatsAppService,
)
from apps.organization.services import ApprovalService  # noqa: F401
from apps.reporting import exporter
from apps.reporting.services import DashboardService  # noqa: F401
from shared_kernel.numbering import NumberingService  # noqa: F401

__all__ = [
    "ApprovalService",
    "AuthService",
    "DEFAULT_WA_TEMPLATE",
    "DashboardService",
    "NasabahApprovalService",
    "NumberingService",
    "OnboardingService",
    "TeamService",
    "TransactionFilterService",
    "TransactionService",
    "WhatsAppService",
]


class TransactionService:
    @staticmethod
    @transaction.atomic
    def create_setoran(user: User, payload: Mapping[str, Any]) -> Transaksi:
        bank = user.bank_sampah
        assert bank is not None  # ponytail: views gate on IsActivePengelola
        nasabah = (
            Nasabah.objects.select_for_update()
            .filter(
                id=payload["nasabah_id"],
                bank_sampah=bank,
                is_active=True,
                status=Nasabah.Status.APPROVED,
            )
            .first()
        )
        if not nasabah:
            raise serializers.ValidationError(
                {"nasabah_id": ["Nasabah tidak ditemukan atau tidak aktif"]}
            )

        saldo, _ = Saldo.objects.select_for_update().get_or_create(nasabah=nasabah)
        transaksi = Transaksi.objects.create(
            nasabah=nasabah,
            bank_sampah=bank,
            dicatat_oleh=user,
            catatan=payload.get("catatan") or None,
        )

        total_nilai = Decimal("0.00")
        for index, item_payload in enumerate(payload["items"]):
            jenis = JenisSampah.objects.filter(
                id=item_payload["jenis_sampah_id"], bank_sampah=bank, is_active=True
            ).first()
            if not jenis:
                raise serializers.ValidationError(
                    {
                        f"items[{index}].jenis_sampah_id": [
                            "Jenis sampah tidak ditemukan atau tidak aktif"
                        ]
                    }
                )
            harga = item_payload.get("harga_per_kg") or jenis.harga_per_kg
            berat = item_payload["berat"]
            subtotal = (harga * berat).quantize(Decimal("0.01"))
            DetailTransaksi.objects.create(
                transaksi=transaksi,
                jenis_sampah=jenis,
                nama_sampah_snapshot=jenis.nama_sampah,
                kategori_snapshot=jenis.kategori,
                harga_snapshot=harga,
                berat=berat,
                subtotal=subtotal,
            )
            total_nilai += subtotal

        transaksi.total_nilai = total_nilai
        transaksi.save(update_fields=["total_nilai"])
        saldo.total_saldo += total_nilai
        saldo.save(update_fields=["total_saldo", "updated_at"])
        return transaksi

    @staticmethod
    def export_excel(
        queryset: QuerySet[Transaksi], request: HttpRequest | None = None
    ) -> tuple[bytes, str]:
        return exporter.export_excel(queryset, request)


class TransactionFilterService:
    @staticmethod
    def apply_period(queryset: QuerySet[Transaksi], request: HttpRequest) -> QuerySet[Transaksi]:
        periode = request.GET.get("periode", "hari_ini")
        today = timezone.localdate()
        if periode == "hari_ini":
            start, end = today, today
        elif periode == "minggu_ini":
            start, end = today - timedelta(days=today.weekday()), today
        elif periode == "bulan_ini":
            start, end = today.replace(day=1), today
        elif periode == "bulan_lalu":
            first_this_month = today.replace(day=1)
            last_previous_month = first_this_month - timedelta(days=1)
            start = last_previous_month.replace(day=1)
            end = last_previous_month
        elif periode == "custom":
            parsed_start = TransactionFilterService._parse_date(request.GET.get("dari_tanggal"))
            parsed_end = TransactionFilterService._parse_date(request.GET.get("sampai_tanggal"))
            if not parsed_start or not parsed_end:
                raise serializers.ValidationError(
                    {"error": "dari_tanggal dan sampai_tanggal wajib diisi"}
                )
            if parsed_end < parsed_start:
                raise ValueError("Tanggal akhir tidak boleh lebih awal dari tanggal awal")
            start, end = parsed_start, parsed_end
        else:
            return queryset

        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime.combine(start, time.min), tz)
        end_dt = timezone.make_aware(datetime.combine(end, time.max), tz)
        return queryset.filter(tanggal__range=(start_dt, end_dt))

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise serializers.ValidationError({"error": "Format tanggal harus YYYY-MM-DD"}) from exc
