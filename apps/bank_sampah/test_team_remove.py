import uuid
from decimal import Decimal

from rest_framework.test import APIClient, APITestCase

from api.models import BankSampah, Nasabah, PengurusDikeluarkan, Transaksi, User
from apps.bank_sampah.test_team_transfer import make_bank, make_pengurus

CODE = "pengurus_dikeluarkan"


class TeamRemoveTests(APITestCase):
    def setUp(self) -> None:
        self.bank = make_bank()
        self.owner = make_pengurus("owner@example.test", self.bank, primary=True)
        self.member = make_pengurus("member@example.test", self.bank)
        self.client = APIClient()

    def _as(self, user: User) -> APIClient:
        self.client.force_authenticate(user)
        return self.client

    def _remove(self, target: User) -> object:
        return self._as(self.owner).delete(f"/api/v1/team/{target.id}")

    def test_primary_removes_a_member_and_the_team_list_drops_them(self) -> None:
        response = self._remove(self.member)

        self.assertEqual(response.status_code, 204)  # type: ignore[attr-defined]
        members = self.client.get("/api/v1/team").json()["members"]
        self.assertEqual([m["id"] for m in members], [str(self.owner.id)])
        self.member.refresh_from_db()
        self.assertIsNone(self.member.bank_sampah)
        self.assertTrue(self.member.is_active)

    def test_removal_is_recorded_with_who_and_where(self) -> None:
        self._remove(self.member)

        record = PengurusDikeluarkan.objects.get(user=self.member)
        self.assertEqual(record.bank_sampah, self.bank)
        self.assertEqual(record.dikeluarkan_oleh, self.owner)

    def test_removed_pengurus_is_refused_with_a_machine_code(self) -> None:
        self._remove(self.member)

        for url in ("/api/v1/team", "/api/v1/bank-sampah/me", "/api/v1/transaksi"):
            with self.subTest(url=url):
                response = self._as(self.member).get(url)
                self.assertEqual(response.status_code, 403)
                body = response.json()
                self.assertEqual(body["code"], CODE)
                self.assertIn("dikeluarkan", body["error"])

    def test_removed_pengurus_cannot_use_primary_only_endpoints(self) -> None:
        self._remove(self.member)

        response = self._as(self.member).post("/api/v1/team/invite")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], CODE)

    def test_pengurus_who_never_had_a_bank_gets_no_removal_code(self) -> None:
        fresh = make_pengurus("fresh@example.test", self.bank)
        User.objects.filter(pk=fresh.pk).update(bank_sampah=None)

        response = self._as(fresh).get("/api/v1/team")

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("code", response.json())

    def test_other_forbidden_responses_keep_their_plain_shape(self) -> None:
        response = self._as(self.member).post("/api/v1/team/transfer", {"id": str(self.owner.id)})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(set(response.json()), {"error"})

    def test_transaction_history_survives_the_removal(self) -> None:
        nasabah = Nasabah.objects.create(
            bank_sampah=self.bank, nomor="NAS-1", nama="Budi", no_hp="+628111111111", alamat="A"
        )
        transaksi = Transaksi.objects.create(
            nasabah=nasabah,
            bank_sampah=self.bank,
            dicatat_oleh=self.member,
            total_nilai=Decimal(5000),
        )

        self._remove(self.member)

        transaksi.refresh_from_db()
        self.assertEqual(transaksi.dicatat_oleh, self.member)
        listed = self._as(self.owner).get("/api/v1/transaksi").json()
        ids = [row["id"] for row in listed.get("results", listed)]
        self.assertIn(str(transaksi.id), ids)

    def test_old_invite_link_cannot_bring_the_removed_pengurus_back(self) -> None:
        self._as(self.owner).post("/api/v1/team/invite")
        token = BankSampah.objects.get(pk=self.bank.pk).invite_token
        self.assertTrue(token)

        self._remove(self.member)

        self.assertEqual(BankSampah.objects.get(pk=self.bank.pk).invite_token, "")
        response = self._as(self.member).post("/api/v1/team/invite/accept", {"token": token})
        self.assertEqual(response.status_code, 400)

    def test_removed_pengurus_can_still_join_another_bank(self) -> None:
        self._remove(self.member)
        other_bank = make_bank("Mawar")
        make_pengurus("mawar@example.test", other_bank, primary=True)
        self._as(User.objects.get(email="mawar@example.test")).post("/api/v1/team/invite")
        token = BankSampah.objects.get(pk=other_bank.pk).invite_token

        response = self._as(self.member).post("/api/v1/team/invite/accept", {"token": token})

        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        self.assertEqual(self.member.bank_sampah, other_bank)
        self.assertEqual(self._as(self.member).get("/api/v1/team").status_code, 200)

    def test_cannot_remove_oneself(self) -> None:
        response = self._remove(self.owner)

        self.assertEqual(response.status_code, 400)  # type: ignore[attr-defined]
        self.assertIn("diri sendiri", response.json()["error"])  # type: ignore[attr-defined]
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.bank_sampah, self.bank)

    def test_member_of_another_bank_is_not_found(self) -> None:
        stranger = make_pengurus("stranger@example.test", make_bank("Mawar"))

        response = self._remove(stranger)

        self.assertEqual(response.status_code, 404)  # type: ignore[attr-defined]
        stranger.refresh_from_db()
        self.assertIsNotNone(stranger.bank_sampah)

    def test_unknown_and_non_pengurus_targets_are_not_found(self) -> None:
        nasabah = make_pengurus("n@example.test", self.bank, role=User.Role.NASABAH)
        for target in (uuid.uuid4(), nasabah.id):
            with self.subTest(target=target):
                response = self._as(self.owner).delete(f"/api/v1/team/{target}")
                self.assertEqual(response.status_code, 404)

    def test_non_primary_cannot_remove_anyone(self) -> None:
        response = self._as(self.member).delete(f"/api/v1/team/{self.owner.id}")

        self.assertEqual(response.status_code, 403)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.bank_sampah, self.bank)

    def test_anonymous_is_rejected(self) -> None:
        self.assertEqual(APIClient().delete(f"/api/v1/team/{self.member.id}").status_code, 401)
