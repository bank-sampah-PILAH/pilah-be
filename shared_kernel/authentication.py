from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import Token

from api.models import User
from shared_kernel.roles import token_role


class RoleJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token: Token) -> User:  # type: ignore[override]  # SimpleJWT uses an unbound AuthUser TypeVar
        user = super().get_user(validated_token)
        assert isinstance(user, User)
        token_role(user, validated_token)
        return user


class RoleJWTScheme(SimpleJWTScheme):  # type: ignore[no-untyped-call]  # extension registry lacks annotations
    target_class = "shared_kernel.authentication.RoleJWTAuthentication"
