from rest_framework.test import APITestCase

from api.models import User


class NavigationRoleContractTests(APITestCase):
    def test_session_reports_each_supported_role(self) -> None:
        for role in User.Role.values:
            with self.subTest(role=role):
                user = User.objects.create_user(
                    email=f"{role}@example.test",
                    nama="Role contract",
                    role=role,
                )
                self.client.force_authenticate(user)
                response = self.client.get("/api/v1/auth/me")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["role"], role)
                self.assertNotIn("password", response.data)

    def test_client_cannot_select_its_role_through_query_parameters(self) -> None:
        user = User.objects.create_user(
            email="nasabah@example.test",
            nama="Siti",
            role=User.Role.NASABAH,
        )
        self.client.force_authenticate(user)
        response = self.client.get("/api/v1/auth/me", {"role": "superadmin"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["role"], "nasabah")
        self.assertEqual(self.client.get("/api/v1/team").status_code, 403)

    def test_signed_out_session_has_no_role_contract(self) -> None:
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)
