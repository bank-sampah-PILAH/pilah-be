from rest_framework.test import APITestCase

from api.models import User


class NasabahProfileTests(APITestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="siti@example.test", nama="Siti Aminah", role=User.Role.NASABAH
        )
        self.client.force_authenticate(self.user)
        self.url = "/api/v1/nasabah/me/profil"

    def test_profile_returns_only_signed_in_identity(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "id": str(self.user.id),
                "nama": "Siti Aminah",
                "email": "siti@example.test",
                "role": "nasabah",
            },
        )

    def test_identity_changes_with_authenticated_user(self) -> None:
        other = User.objects.create_user(
            email="budi@example.test", nama="Budi", role=User.Role.NASABAH
        )
        self.client.force_authenticate(other)
        response = self.client.get(self.url, {"user_id": str(self.user.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(other.id))
        self.assertEqual(response.data["nama"], "Budi")

    def test_profile_does_not_require_membership(self) -> None:
        self.assertFalse(self.user.keanggotaan_nasabah.exists())
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_anonymous_and_management_roles_cannot_access(self) -> None:
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)
        for role in (User.Role.PENGELOLA, User.Role.PENGELOLA_INDUK, User.Role.SUPERADMIN):
            user = User.objects.create_user(
                email=f"{role}@example.test", nama="Pengurus", role=role
            )
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_profile_is_read_only(self) -> None:
        for method in (self.client.post, self.client.put, self.client.patch, self.client.delete):
            self.assertEqual(method(self.url, {"nama": "Changed"}).status_code, 405)
        self.user.refresh_from_db()
        self.assertEqual(self.user.nama, "Siti Aminah")

    def test_jwt_authentication(self) -> None:
        from rest_framework_simplejwt.tokens import AccessToken

        self.client.force_authenticate(None)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.client.get(self.url).status_code, 401)
