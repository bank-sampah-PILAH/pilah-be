from django.db.models import Model
from rest_framework import serializers

from api.models import User


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
