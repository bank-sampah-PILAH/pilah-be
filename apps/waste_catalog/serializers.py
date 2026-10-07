from decimal import Decimal
from typing import Any

from django.db.models import Model
from django.utils import timezone
from rest_framework import serializers

from api.models import JenisSampah
from apps.waste_catalog.api import harga_berlaku


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
        return validasi_harga(value)

    def get_satuan(self, obj: Any) -> Any:
        return "kg"

    def to_representation(self, instance: Any) -> Any:
        data = super().to_representation(instance)
        harga = harga_berlaku(instance, timezone.now())
        if harga is not None:
            data["harga_per_kg"] = serializers.DecimalField(
                max_digits=11, decimal_places=2
            ).to_representation(harga)
        return data


def validasi_harga(value: Decimal) -> Decimal:
    if value <= 0:
        raise serializers.ValidationError("Harga harus berupa angka positif")
    if value >= Decimal(1000000000):
        raise serializers.ValidationError("Harga maksimal 9 digit")
    return value


class HargaBaruSerializer(serializers.Serializer[Any]):
    harga_per_kg = serializers.DecimalField(
        max_digits=11, decimal_places=2, validators=[validasi_harga]
    )
