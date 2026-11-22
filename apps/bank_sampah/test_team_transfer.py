import uuid
from unittest import mock

from django.db import IntegrityError
from rest_framework.test import APIClient, APITestCase

from api.models import BankSampah, PushNotification, User
from apps.bank_sampah.services import TeamService

URL = "/api/v1/team/transfer"


def make_bank(nama: str = "Melati") -> BankSampah:
    return BankSampah.objects.create(
        nama=nama,
        alamat="Depok",
        kota="Depok",
        no_hp_pic="+628111111111",
        status=BankSampah.Status.ACTIVE,
        is_active=True,
    )


def make_pengurus(email: str, bank: BankSampah, *, primary: bool = False, **extra: object) -> User:
    fields: dict[str, object] = {
        "nama": email.split("@")[0],
        "role": User.Role.PENGELOLA,
        "bank_sampah": bank,
        "is_primary_pengelola": primary,
        "is_profile_complete": True,
    }
    fields.update(extra)
    return User.objects.create_user(email=email, **fields)


class TeamTransferTests(APITestCase):
    def setUp(self) -> None:
        self.bank = make_bank()
        self.owner = make_pengurus("owner@example.test", self.bank, primary=True)
        self.other = make_pengurus("other@example.test", self.bank)
        self.client = APIClient()

    def _as(self, user: User) -> APIClient:
        self.client.force_authenticate(user)
        return self.client

    def _primaries(self) -> list[User]:
        return list(User.objects.filter(bank_sampah=self.bank, is_primary_pengelola=True))

    def test_primary_hands_over_and_response_is_the_fresh_team_list(self) -> None:
        response = self._as(self.owner).post(URL, {"id": str(self.other.id)}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._primaries(), [self.other])
        members = response.json()["members"]
        self.assertEqual([m["id"] for m in members], [str(self.other.id), str(self.owner.id)])
        self.assertEqual([m["is_primary_pengelola"] for m in members], [True, False])
        self.assertTrue(members[1]["is_current_user"])
        self.assertEqual(members, self.client.get("/api/v1/team").json()["members"])

    def test_new_primary_is_notified_without_naming_anyone(self) -> None:
        self._as(self.owner).post(URL, {"id": str(self.other.id)}, format="json")

        push = PushNotification.objects.get(user=self.other)
        self.assertEqual(push.title, "Anda kini Pengurus Utama")
        self.assertNotIn(self.owner.nama, push.body)
        self.assertNotIn(self.owner.email, push.body)

    def test_old_primary_loses_primary_only_actions(self) -> None:
        self._as(self.owner).post(URL, {"id": str(self.other.id)}, format="json")

        self.assertEqual(
            self.client.post(URL, {"id": str(self.other.id)}, format="json").status_code, 403
        )

    def test_non_primary_cannot_transfer(self) -> None:
        response = self._as(self.other).post(URL, {"id": str(self.owner.id)}, format="json")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._primaries(), [self.owner])

    def test_cannot_hand_over_to_oneself(self) -> None:
        response = self._as(self.owner).post(URL, {"id": str(self.owner.id)}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("diri sendiri", response.json()["error"])
        self.assertEqual(self._primaries(), [self.owner])

    def test_target_from_another_bank_is_not_found(self) -> None:
        stranger = make_pengurus("stranger@example.test", make_bank("Mawar"))

        response = self._as(self.owner).post(URL, {"id": str(stranger.id)}, format="json")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self._primaries(), [self.owner])

    def test_unknown_inactive_and_non_pengurus_targets_are_not_found(self) -> None:
        inactive = make_pengurus("gone@example.test", self.bank, is_active=False)
        nasabah = make_pengurus("n@example.test", self.bank, role=User.Role.NASABAH)
        for target in (uuid.uuid4(), inactive.id, nasabah.id):
            with self.subTest(target=target):
                response = self._as(self.owner).post(URL, {"id": str(target)}, format="json")
                self.assertEqual(response.status_code, 404)
        self.assertEqual(self._primaries(), [self.owner])

    def test_malformed_body_is_a_validation_error(self) -> None:
        for body in ({}, {"id": "bukan-uuid"}, {"id": None}):
            with self.subTest(body=body):
                response = self._as(self.owner).post(URL, body, format="json")
                self.assertEqual(response.status_code, 422)

    def test_anonymous_is_rejected(self) -> None:
        self.assertEqual(
            APIClient().post(URL, {"id": str(self.other.id)}, format="json").status_code, 401
        )

    def test_failed_promotion_rolls_the_demotion_back(self) -> None:
        with mock.patch.object(TeamService, "_promote", side_effect=IntegrityError("boom")):
            with self.assertRaises(IntegrityError):
                TeamService.transfer_primary(self.owner, self.other.id)

        self.assertEqual(self._primaries(), [self.owner])
        self.assertFalse(PushNotification.objects.exists())

    def test_stale_caller_who_already_handed_over_is_refused(self) -> None:
        stale_owner = User.objects.get(pk=self.owner.pk)
        TeamService.transfer_primary(self.owner, self.other.id)

        with self.assertRaises(PermissionError):
            TeamService.transfer_primary(stale_owner, self.other.id)

        self.assertEqual(self._primaries(), [self.other])
