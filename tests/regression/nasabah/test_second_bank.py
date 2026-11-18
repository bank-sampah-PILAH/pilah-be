"""Nasabah contracts: an account already approved at one bank applies to another (PIL-539)."""

from typing import Any

from api.models import BankSampah, Nasabah, Saldo, User
from tests.regression.helpers import RegressionTestCase


class SecondBankApplicationTests(RegressionTestCase):
    """Bank A is `self.bank` (its pengurus is `self.user`); Bank B is a second unit."""

    def setUp(self) -> None:
        super().setUp()
        self.bank_b = BankSampah.objects.create(
            nama="Bank Sampah Mawar", alamat="Depok", kota="Depok", no_hp_pic="+628122222222"
        )
        self.pengurus_b = self.make_user("pengurus-b@example.com", User.Role.PENGELOLA, self.bank_b)
        self.customer = User.objects.create_user(
            email="dua-bank@example.com",
            nama="Nasabah Dua Bank",
            role=User.Role.NASABAH,
            jenis_kelamin=User.Gender.FEMALE,
            tanggal_lahir="1998-05-20",
            no_hp="+628555555011",
            alamat="Jl. Melati No. 5",
            is_profile_complete=True,
        )
        self.member_a = Nasabah.objects.create(
            user=self.customer,
            bank_sampah=self.bank,
            nomor="NAS-0001",
            nama=self.customer.nama,
            alamat=self.customer.alamat,
            no_hp=self.customer.no_hp,
            email=self.customer.email,
        )
        Saldo.objects.create(nasabah=self.member_a)

    def apply_to_bank_b(self) -> Any:
        self.auth_as(self.customer)
        return self.client.post(
            "/api/v1/onboarding/nasabah", {"bank_sampah_id": str(self.bank_b.id)}, format="json"
        )

    def saldo(self, member: Nasabah | None = None) -> Any:
        self.auth_as(self.customer)
        query = {"keanggotaan_id": str(member.id)} if member else {}
        return self.client.get("/api/v1/nasabah/me/saldo", query)

    def test_applying_to_a_second_bank_waits_while_the_first_stays_open(self) -> None:
        applied = self.apply_to_bank_b()

        self.assertEqual(applied.status_code, 201, applied.data)
        member_b = Nasabah.objects.get(user=self.customer, bank_sampah=self.bank_b)
        self.assertEqual(member_b.status, Nasabah.Status.PENDING)
        self.assertEqual(self.saldo().status_code, 200)
        self.assertEqual(self.saldo(self.member_a).status_code, 200)
        self.assertEqual(self.saldo(member_b).status_code, 403)

    def test_only_the_second_banks_pengurus_can_decide_the_application(self) -> None:
        self.apply_to_bank_b()
        member_b = Nasabah.objects.get(user=self.customer, bank_sampah=self.bank_b)

        self.auth_as(self.user)
        for decision in ("approve", "reject"):
            with self.subTest(decision=decision):
                response = self.client.post(
                    f"/api/v1/nasabah/{member_b.id}/{decision}", {}, format="json"
                )
                self.assertEqual(response.status_code, 404)
        member_b.refresh_from_db()
        self.assertEqual(member_b.status, Nasabah.Status.PENDING)

        self.auth_as(self.pengurus_b)
        approved = self.client.post(f"/api/v1/nasabah/{member_b.id}/approve", {}, format="json")

        self.assertEqual(approved.status_code, 200, approved.data)
        member_b.refresh_from_db()
        self.assertEqual(member_b.status, Nasabah.Status.APPROVED)
