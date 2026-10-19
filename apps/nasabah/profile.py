from rest_framework import serializers
from rest_framework.generics import GenericAPIView
from rest_framework.request import Request
from rest_framework.response import Response

from api.models import User
from shared_kernel.permissions import IsActiveNasabah
from shared_kernel.scoping import current_user
from shared_kernel.validators import normalize_indonesian_phone


class NasabahProfileSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = [
            "id",
            "nama",
            "email",
            "no_hp",
            "jenis_kelamin",
            "tanggal_lahir",
            "alamat",
            "role",
        ]
        read_only_fields = ["id", "email", "role"]

    def validate_no_hp(self, value: str) -> str:
        return normalize_indonesian_phone(value)


class NasabahProfileView(GenericAPIView[User]):
    """Read and edit the authenticated nasabah's own profile fields."""

    permission_classes = [IsActiveNasabah]
    serializer_class = NasabahProfileSerializer

    def get(self, request: Request) -> Response:
        return Response(self.get_serializer(request.user).data)

    def patch(self, request: Request) -> Response:
        user = current_user(request)
        serializer = self.get_serializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
