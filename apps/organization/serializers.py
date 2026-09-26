from typing import Any

from django.db.models import Model
from rest_framework import serializers

from api.models import BankSampah
from shared_kernel.validators import normalize_indonesian_phone


def validate_image_upload(value: Any, label: str) -> Any:
    name = getattr(value, "name", str(value)).lower()
    if not name.endswith((".jpg", ".jpeg", ".png")):
        raise serializers.ValidationError(f"{label} harus berformat JPG, JPEG, atau PNG")
    if getattr(value, "size", 0) > 5 * 1024 * 1024:
        raise serializers.ValidationError(f"Ukuran {label.lower()} maksimal 5 MB")
    return value


class BankSampahSerializer(serializers.ModelSerializer[Model]):
    pengelola = serializers.SerializerMethodField()

    class Meta:
        model = BankSampah
        fields = [
            "id",
            "nama",
            "alamat",
            "kota",
            "no_hp_pic",
            "wa_gateway_token",
            "foto_logo",
            "status",
            "is_active",
            "created_at",
            "pengelola",
        ]
        read_only_fields = ["id", "status", "is_active", "created_at", "pengelola"]

    def validate_nama(self, value: Any) -> Any:
        if len(value.strip()) < 3:
            raise serializers.ValidationError("Nama bank sampah wajib diisi")
        return value.strip()

    def validate_no_hp_pic(self, value: Any) -> Any:
        try:
            return normalize_indonesian_phone(value)
        except serializers.ValidationError as err:
            raise serializers.ValidationError("Format nomor tidak valid") from err

    def validate_foto_logo(self, value: Any) -> Any:
        return validate_image_upload(value, "Foto logo")

    def get_pengelola(self, obj: Any) -> Any:
        user = obj.users.filter(role="pengelola", is_active=True).first()
        if not user:
            return None
        return {"id": str(user.id), "nama": user.nama, "email": user.email}


class BankSampahRegistrationSerializer(serializers.Serializer[Any]):
    nama = serializers.CharField(required=True, max_length=100)
    alamat = serializers.CharField(required=True)
    kota = serializers.CharField(required=False, allow_blank=True, max_length=100)
    no_hp_pic = serializers.CharField(required=True)
    foto_kegiatan = serializers.FileField(required=True)

    def validate_nama(self, value: Any) -> Any:
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("Nama Bank Sampah wajib diisi (minimal 3 karakter)")
        return value

    def validate_alamat(self, value: Any) -> Any:
        value = value.strip()
        if len(value) < 10:
            raise serializers.ValidationError(
                "Alamat lengkap wajib diisi untuk keperluan verifikasi lokasi"
            )
        return value

    def validate_no_hp_pic(self, value: Any) -> Any:
        return normalize_indonesian_phone(value)

    def validate_foto_kegiatan(self, value: Any) -> Any:
        if not value:
            raise serializers.ValidationError("Foto kegiatan wajib diunggah sebagai bukti validasi")
        return validate_image_upload(value, "Foto kegiatan")
