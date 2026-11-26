"""The server refuses a role or a bank sampah the active session has no claim to.

PIL-251 pins the permission classes themselves and rejects a token whose role
the account does not own. What it does not pin is an endpoint answering a
two-organization account: a pengurus of Bank A who also saves at Bank B. These
tests drive real endpoints over HTTP with each active role, and keep the
single-role account honest alongside them.
"""

from typing import Any

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from api.models import BankSampah, Nasabah, User

NASABAH_LIST = "/api/v1/nasabah"


class DualRoleEndpointRefusalTest(TestCase):
    def setUp(self) -> None:
        self.bank_a = BankSampah.objects.create(nama="Bank A", no_hp_pic="+628123456781")
        self.bank_b = BankSampah.objects.create(nama="Bank B", no_hp_pic="+628123456782")
        self.user = User.objects.create_user(
            email="dual-http@example.com",
            bank_sampah=self.bank_a,
            role=User.Role.PENGELOLA,
            roles=[User.Role.PENGELOLA, User.Role.NASABAH],
            is_profile_complete=True,
        )
        self.customer_a = self._member(self.bank_a, "NAS-A1", "Customer A", "+628100000001")
        self.own_b = self._member(
            self.bank_b, "NAS-B1", "Dual", "+628100000002", user=self.user
        )
        self.stranger_b = self._member(self.bank_b, "NAS-B2", "Stranger B", "+628100000003")

    def _member(
        self,
        bank: BankSampah,
        nomor: str,
        nama: str,
        no_hp: str,
        user: User | None = None,
    ) -> Nasabah:
        return Nasabah.objects.create(
            user=user,
            bank_sampah=bank,
            nomor=nomor,
            nama=nama,
            alamat="Jl. Test",
            no_hp=no_hp,
            email=f"{nomor.lower()}@example.com",
        )

    def _client(self, user: User, role: str) -> APIClient:
        token = AccessToken.for_user(user)
        token["role"] = role
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    @staticmethod
    def _names(payload: Any) -> set[str]:
        rows = payload["results"] if isinstance(payload, dict) else payload
        return {row["nama"] for row in rows}

    def test_nasabah_session_is_refused_the_pengurus_customer_list(self) -> None:
        # Same account, same bank sampah to manage. Only the active role differs.
        self.assertEqual(self._client(self.user, "nasabah").get(NASABAH_LIST).status_code, 403)

    def test_pengelola_session_lists_only_its_own_bank(self) -> None:
        response = self._client(self.user, "pengelola").get(NASABAH_LIST)

        self.assertEqual(response.status_code, 200)
        names = self._names(response.data)
        self.assertIn("Customer A", names)
        # Bank B holds this account's own membership and a stranger's. Managing
        # Bank A must reach neither.
        self.assertNotIn("Dual", names)
        self.assertNotIn("Stranger B", names)

    def test_single_role_pengurus_is_unaffected(self) -> None:
        solo = User.objects.create_user(
            email="solo@example.com",
            bank_sampah=self.bank_a,
            role=User.Role.PENGELOLA,
            roles=[User.Role.PENGELOLA],
            is_profile_complete=True,
        )
        response = self._client(solo, "pengelola").get(NASABAH_LIST)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._names(response.data), {"Customer A"})
        # A role the account does not own is refused even though the bank is its own.
        self.assertEqual(self._client(solo, "nasabah").get(NASABAH_LIST).status_code, 401)
