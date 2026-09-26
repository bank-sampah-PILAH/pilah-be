from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from api.models import BankSampah, User
from api.services import AuthService


def _auth_user(request: Request) -> User:
    assert isinstance(request.user, User)  # ponytail: IsAuthenticated gates these endpoints
    return request.user


class IsPengelola(BasePermission):
    message = "Endpoint ini hanya untuk pengelola"

    def has_permission(self, request: Request, view: APIView) -> bool:
        return request.user.is_authenticated and request.user.role == User.Role.PENGELOLA


class IsRegistrationRole(BasePermission):
    message = "Endpoint ini hanya untuk peran yang sedang mendaftar"

    def has_permission(self, request: Request, view: APIView) -> bool:
        return request.user.is_authenticated and request.user.role in User.GOOGLE_REGISTRATION_ROLES


class IsActivePengelola(IsPengelola):
    message = "Bank sampah belum aktif"

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not super().has_permission(request, view):
            return False
        user = _auth_user(request)
        bank = user.bank_sampah
        return bool(
            user.bank_sampah_id
            and user.is_profile_complete
            and bank is not None
            and bank.status == BankSampah.Status.ACTIVE
            and bank.is_active
        )


class IsPrimaryPengelola(IsActivePengelola):
    message = "Hanya pengelola utama yang dapat melakukan aksi ini"

    def has_permission(self, request: Request, view: APIView) -> bool:
        return super().has_permission(request, view) and _auth_user(request).is_primary_pengelola


class IsSuperAdmin(BasePermission):
    message = "Endpoint ini hanya untuk superadmin"

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return (
            user.is_authenticated
            and user.role == User.Role.SUPERADMIN
            and AuthService.is_superadmin_allowlisted(user.email)
        )


class IsActiveNasabah(BasePermission):
    """Require an active nasabah account, not active membership or bank status."""

    message = "Endpoint ini hanya untuk nasabah"

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not user.is_authenticated:
            return False
        return bool(user.is_active and user.role == User.Role.NASABAH)
