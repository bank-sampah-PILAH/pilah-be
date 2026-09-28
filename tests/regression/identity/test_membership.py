"""Identity contracts: team roster and invite lifecycle."""

from datetime import timedelta

from django.utils import timezone

from tests.regression.helpers import RegressionTestCase


class MembershipRegressionTests(RegressionTestCase):
    def test_team_list_contract(self) -> None:
        response = self.client.get("/api/v1/team")
        self.assertEqual(response.status_code, 200)
        self.assertIn("members", response.data)
        self.assertEqual(len(response.data["members"]), 1)

    def test_invite_generate_accept_and_roster(self) -> None:
        generated = self.client.post("/api/v1/team/invite", {}, format="json")
        self.assertEqual(generated.status_code, 201)
        for key in ("token", "invite_url", "expires_at"):
            self.assertIn(key, generated.data)

        newcomer = self.fresh_pengelola("gabung@example.com")
        self.auth_as(newcomer)
        accepted = self.client.post(
            "/api/v1/invites/accept", {"token": generated.data["token"]}, format="json"
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.data["outcome"], "join_success")

        # Joined but profile-incomplete: still gated out of active endpoints.
        self.assertEqual(self.client.get("/api/v1/team").status_code, 403)
        self.auth_as(self.user)
        members = self.client.get("/api/v1/team")
        self.assertEqual(len(members.data["members"]), 2)

    def test_invite_accept_rejects_expired(self) -> None:
        generated = self.client.post("/api/v1/team/invite", {}, format="json")
        self.bank.invite_token_expires = timezone.now() - timedelta(days=1)
        self.bank.save(update_fields=["invite_token_expires"])
        newcomer = self.fresh_pengelola("telat@example.com")
        self.auth_as(newcomer)
        response = self.client.post(
            "/api/v1/invites/accept", {"token": generated.data["token"]}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_invite_accept_rejects_bogus_token(self) -> None:
        for path in ("/api/v1/invites/accept", "/api/v1/bank-sampah/invite/join"):
            with self.subTest(path=path):
                response = self.client.post(path, {"token": "bogus-token"}, format="json")
                self.assertGreaterEqual(response.status_code, 400)

    def test_invite_accept_rejects_missing_token(self) -> None:
        response = self.client.post("/api/v1/invites/accept", {}, format="json")
        self.assertGreaterEqual(response.status_code, 400)

    def test_non_primary_cannot_generate_invite(self) -> None:
        member = self.fresh_pengelola("anggota@example.com")
        member.bank_sampah = self.bank
        member.is_profile_complete = True
        member.save()
        self.auth_as(member)
        self.assertGreaterEqual(self.client.post("/api/v1/team/invite", {}).status_code, 400)
