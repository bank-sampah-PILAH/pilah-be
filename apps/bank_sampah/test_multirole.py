from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from api.models import BankSampah, User
from apps.bank_sampah.services import BankOnboardingService


class MultiroleTeamTest(TestCase):
    def test_invite_http_endpoints_accept_a_nasabah_or_pengelola_session(self) -> None:
        # PIL-542: an account signed in as a Nasabah can accept an invite
        # without switching role first; before, only a Pengurus session could.
        bank = BankSampah.objects.create(
            nama="Inviting Bank",
            no_hp_pic="+628123456789",
            invite_token="role-bound-invite",
            invite_token_expires=timezone.now() + timedelta(days=1),
        )
        for active_role in ("nasabah", "pengelola"):
            with self.subTest(active_role=active_role):
                user = User.objects.create_user(
                    email=f"invite-{active_role}@example.com", roles=["pengelola", "nasabah"]
                )
                token = AccessToken.for_user(user)
                token["role"] = active_role
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
                outcomes = [
                    client.post(url, {"token": bank.invite_token}, format="json").data["outcome"]
                    for url in ("/api/v1/invites/accept", "/api/v1/bank-sampah/invite/join")
                ]
                self.assertEqual(outcomes, ["join_success", "already_member"])
                user.refresh_from_db()
                self.assertEqual(user.bank_sampah_id, bank.pk)

    def test_team_includes_assigned_pengelola_independently_of_primary_and_active_role(
        self,
    ) -> None:
        bank = BankSampah.objects.create(nama="Bank A", no_hp_pic="+628123456789")
        other = BankSampah.objects.create(nama="Bank B", no_hp_pic="+628123456780")
        manager = User.objects.create_user(
            email="manager@example.com",
            bank_sampah=bank,
            is_profile_complete=True,
            roles=[User.Role.PENGELOLA, User.Role.NASABAH],
        )
        dual = User.objects.create_user(
            email="dual@example.com",
            bank_sampah=bank,
            role=User.Role.NASABAH,
            roles=[User.Role.NASABAH, User.Role.PENGELOLA],
        )
        User.objects.create_user(
            email="customer@example.com", bank_sampah=bank, role=User.Role.NASABAH
        )
        User.objects.create_user(email="inactive@example.com", bank_sampah=bank, is_active=False)
        User.objects.create_user(email="other@example.com", bank_sampah=other)
        token = AccessToken.for_user(manager)
        token["role"] = User.Role.PENGELOLA
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = client.get("/api/v1/team")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {member["id"] for member in response.data["members"]}, {str(manager.pk), str(dual.pk)}
        )
        token["role"] = User.Role.NASABAH
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(client.get("/api/v1/team").status_code, 403)

    def test_invite_eligibility_uses_assigned_pengelola_without_changing_primary_role(self) -> None:
        bank = BankSampah.objects.create(
            nama="Inviting Bank",
            no_hp_pic="+628123456789",
            invite_token="test-invite",
            invite_token_expires=timezone.now() + timedelta(days=1),
        )
        user = User.objects.create_user(
            email="invite-dual@example.com",
            role=User.Role.NASABAH,
            roles=[User.Role.NASABAH, User.Role.PENGELOLA],
        )
        joined, outcome = BankOnboardingService.accept_invite(user, "test-invite")
        self.assertEqual(joined.pk, bank.pk)
        self.assertEqual(outcome, "join_success")
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.NASABAH)
        self.assertEqual(user.roles, [User.Role.NASABAH, User.Role.PENGELOLA])
