from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from django.db.models import QuerySet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from api.models import BankSampah, Nasabah, Pencairan, Transaksi, User
from apps.ledger.api import activity_query, apply_period
from apps.ledger.serializers import TransactionDetailSerializer
from apps.reporting.api import StatementPeriodError, export_statement_pdf
from shared_kernel.pagination import StandardPagination
from shared_kernel.permissions import IsActiveNasabah


class BankUnitSerializer(serializers.ModelSerializer[BankSampah]):
    class Meta:
        model = BankSampah
        # Explicit public fields: never expose gateway credentials or invite tokens.
        fields = [
            "id",
            "nama",
            "alamat",
            "kota",
            "no_hp_pic",
            "foto_logo",
            "status",
            "jenis_organisasi",
        ]


class ActivitySerializer(serializers.Serializer[Any]):
    """Public history summary shared by deposits and payout projections."""

    id = serializers.UUIDField()
    tanggal = serializers.DateTimeField()
    tipe = serializers.CharField()
    total_nilai = serializers.DecimalField(max_digits=14, decimal_places=2)


class NasabahTransactionDetailSerializer(TransactionDetailSerializer):
    class Meta(TransactionDetailSerializer.Meta):
        fields = [
            "id",
            "tanggal",
            "tipe",
            "total_nilai",
            "catatan",
            "items",
            "saldo_setelah_transaksi",
        ]


class MembershipSerializer(serializers.ModelSerializer[Nasabah]):
    class Meta:
        model = Nasabah
        fields = ["id", "nomor", "status", "is_active"]


class IdentitySerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ["id", "nama", "email", "role"]


class BalanceSerializer(serializers.Serializer[Any]):
    total_saldo = serializers.DecimalField(max_digits=14, decimal_places=2)
    updated_at = serializers.DateTimeField(allow_null=True)


class HomeSerializer(serializers.Serializer[Any]):
    user = IdentitySerializer()
    keanggotaan = MembershipSerializer()
    bank_sampah = BankUnitSerializer()
    saldo = BalanceSerializer()
    aktivitas_terbaru = ActivitySerializer(many=True)


class MembershipService:
    @staticmethod
    def get_active_membership(request: Request) -> Nasabah:
        memberships = Nasabah.objects.filter(user=cast(User, request.user)).select_related(
            "bank_sampah", "saldo"
        )
        identifier = request.query_params.get("keanggotaan_id")
        if identifier is not None:
            return MembershipService._get_selected_membership(memberships, identifier)
        return MembershipService._get_default_membership(memberships)

    @staticmethod
    def _get_selected_membership(memberships: QuerySet[Nasabah], identifier: str) -> Nasabah:
        try:
            member_id = UUID(identifier)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError({"keanggotaan_id": "UUID tidak valid."}) from exc
        selected = memberships.filter(pk=member_id)
        member = MembershipService._eligible_memberships(selected).first()
        if member is not None:
            return member
        if selected.exists():
            raise PermissionDenied("Keanggotaan dan bank sampah harus aktif.")
        raise NotFound()

    @staticmethod
    def _eligible_memberships(memberships: QuerySet[Nasabah]) -> QuerySet[Nasabah]:
        return memberships.filter(
            status=Nasabah.Status.APPROVED,
            is_active=True,
            bank_sampah__is_active=True,
            bank_sampah__status=BankSampah.Status.ACTIVE,
        )

    @staticmethod
    def _get_default_membership(memberships: QuerySet[Nasabah]) -> Nasabah:
        eligible = list(MembershipService._eligible_memberships(memberships))
        if not eligible:
            raise PermissionDenied("Keanggotaan aktif diperlukan.")
        if len(eligible) > 1:
            raise ValidationError(
                {
                    "keanggotaan_id": "Pilih keanggotaan untuk melihat beranda.",
                    "pilihan": [
                        {"id": str(member.id), "bank_sampah_nama": member.bank_sampah.nama}
                        for member in eligible
                    ],
                }
            )
        return eligible[0]


def balance_data(member: Nasabah) -> dict[str, Any]:
    balance = getattr(member, "saldo", None)
    return {
        "total_saldo": balance.total_saldo if balance else Decimal("0.00"),
        "updated_at": balance.updated_at if balance else None,
    }


def activities(member: Nasabah) -> QuerySet[Transaksi]:
    return Transaksi.objects.filter(nasabah=member, bank_sampah=member.bank_sampah).order_by(
        "-tanggal", "-created_at", "-id"
    )


class NasabahHomeView(GenericAPIView[Nasabah]):
    permission_classes = [IsActiveNasabah]
    serializer_class = HomeSerializer

    def get(self, request: Request) -> Response:
        member = MembershipService.get_active_membership(request)
        return Response(
            self.get_serializer(
                {
                    "user": request.user,
                    "keanggotaan": member,
                    "bank_sampah": member.bank_sampah,
                    "saldo": balance_data(member),
                    "aktivitas_terbaru": activities(member)[:5],
                }
            ).data
        )


class NasabahBalanceView(GenericAPIView[Nasabah]):
    permission_classes = [IsActiveNasabah]
    serializer_class = BalanceSerializer

    def get(self, request: Request) -> Response:
        return Response(
            self.get_serializer(balance_data(MembershipService.get_active_membership(request))).data
        )


class NasabahBankView(GenericAPIView[BankSampah]):
    permission_classes = [IsActiveNasabah]
    serializer_class = BankUnitSerializer

    def get(self, request: Request) -> Response:
        return Response(
            self.get_serializer(MembershipService.get_active_membership(request).bank_sampah).data
        )


class NasabahHistoryView(ListAPIView[Transaksi]):
    permission_classes = [IsActiveNasabah]
    serializer_class = ActivitySerializer
    pagination_class = StandardPagination

    # periode filter (PIL-315): omitted param = all-time history (default=None).
    # Overriding list (not get_queryset) because a custom range with reversed
    # dates raises ValueError, which must surface as the ledger-style 400 —
    # get_queryset can only raise, not return a Response. The queryset runs
    # through apply_period exactly once (here).
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if "tipe" in request.query_params:
            member = MembershipService.get_active_membership(request)
            try:
                rows = activity_query(member.bank_sampah, request, member)
            except ValueError as exc:
                return Response({"error": str(exc)}, status=400)
            page = self.paginate_queryset(rows)
            assert page is not None  # StandardPagination is always enabled.
            # Preserve the nasabah list DTO and never expose staff-only fields.
            payloads = []
            deposits = {
                obj.id: obj
                for obj in Transaksi.objects.filter(
                    nasabah=member,
                    id__in=[row["id"] for row in page if row["tipe_aktivitas"] == "setoran"],
                )
            }
            payouts = {
                obj.id: obj
                for obj in Pencairan.objects.filter(
                    nasabah=member,
                    id__in=[row["id"] for row in page if row["tipe_aktivitas"] == "pencairan"],
                )
            }
            for row in page:
                value = (
                    deposits[row["id"]].total_nilai
                    if row["tipe_aktivitas"] == "setoran"
                    else payouts[row["id"]].nominal
                )
                payloads.append(
                    {
                        "id": row["id"],
                        "tanggal": row["tanggal"],
                        "tipe": row["tipe_aktivitas"],
                        "total_nilai": value,
                    }
                )
            return self.get_paginated_response(self.get_serializer(payloads, many=True).data)
        try:
            queryset = apply_period(
                activities(MembershipService.get_active_membership(request)),
                request,
                default=None,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page or queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class NasabahHistoryExportPdfView(GenericAPIView[Nasabah]):
    """Riwayat aktivitas statement PDF (PIL-315).

    Same isolation contract as every nasabah-me endpoint: the statement is
    scoped to the active membership resolved by MembershipService, so a
    nasabah only ever exports their own rows for their own bank sampah.
    """

    permission_classes = [IsActiveNasabah]
    # The statement render is CPU-heavy (minutes of history → one PDF); the
    # scoped throttle is read from DEFAULT_THROTTLE_RATES["statement_pdf"].
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "statement_pdf"

    def get(self, request: Request) -> HttpResponse:
        member = MembershipService.get_active_membership(request)
        try:
            result = export_statement_pdf(member, request)
        # StatementPeriodError means the periode/tipe request is unservable
        # (unknown month window, reversed range, oversized window) and maps
        # to the same 400 shape the ledger views return. Anything else —
        # including a ValueError escaping the renderer — must NOT be echoed
        # back as a 400; it falls through to the framework's 500 path.
        except StatementPeriodError as exc:
            return Response({"error": str(exc)}, status=400)
        if result is None:
            return Response({"error": "Tidak ada data pada periode ini"}, status=400)
        content, filename = result
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class NasabahTransactionDetailView(GenericAPIView[Transaksi]):
    permission_classes = [IsActiveNasabah]
    serializer_class = NasabahTransactionDetailSerializer  # type: ignore[assignment]  # DRF stubs type serializer_class too narrowly

    def get(self, request: Request, pk: UUID) -> Response:
        member = MembershipService.get_active_membership(request)
        transaction = get_object_or_404(
            activities(member).select_related("nasabah", "bank_sampah").prefetch_related("items"),
            pk=pk,
        )
        return Response(self.get_serializer(transaction).data)
