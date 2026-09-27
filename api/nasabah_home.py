from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from django.db.models import QuerySet
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response

from api.models import BankSampah, Nasabah, Transaksi, User
from api.pagination import StandardPagination
from api.permissions import IsActiveNasabah


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


class ActivitySerializer(serializers.ModelSerializer[Transaksi]):
    class Meta:
        model = Transaksi
        fields = ["id", "tanggal", "tipe", "total_nilai"]


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

    def get_queryset(self) -> QuerySet[Transaksi]:
        return activities(MembershipService.get_active_membership(self.request))
