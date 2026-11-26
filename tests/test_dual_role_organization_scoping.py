"""A dual-role account's reads follow its active role's organization.

Every existing multirole test gives the account one bank sampah: it is the
pengurus and the nasabah of the same Bank A. The case CPBI-02 actually
describes is two organizations at once, a pengurus of one bank who saves at
another, and nothing covered it. These tests pin that: switching the active
role has to move the organization with it, not only the permission.
"""

from django.test import TestCase
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from api.models import BankSampah, Nasabah, Pencairan, User
from apps.ledger.views import PencairanViewSet


class DualRoleOrganizationScopingTest(TestCase):
    def setUp(self) -> None:
        self.bank_a = BankSampah.objects.create(nama="Bank A", no_hp_pic="+628123456781")
        self.bank_b = BankSampah.objects.create(nama="Bank B", no_hp_pic="+628123456782")
        # Pengurus of Bank A, and a nasabah saving at Bank B.
        self.user = User.objects.create_user(
            email="dual@example.com",
            bank_sampah=self.bank_a,
            role=User.Role.PENGELOLA,
            roles=[User.Role.PENGELOLA, User.Role.NASABAH],
            is_profile_complete=True,
        )
        self.membership_b = self._member(self.bank_b, "NAS-B1", "Dual", user=self.user)
        self.customer_a = self._member(self.bank_a, "NAS-A1", "Customer A")
        self.stranger_b = self._member(self.bank_b, "NAS-B2", "Stranger B")

    _next_phone = 0

    def _member(
        self, bank: BankSampah, nomor: str, nama: str, user: User | None = None
    ) -> Nasabah:
        # no_hp is unique per bank sampah, so each member needs its own.
        DualRoleOrganizationScopingTest._next_phone += 1
        return Nasabah.objects.create(
            user=user,
            bank_sampah=bank,
            nomor=nomor,
            nama=nama,
            alamat="Jl. Test",
            no_hp=f"+62812345{self._next_phone:04d}",
            email=f"{nomor.lower()}@example.com",
        )

    def _pencairan(self, member: Nasabah) -> Pencairan:
        return Pencairan.objects.create(
            nasabah=member,
            bank_sampah=member.bank_sampah,
            dicatat_oleh=self.user,
            nominal=100,
            metode="tunai",
            saldo_sebelum=100,
            saldo_sesudah=0,
        )

    def request(self, role: str) -> Request:
        request = Request(APIRequestFactory().get("/"))
        request.user = self.user
        request.auth = {"role": role}
        return request

    def _pencairan_ids(self, role: str) -> set[object]:
        view = PencairanViewSet()
        view.request = self.request(role)
        return set(view.get_queryset().values_list("pk", flat=True))

    def test_nasabah_mode_reads_only_the_accounts_own_savings_not_the_bank_it_manages(
        self,
    ) -> None:
        own_b = self._pencairan(self.membership_b)
        managed_a = self._pencairan(self.customer_a)
        stranger_b = self._pencairan(self.stranger_b)

        self.assertEqual(self._pencairan_ids("nasabah"), {own_b.pk})
        self.assertNotIn(managed_a.pk, self._pencairan_ids("nasabah"))
        self.assertNotIn(stranger_b.pk, self._pencairan_ids("nasabah"))

    def test_pengelola_mode_reads_its_own_bank_and_not_the_account_savings_elsewhere(
        self,
    ) -> None:
        own_b = self._pencairan(self.membership_b)
        managed_a = self._pencairan(self.customer_a)
        self._pencairan(self.stranger_b)

        # Managing Bank A must not pull in what this same person saved at Bank B,
        # even though both rows belong to the one account.
        self.assertEqual(self._pencairan_ids("pengelola"), {managed_a.pk})
        self.assertNotIn(own_b.pk, self._pencairan_ids("pengelola"))
