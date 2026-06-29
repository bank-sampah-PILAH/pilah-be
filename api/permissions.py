from rest_framework.permissions import BasePermission

from api.models import BankSampah, User


class IsPengelola(BasePermission):
    message = "Endpoint ini hanya untuk pengelola"

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.PENGELOLA


class IsActivePengelola(IsPengelola):
    message = "Bank sampah belum aktif"

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return bool(
            request.user.bank_sampah_id
            and request.user.is_profile_complete
            and request.user.bank_sampah.status == BankSampah.Status.ACTIVE
            and request.user.bank_sampah.is_active
        )


class IsPrimaryPengelola(IsActivePengelola):
    message = "Hanya pengelola utama yang dapat melakukan aksi ini"

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.is_primary_pengelola


class IsSuperAdmin(BasePermission):
    message = "Endpoint ini hanya untuk superadmin"

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.SUPERADMIN
