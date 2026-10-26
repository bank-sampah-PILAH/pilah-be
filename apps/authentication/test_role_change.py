"""PIL-451: a Google account that picked the wrong role can pick again until
onboarding has committed anything for that role."""

from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from api.models import User

URL = "/api/v1/onboarding/role"


class RoleChangeTests(APITestCase):
    def _fresh(self, role: str = User.Role.PENGELOLA) -> User:
        return User.objects.create_user(email=f"{role}@example.com", nama="Baru", role=role)

    def test_an_unfinished_account_switches_role_and_gets_a_session_for_it(self) -> None:
        user = self._fresh(User.Role.PENGELOLA)
        self.client.force_authenticate(user)

        response = self.client.patch(URL, {"role": User.Role.NASABAH}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["user"]["role"], User.Role.NASABAH)
        self.assertEqual(response.data["next_step"], "complete_profile")
        self.assertEqual(AccessToken(response.data["access_token"])["role"], User.Role.NASABAH)
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.NASABAH)
