from decimal import Decimal
from typing import Any

from django.db.models import Model, Q, Sum
from django.db.models.functions import Coalesce
from rest_framework import serializers

from api.kalkulasi import bulatkan_rupiah, format_ribuan
from api.models import DetailTransaksi, Transaksi
from apps.ledger.services import BalanceService
from shared_kernel.validators import get_initials


class TransactionListSerializer(serializers.ModelSerializer[Model]):
    nasabah_id = serializers.UUIDField(source="nasabah.id")
    nasabah_nama = serializers.CharField(source="nasabah.nama")
    nasabah_inisial = serializers.SerializerMethodField()
    jenis_sampah_utama = serializers.SerializerMethodField()
    total_berat_kg = serializers.SerializerMethodField()
    dicatat_oleh = serializers.UUIDField(source="dicatat_oleh.id")

    class Meta:
        model = Transaksi
        fields = [
            "id",
            "nasabah_id",
            "nasabah_nama",
            "nasabah_inisial",
            "jenis_sampah_utama",
            "total_berat_kg",
            "total_nilai",
            "tanggal",
            "status_wa",
            "dicatat_oleh",
        ]

    def get_nasabah_inisial(self, obj: Any) -> Any:
        return get_initials(obj.nasabah.nama)

    def get_jenis_sampah_utama(self, obj: Any) -> Any:
        item = max(obj.items.all(), key=lambda detail: detail.berat, default=None)
        return item.nama_sampah_snapshot if item else None

    def get_total_berat_kg(self, obj: Any) -> Any:
        return sum((item.berat for item in obj.items.all()), Decimal(0))


BERAT_MAKS_PER_ITEM = Decimal(500)
BERAT_MAKS_PER_SETORAN = Decimal(1000)


class TransactionItemInputSerializer(serializers.Serializer[Any]):
    jenis_sampah_id = serializers.UUIDField(required=True)
    berat = serializers.DecimalField(
        max_digits=10,
        decimal_places=3,
        min_value=Decimal("0.001"),
        max_value=BERAT_MAKS_PER_ITEM,
        error_messages={
            "max_value": f"Berat maksimal {format_ribuan(BERAT_MAKS_PER_ITEM)} kg untuk satu jenis sampah"
        },
    )


class TransactionCreateSerializer(serializers.Serializer[Any]):
    nasabah_id = serializers.UUIDField(required=True)
    items = TransactionItemInputSerializer(many=True, required=True)
    catatan = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_items(self, value: Any) -> Any:
        if not value:
            raise serializers.ValidationError("Minimal 1 item setoran diperlukan")
        if sum(item["berat"] for item in value) > BERAT_MAKS_PER_SETORAN:
            raise serializers.ValidationError(
                f"Total berat satu setoran maksimal {format_ribuan(BERAT_MAKS_PER_SETORAN)} kg"
            )
        return value

    def validate(self, attrs: Any) -> Any:
        # Harga hanya boleh berasal dari master jenis sampah. Menerima harga
        # dari client membuat nilai setoran bisa diatur dari luar sistem, jadi
        # request yang masih mengirimnya ditolak, bukan diabaikan diam-diam.
        raw_items = self.initial_data.get("items")
        if isinstance(raw_items, list):
            item_errors: list[dict[str, list[str]]] = [
                {"harga_per_kg": ["Harga diambil dari master jenis sampah dan tidak dapat dikirim"]}
                if isinstance(item, dict) and "harga_per_kg" in item
                else {}
                for item in raw_items
            ]
            if any(item_errors):
                raise serializers.ValidationError({"items": item_errors})
        return attrs


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
        return bulatkan_rupiah(
            BalanceService.saldo_at(obj.bank_sampah, obj.nasabah_id, obj.tanggal, obj.id)
        )
