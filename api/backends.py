from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import AnonymousUser

from api.models import User
from api.services import AuthService


class AllowlistedSuperadminBackend(ModelBackend):
    def user_can_authenticate(self, user: User | AnonymousUser | None) -> bool:
        if not super().user_can_authenticate(user):
            return False
        if not isinstance(user, User):
            return False
        if user.role == User.Role.SUPERADMIN:
            return AuthService._sync_superadmin_admin_flags(user, user.email)
        return not user.is_staff and not user.is_superuser
