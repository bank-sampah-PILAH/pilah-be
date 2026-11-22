from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from api.models import User


class SwitchRoleTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="switch@example.com",
            roles=[User.Role.PENGELOLA, User.Role.NASABAH],
            is_profile_complete=True,
        )
        self.refresh = RefreshToken.for_user(self.user)
        self.refresh["role"] = User.Role.PENGELOLA
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.refresh.access_token}")

    def test_owned_role_issues_new_token_pair_without_changing_account(self) -> None:
        response = self.client.post(
            "/api/v1/auth/switch-role", {"role": User.Role.NASABAH}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        for token in (
            AccessToken(response.data["access_token"]),
            RefreshToken(response.data["refresh_token"]),
        ):
            self.assertEqual(token["role"], User.Role.NASABAH)
            self.assertEqual(str(token["user_id"]), str(self.user.pk))
        self.assertNotEqual(response.data["refresh_token"], str(self.refresh))
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.PENGELOLA)
        self.assertEqual(self.user.roles, [User.Role.PENGELOLA, User.Role.NASABAH])

    def test_response_routes_to_selected_role_without_nasabah_membership(self) -> None:
        response = self.client.post(
            "/api/v1/auth/switch-role", {"role": User.Role.NASABAH}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["role"], User.Role.NASABAH)
        self.assertEqual(response.data["user"]["state"], "register_nasabah")
        self.assertEqual(response.data["next_step"], "register_nasabah")

    def test_unowned_role_is_forbidden_and_preserves_existing_session(self) -> None:
        response = self.client.post(
            "/api/v1/auth/switch-role", {"role": User.Role.SUPERADMIN}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "role_not_owned")
        self.assertIn("error", response.data)
        self.assertNotIn("access_token", response.data)
        self.assertNotIn("refresh_token", response.data)
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 200)
        refreshed = self.client.post(
            "/api/v1/auth/refresh", {"refresh_token": str(self.refresh)}, format="json"
        )
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(AccessToken(refreshed.data["access_token"])["role"], User.Role.PENGELOLA)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.PENGELOLA)
        self.assertEqual(self.user.roles, [User.Role.PENGELOLA, User.Role.NASABAH])
