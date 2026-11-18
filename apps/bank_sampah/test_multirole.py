from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from api.models import BankSampah, User


class MultiroleTeamTest(TestCase):
    def test_team_includes_assigned_pengelola_independently_of_primary_and_active_role(self):
        bank = BankSampah.objects.create(nama="Bank A", no_hp_pic="+628123456789")
        other = BankSampah.objects.create(nama="Bank B", no_hp_pic="+628123456780")
        manager = User.objects.create_user(
            email="manager@example.com", bank_sampah=bank, is_profile_complete=True,
            roles=[User.Role.PENGELOLA, User.Role.NASABAH],
        )
        dual = User.objects.create_user(
            email="dual@example.com", bank_sampah=bank, role=User.Role.NASABAH,
            roles=[User.Role.NASABAH, User.Role.PENGELOLA],
        )
        User.objects.create_user(email="customer@example.com", bank_sampah=bank, role=User.Role.NASABAH)
        User.objects.create_user(email="inactive@example.com", bank_sampah=bank, is_active=False)
        User.objects.create_user(email="other@example.com", bank_sampah=other)
        token = AccessToken.for_user(manager)
        token["role"] = User.Role.PENGELOLA
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = client.get("/api/v1/team")
        self.assertEqual(response.status_code, 200)
        self.assertEqual({member["id"] for member in response.data["members"]}, {str(manager.pk), str(dual.pk)})
        token["role"] = User.Role.NASABAH
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(client.get("/api/v1/team").status_code, 403)
