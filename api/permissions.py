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


class IsNasabah(BasePermission):
    message = "Endpoint ini hanya untuk nasabah dengan profil lengkap"

    def has_permission(self, request: Request, view: APIView) -> bool:
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.NASABAH
            and request.user.is_profile_complete
        )


class IsNasabahRole(BasePermission):
    """Like `IsNasabah`, but without the `is_profile_complete` requirement.

    A pengurus-entered record can now auto-link on login before the user
    has filled in their own profile (see AuthService._sync_nasabah_prefill),
    so an endpoint that needs to see that membership before the profile
    step ever posts to the backend — the bank-sampah picker's existing-
    membership check — can't gate on profile completeness the way
    `IsNasabah` does for endpoints that actually depend on it.
    """

    message = "Endpoint ini hanya untuk nasabah"

    def has_permission(self, request: Request, view: APIView) -> bool:
        return request.user.is_authenticated and request.user.role == User.Role.NASABAH


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


class IsJadwalViewer(BasePermission):
    message = "Jadwal hanya dapat dilihat oleh pengelola atau nasabah aktif"

    def has_permission(self, request: Request, view: APIView) -> bool:
        if IsActivePengelola().has_permission(request, view):
            return True
        if not request.user.is_authenticated:
            return False
        user = _auth_user(request)
        return user.role == User.Role.NASABAH and user.is_active


class IsSuperAdmin(BasePermission):
    message = "Endpoint ini hanya untuk superadmin"

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return (
            user.is_authenticated
            and user.role == User.Role.SUPERADMIN
            and AuthService.is_superadmin_allowlisted(user.email)
        )
