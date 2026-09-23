from rest_framework import serializers
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import User


class IsNasabahProfileOwner(BasePermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            request.user.is_authenticated
            and request.user.is_active
            and request.user.role == User.Role.NASABAH
        )


class NasabahProfileSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ["id", "nama", "email", "role"]
        read_only_fields = fields


class NasabahProfileView(GenericAPIView[User]):
    """Read the authenticated identity without loading management settings."""

    permission_classes = [IsNasabahProfileOwner]
    serializer_class = NasabahProfileSerializer

    def get(self, request: Request) -> Response:
        return Response(self.get_serializer(request.user).data)
