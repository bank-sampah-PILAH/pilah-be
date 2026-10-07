from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Model
from django.utils import timezone
from rest_framework import serializers

from api.models import (
    DetailTransaksi,
    DraftPencairan,
    DraftPencairanItem,
    Pencairan,
    PencairanRevisi,
    Transaksi,
)
from apps.ledger.services import BalanceService, PencairanService
from shared_kernel.kalkulasi import bulatkan_rupiah, format_ribuan
from shared_kernel.validators import get_initials

# Nested `source` paths shared by several serializers (one definition each).
_NASABAH_ID = "nasabah.id"
_NASABAH_NAMA = "nasabah.nama"
_BANK_SAMPAH_ID = "bank_sampah.id"
_DICATAT_OLEH_ID = "dicatat_oleh.id"


class TransactionListSerializer(serializers.ModelSerializer[Model]):
    nasabah_id = serializers.UUIDField(source=_NASABAH_ID)
    nasabah_nama = serializers.CharField(source=_NASABAH_NAMA)
    nasabah_inisial = serializers.SerializerMethodField()
    jenis_sampah_utama = serializers.SerializerMethodField()
    total_berat_kg = serializers.SerializerMethodField()
    dicatat_oleh = serializers.UUIDField(source=_DICATAT_OLEH_ID)

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
        # Item dengan jenis sampah sama digabung jadi satu baris (CPBI-08):
        # berat dijumlah, harga tetap dari master sehingga aman digabung.
        merged: dict[UUID, dict[str, Any]] = {}
        for item in value:
            jid = item["jenis_sampah_id"]
            if jid in merged:
                merged[jid]["berat"] += item["berat"]
            else:
                merged[jid] = dict(item)
        items = list(merged.values())
        # Batas 500 kg tetap per baris input (sudah dijaga TransactionItemInputSerializer);
        # total gabungan per jenis tidak di-cap tambahan — dua baris 300 kg yang sama-sama
        # valid tidak boleh ditolak hanya karena kebetulan satu jenis (rev PR 70).
        return items

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
    jenis_sampah_id = serializers.UUIDField()

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
    nasabah_id = serializers.UUIDField(source=_NASABAH_ID)
    nasabah_nama = serializers.CharField(source=_NASABAH_NAMA)
    bank_sampah_id = serializers.UUIDField(source=_BANK_SAMPAH_ID)
    dicatat_oleh = serializers.UUIDField(source=_DICATAT_OLEH_ID)
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


def _validate_tanggal_pencairan(value: datetime) -> datetime:
    if value > timezone.now():
        raise serializers.ValidationError("Tanggal pencairan tidak boleh di masa depan")
    return value


def _validate_nominal_pencairan(value: Decimal) -> Decimal:
    if value <= 0:
        raise serializers.ValidationError("Nominal harus lebih dari nol")
    if value != value.to_integral_value():
        raise serializers.ValidationError("Nominal harus dalam rupiah bulat tanpa desimal")
    return value


class PencairanCreateSerializer(serializers.Serializer[Any]):
    nasabah_id = serializers.UUIDField(required=True)
    nominal = serializers.DecimalField(max_digits=14, decimal_places=2, required=True)
    metode = serializers.ChoiceField(choices=Pencairan.Metode.choices, required=True)
    tanggal = serializers.DateTimeField(required=False)
    keterangan = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=255
    )

    def validate_nominal(self, value: Decimal) -> Decimal:
        return _validate_nominal_pencairan(value)

    def validate_tanggal(self, value: datetime) -> datetime:
        return _validate_tanggal_pencairan(value)


class PencairanEditSerializer(serializers.Serializer[Any]):
    nominal = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    metode = serializers.ChoiceField(choices=Pencairan.Metode.choices, required=False)
    tanggal = serializers.DateTimeField(required=False)
    keterangan = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=255
    )
    alasan = serializers.CharField(
        required=True,
        max_length=255,
        error_messages={
            "required": "Alasan perubahan wajib diisi",
            "blank": "Alasan perubahan wajib diisi",
        },
    )

    def validate_nominal(self, value: Decimal) -> Decimal:
        return _validate_nominal_pencairan(value)

    def validate_tanggal(self, value: datetime) -> datetime:
        return _validate_tanggal_pencairan(value)


class PencairanDetailSerializer(serializers.ModelSerializer[Model]):
    nasabah_id = serializers.UUIDField(source=_NASABAH_ID)
    nasabah_nama = serializers.CharField(source=_NASABAH_NAMA)
    bank_sampah_id = serializers.UUIDField(source=_BANK_SAMPAH_ID)
    bank_sampah_nama = serializers.CharField(source="bank_sampah.nama")
    dicatat_oleh = serializers.UUIDField(source=_DICATAT_OLEH_ID)
    dicatat_oleh_nama = serializers.CharField(source="dicatat_oleh.nama")
    diperbarui = serializers.SerializerMethodField()
    tanggal_edit_minimum = serializers.SerializerMethodField()

    class Meta:
        model = Pencairan
        fields = [
            "id",
            "nasabah_id",
            "nasabah_nama",
            "bank_sampah_id",
            "bank_sampah_nama",
            "dicatat_oleh",
            "dicatat_oleh_nama",
            "tanggal",
            "nominal",
            "metode",
            "keterangan",
            "status",
            "saldo_sebelum",
            "saldo_sesudah",
            "diperbarui",
            "tanggal_edit_minimum",
            "created_at",
        ]

    def get_diperbarui(self, obj: Pencairan) -> bool:
        return PencairanService.diperbarui(obj)

    def get_tanggal_edit_minimum(self, obj: Pencairan) -> str:
        return serializers.DateTimeField().to_representation(
            PencairanService.tanggal_edit_minimum(obj)
        )


class PencairanRevisiSerializer(serializers.ModelSerializer[Model]):
    diubah_oleh = serializers.UUIDField(source="diubah_oleh.id")
    diubah_oleh_nama = serializers.CharField(source="diubah_oleh.nama")

    class Meta:
        model = PencairanRevisi
        fields = [
            "versi",
            "tanggal",
            "nominal",
            "metode",
            "keterangan",
            "saldo_sebelum",
            "saldo_sesudah",
            "alasan",
            "diubah_oleh",
            "diubah_oleh_nama",
            "diubah_pada",
        ]


class DraftItemInputSerializer(serializers.Serializer[Any]):
    nasabah_id = serializers.UUIDField()
    nominal = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    metode = serializers.ChoiceField(choices=Pencairan.Metode.choices, required=False)

    def validate_nominal(self, value: Decimal) -> Decimal:
        return _validate_nominal_pencairan(value)


class DraftPencairanCreateSerializer(serializers.Serializer[Any]):
    items = DraftItemInputSerializer(many=True, allow_empty=False)


class DraftPencairanItemSerializer(serializers.ModelSerializer[Model]):
    nasabah_id = serializers.UUIDField(source=_NASABAH_ID)
    nasabah_nama = serializers.CharField(source=_NASABAH_NAMA)

    class Meta:
        model = DraftPencairanItem
        fields = ["id", "nasabah_id", "nasabah_nama", "nominal", "metode"]


class DraftPencairanSerializer(serializers.ModelSerializer[Model]):
    items = DraftPencairanItemSerializer(many=True, read_only=True)

    class Meta:
        model = DraftPencairan
        fields = ["id", "status", "items"]
