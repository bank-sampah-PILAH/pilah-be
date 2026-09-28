from rest_framework import serializers
from rest_framework.generics import GenericAPIView
from rest_framework.request import Request
from rest_framework.response import Response

from api.models import User
from api.permissions import IsActiveNasabah


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


class NasabahProfileView(GenericAPIView[User]):
    """Read and edit the authenticated nasabah's own profile fields."""

    permission_classes = [IsActiveNasabah]
    serializer_class = NasabahProfileSerializer

    def get(self, request: Request) -> Response:
        return Response(self.get_serializer(request.user).data)

    def patch(self, request: Request) -> Response:
        serializer = self.get_serializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
