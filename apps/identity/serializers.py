from collections.abc import Mapping
from typing import Any

from django.db.models import Model
from django.utils import timezone
from rest_framework import serializers

from api.models import User
from shared_kernel.validators import normalize_indonesian_phone


class AuthUserSerializer(serializers.ModelSerializer[Model]):
    bank_sampah_id = serializers.UUIDField(source="bank_sampah.id", allow_null=True)
    bank_sampah_nama = serializers.CharField(source="bank_sampah.nama", allow_null=True)
    bank_sampah_status = serializers.CharField(source="bank_sampah.status", allow_null=True)

    class Meta:
        model = User
        fields = [
            "id",
            "nama",
            "email",
            "role",
            "bank_sampah_id",
            "bank_sampah_nama",
            "bank_sampah_status",
            "is_profile_complete",
            "is_primary_pengelola",
        ]


class UserProfileSerializer(serializers.ModelSerializer[Model]):
    class Meta:
        model = User
        fields = [
            "id",
            "nama",
            "email",
            "no_hp",
            "jenis_kelamin",
            "tanggal_lahir",
            "role",
            "is_profile_complete",
            "is_primary_pengelola",
        ]
        read_only_fields = ["id", "email", "role", "is_profile_complete", "is_primary_pengelola"]

    def validate_nama(self, value: Any) -> Any:
        value = value.strip()
        if not 3 <= len(value) <= 100:
            raise serializers.ValidationError("Nama minimal 3 karakter")
        return value

    def validate_no_hp(self, value: Any) -> Any:
        return normalize_indonesian_phone(value)

    def validate_jenis_kelamin(self, value: Any) -> Any:
        if value not in [User.Gender.MALE, User.Gender.FEMALE]:
            raise serializers.ValidationError("Jenis kelamin wajib dipilih")
        return value

    def validate_tanggal_lahir(self, value: Any) -> Any:
        if value > timezone.localdate():
            raise serializers.ValidationError("Tanggal lahir tidak boleh di masa depan")
        return value


class TeamMemberSerializer(serializers.ModelSerializer[Model]):
    is_current_user = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "nama",
            "email",
            "role",
            "is_primary_pengelola",
            "is_current_user",
            "created_at",
        ]

    def get_is_current_user(self, obj: Any) -> Any:
        request = self.context.get("request")
        return bool(request and request.user.id == obj.id)


class InviteAcceptSerializer(serializers.Serializer[Any]):
    token = serializers.CharField(required=False, allow_blank=True)
    invite_token = serializers.CharField(required=False, allow_blank=True, write_only=True)

    def validate(self, attrs: Mapping[str, Any]) -> dict[str, Any]:
        mutable = dict(attrs)
        token = mutable.get("token") or mutable.get("invite_token")
        if not token:
            raise serializers.ValidationError({"token": ["Token undangan wajib diisi"]})
        mutable["token"] = token
        return mutable


class GoogleAuthSerializer(serializers.Serializer[Any]):
    id_token = serializers.CharField(required=True)


class RefreshTokenSerializer(serializers.Serializer[Any]):
    refresh_token = serializers.CharField(required=True)


class LogoutSerializer(serializers.Serializer[Any]):
    refresh_token = serializers.CharField(required=False, allow_blank=True)
