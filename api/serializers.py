from decimal import Decimal
from typing import Any

from django.db.models import Model, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import serializers

from api.models import (
    DetailTransaksi,
    JenisSampah,
    Nasabah,
    NasabahApprovalLog,
    Saldo,
    Transaksi,
)
from api.validators import normalize_indonesian_phone

# ponytail: compat shims — canonical homes are apps.*.serializers.
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
from apps.notify.serializers import WATemplateSerializer  # noqa: F401
from apps.organization.serializers import (  # noqa: F401
    ApprovalDecisionSerializer,
    ApprovalLogSerializer,
    BankSampahApprovalListSerializer,
    BankSampahRegistrationSerializer,
    BankSampahSerializer,
)

__all__ = [
    "ApprovalDecisionSerializer",
    "ApprovalLogSerializer",
    "AuthUserSerializer",
    "BankSampahApprovalListSerializer",
    "BankSampahRegistrationSerializer",
    "BankSampahSerializer",
    "GoogleAuthSerializer",
    "InviteAcceptSerializer",
    "LogoutSerializer",
    "RefreshTokenSerializer",
    "TeamMemberSerializer",
    "TransactionListSerializer",
    "UserProfileSerializer",
    "WATemplateSerializer",
]


class NasabahApprovalLogSerializer(serializers.ModelSerializer[Model]):
    pengurus_email = serializers.EmailField(source="pengurus.email")

    class Meta:
        model = NasabahApprovalLog
        fields = ["id", "nasabah_id", "pengurus_email", "status", "catatan", "created_at"]


class NasabahSerializer(serializers.ModelSerializer[Model]):
    kode = serializers.CharField(source="nomor", required=True, max_length=20)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    total_saldo = serializers.SerializerMethodField()

    class Meta:
        model = Nasabah
        fields = [
            "id",
            "kode",
            "email",
            "nama",
            "jenis_kelamin",
            "tanggal_lahir",
            "no_hp",
            "alamat",
            "tanggal_daftar",
            "is_active",
            "status",
            "total_saldo",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "tanggal_daftar",
            "is_active",
            "status",
            "total_saldo",
            "created_at",
        ]

    def validate_email(self, value: Any) -> Any:
        if value is None:
            return None
        value = value.strip().lower()
        return value or None

    def validate_kode(self, value: Any) -> Any:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("ID Nasabah wajib diisi")
        return value

    def validate_nama(self, value: Any) -> Any:
        value = value.strip()
        if not 3 <= len(value) <= 100:
            raise serializers.ValidationError("Nama minimal 3 karakter")
        return value

    def validate_no_hp(self, value: Any) -> Any:
        return normalize_indonesian_phone(value)

    def validate_jenis_kelamin(self, value: Any) -> Any:
        if value not in [Nasabah.Gender.MALE, Nasabah.Gender.FEMALE]:
            raise serializers.ValidationError("Jenis kelamin wajib dipilih")
        return value

    def validate_tanggal_lahir(self, value: Any) -> Any:
        if value > timezone.localdate():
            raise serializers.ValidationError("Tanggal lahir tidak boleh di masa depan")
        return value

    def validate_alamat(self, value: Any) -> Any:
        value = value.strip()
        if len(value) < 10:
            raise serializers.ValidationError("Alamat wajib diisi")
        return value

    def get_total_saldo(self, obj: Any) -> Any:
        return getattr(getattr(obj, "saldo", None), "total_saldo", Decimal("0.00"))


class NasabahDetailSerializer(NasabahSerializer):
    ringkasan_transaksi = serializers.SerializerMethodField()

    class Meta(NasabahSerializer.Meta):
        fields = NasabahSerializer.Meta.fields + ["ringkasan_transaksi"]

    def get_ringkasan_transaksi(self, obj: Any) -> Any:
        items = DetailTransaksi.objects.filter(transaksi__nasabah=obj)
        total_kg = sum((item.berat for item in items), Decimal(0))
        last_transaction = obj.transaksi.order_by("-tanggal").first()
        return {
            "jumlah_transaksi": obj.transaksi.count(),
            "total_kg": total_kg,
            "tanggal_transaksi_terakhir": last_transaction.tanggal if last_transaction else None,
        }


class StatusSerializer(serializers.Serializer[Any]):
    is_active = serializers.BooleanField(required=True)


class JenisSampahSerializer(serializers.ModelSerializer[Model]):
    satuan = serializers.SerializerMethodField()
    kode = serializers.CharField(source="nomor", required=True, max_length=20)

    class Meta:
        model = JenisSampah
        fields = [
            "id",
            "kode",
            "nama_sampah",
            "kategori",
            "deskripsi",
            "satuan",
            "harga_per_kg",
            "is_active",
            "updated_at",
        ]
        read_only_fields = ["id", "satuan", "is_active", "updated_at"]

    def validate_kode(self, value: Any) -> Any:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Kode sampah wajib diisi")
        return value

    def validate_nama_sampah(self, value: Any) -> Any:
        value = value.strip()
        if not 2 <= len(value) <= 50:
            raise serializers.ValidationError("Nama jenis sampah wajib diisi")
        return value

    def validate_deskripsi(self, value: Any) -> Any:
        if value and len(value) > 200:
            raise serializers.ValidationError("Deskripsi maksimal 200 karakter")
        return value

    def validate_harga_per_kg(self, value: Any) -> Any:
        if value <= 0:
            raise serializers.ValidationError("Harga harus berupa angka positif")
        if value >= Decimal(1000000000):
            raise serializers.ValidationError("Harga maksimal 9 digit")
        return value

    def get_satuan(self, obj: Any) -> Any:
        return "kg"


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


class SaldoSerializer(serializers.ModelSerializer[Model]):
    nasabah_id = serializers.UUIDField(source="nasabah.id")
    nasabah_nama = serializers.CharField(source="nasabah.nama")

    class Meta:
        model = Saldo
        fields = ["nasabah_id", "nasabah_nama", "total_saldo", "updated_at"]
