from decimal import Decimal
from typing import Any

from django.db.models import Model, Q, Sum
from django.db.models.functions import Coalesce
from rest_framework import serializers

from api.models import (
    DetailTransaksi,
    Transaksi,
)

# ponytail: compat shims — canonical homes are apps.*.serializers.
from apps.catalog.serializers import JenisSampahSerializer  # noqa: F401
from apps.identity.serializers import (  # noqa: F401
    AuthUserSerializer,
    GoogleAuthSerializer,
    InviteAcceptSerializer,
    LogoutSerializer,
    RefreshTokenSerializer,
    TeamMemberSerializer,
    UserProfileSerializer,
)
from apps.ledger.serializers import TransactionListSerializer  # noqa: F401
from apps.membership.serializers import (  # noqa: F401
    NasabahApprovalLogSerializer,
    NasabahDetailSerializer,
    NasabahSerializer,
    SaldoSerializer,
    StatusSerializer,
)
from apps.notify.serializers import WATemplateSerializer  # noqa: F401
from apps.organization.serializers import (  # noqa: F401
    ApprovalDecisionSerializer,
    ApprovalLogSerializer,
    BankSampahApprovalListSerializer,
    BankSampahRegistrationSerializer,
    BankSampahSerializer,
)


class TransactionItemInputSerializer(serializers.Serializer[Any]):
    jenis_sampah_id = serializers.UUIDField(required=True)
    berat = serializers.DecimalField(max_digits=10, decimal_places=3, min_value=Decimal("0.001"))
    harga_per_kg = serializers.DecimalField(
        max_digits=11, decimal_places=2, min_value=Decimal("0.01"), required=False
    )


class TransactionCreateSerializer(serializers.Serializer[Any]):
    nasabah_id = serializers.UUIDField(required=True)
    items = TransactionItemInputSerializer(many=True, required=True)
    catatan = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_items(self, value: Any) -> Any:
        if not value:
            raise serializers.ValidationError("Minimal 1 item setoran diperlukan")
        return value


class DetailTransaksiSerializer(serializers.ModelSerializer[Model]):
    jenis_sampah_id = serializers.UUIDField(source="jenis_sampah.id")

    class Meta:
        model = DetailTransaksi
        fields = [
            "id",
            "jenis_sampah_id",
            "nama_sampah_snapshot",
            "harga_snapshot",
            "berat",
            "subtotal",
        ]


class TransactionDetailSerializer(serializers.ModelSerializer[Model]):
    nasabah_id = serializers.UUIDField(source="nasabah.id")
    nasabah_nama = serializers.CharField(source="nasabah.nama")
    bank_sampah_id = serializers.UUIDField(source="bank_sampah.id")
    dicatat_oleh = serializers.UUIDField(source="dicatat_oleh.id")
    items = DetailTransaksiSerializer(many=True)
    saldo_setelah_transaksi = serializers.SerializerMethodField()

    class Meta:
        model = Transaksi
        fields = [
            "id",
            "nasabah_id",
            "nasabah_nama",
            "bank_sampah_id",
            "dicatat_oleh",
            "tanggal",
            "total_nilai",
            "catatan",
            "status_wa",
            "items",
            "saldo_setelah_transaksi",
        ]

    def get_saldo_setelah_transaksi(self, obj: Any) -> Any:
        return (
            Transaksi.objects.filter(bank_sampah=obj.bank_sampah, nasabah=obj.nasabah)
            .filter(Q(tanggal__lt=obj.tanggal) | Q(tanggal=obj.tanggal, id__lte=obj.id))
            .aggregate(total=Coalesce(Sum("total_nilai"), Decimal("0.00")))["total"]
        )
