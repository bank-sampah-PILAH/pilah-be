from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import Token

from api.models import User
from shared_kernel.roles import token_role


class RoleJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token: Token) -> User:
        user = super().get_user(validated_token)
        assert isinstance(user, User)
        token_role(user, validated_token)
        return user
from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme


class RoleJWTScheme(SimpleJWTScheme):
    target_class = "shared_kernel.authentication.RoleJWTAuthentication"
