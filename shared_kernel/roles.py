from typing import Any

from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from api.models import User


def token_role(user: User, token: Any) -> str:
    """Absent claims use the primary role; explicit invalid claims never do."""
    role = token.get("role", user.role) if token is not None else user.role
    if not isinstance(role, str) or role not in User.Role.values or role not in user.roles:
        raise AuthenticationFailed("Role token tidak dimiliki akun")
    return role


def active_role(request: Request) -> str:
    if not isinstance(request.user, User):
        raise AuthenticationFailed("Akun tidak terautentikasi")
    return token_role(request.user, request.auth)
