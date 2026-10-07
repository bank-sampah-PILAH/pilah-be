from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Model
from django.utils import timezone
from rest_framework import serializers

from api.models import JenisSampah
from apps.waste_catalog.api import versi_berlaku, versi_terjadwal


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
        sekarang = timezone.now()
        berlaku = versi_berlaku(instance, sekarang)
        if berlaku is not None:
            data["harga_per_kg"] = _HARGA.to_representation(berlaku.harga_per_kg)
        data["harga_berlaku_mulai"] = (
            _WAKTU.to_representation(berlaku.berlaku_mulai) if berlaku else None
        )
        terjadwal = versi_terjadwal(instance, sekarang)
        data["harga_terjadwal"] = (
            {
                "harga_per_kg": _HARGA.to_representation(terjadwal.harga_per_kg),
                "berlaku_mulai": _WAKTU.to_representation(terjadwal.berlaku_mulai),
            }
            if terjadwal
            else None
        )
        return data


_HARGA = serializers.DecimalField(max_digits=11, decimal_places=2)
_WAKTU = serializers.DateTimeField()


def validasi_harga(value: Decimal) -> Decimal:
    if value <= 0:
        raise serializers.ValidationError("Harga harus berupa angka positif")
    if value >= Decimal(1000000000):
        raise serializers.ValidationError("Harga maksimal 9 digit")
    return value


# Jadwal harga lebih jauh dari ini hampir pasti salah ketik tahun.
BATAS_JADWAL_HARGA_HARI = 365


class WaktuBerzonaField(serializers.DateTimeField):
    """Waktu yang wajib membawa offset zona waktu.

    Bank sampah bisa berada di WIB, WITA, atau WIT. Waktu tanpa offset akan
    ditafsirkan sebagai UTC dan bergeser beberapa jam, jadi ditolak.
    """

    default_error_messages = {"tanpa_zona": "Sertakan zona waktu, misalnya +07:00."}

    def enforce_timezone(self, value: datetime) -> datetime:
        if timezone.is_naive(value):
            self.fail("tanpa_zona")
        return super().enforce_timezone(value)


class HargaBaruSerializer(serializers.Serializer[Any]):
    harga_per_kg = serializers.DecimalField(
        max_digits=11, decimal_places=2, validators=[validasi_harga]
    )
    berlaku_mulai = WaktuBerzonaField(required=False)

    def validate_berlaku_mulai(self, value: datetime) -> datetime:
        sekarang = timezone.now()
        if value <= sekarang:
            raise serializers.ValidationError(
                "Harga tidak boleh berlaku surut. Kosongkan untuk berlaku sekarang."
            )
        if value > sekarang + timedelta(days=BATAS_JADWAL_HARGA_HARI):
            raise serializers.ValidationError(
                f"Harga paling lambat dijadwalkan {BATAS_JADWAL_HARGA_HARI} hari dari sekarang."
            )
        return value
