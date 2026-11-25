from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from api.models import User
from apps.authentication.services import OnboardingService


class ActiveRoleProfileTests(APITestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="active-profile@example.com",
            nama="Nama Lama",
            alamat="Jl. Test",
            roles=[User.Role.PENGELOLA, User.Role.NASABAH],
            is_profile_complete=True,
        )

    def test_active_nasabah_can_resave_pengurus_primary_profile_and_get_nasabah_routing(
        self,
    ) -> None:
        token = AccessToken.for_user(self.user)
        token["role"] = User.Role.NASABAH
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = self.client.put(
            "/api/v1/onboarding/profile", {"nama": "Nama Baru"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["role"], User.Role.NASABAH)
        self.assertEqual(response.data["next_step"], "register_nasabah")
        self.user.refresh_from_db()
        self.assertEqual(self.user.nama, "Nama Baru")
        self.assertEqual(self.user.role, User.Role.PENGELOLA)
        self.assertEqual(self.user.roles, [User.Role.PENGELOLA, User.Role.NASABAH])

    def test_active_nasabah_address_validation_does_not_use_primary_pengurus_role(self) -> None:
        token = AccessToken.for_user(self.user)
        token["role"] = User.Role.NASABAH
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = self.client.put("/api/v1/onboarding/profile", {"alamat": " "}, format="json")
        self.assertEqual(response.status_code, 422)
        self.user.refresh_from_db()
        self.assertEqual(self.user.alamat, "Jl. Test")

    def test_active_pengurus_cannot_repeat_save_even_with_nasabah_primary(self) -> None:
        self.user.role = User.Role.NASABAH
        self.user.save(update_fields=["role"])
        token = AccessToken.for_user(self.user)
        token["role"] = User.Role.PENGELOLA
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = self.client.put(
            "/api/v1/onboarding/profile", {"nama": "Nama Baru"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.nama, "Nama Lama")

    def test_profile_service_rechecks_revoked_session_role_after_lock(self) -> None:
        User.objects.filter(pk=self.user.pk).update(roles=[User.Role.PENGELOLA])
        with self.assertRaises(AuthenticationFailed):
            OnboardingService.complete_profile(
                self.user, {"nama": "Nama Baru"}, active_role=User.Role.NASABAH
            )
        self.user.refresh_from_db()
        self.assertEqual(self.user.nama, "Nama Lama")
