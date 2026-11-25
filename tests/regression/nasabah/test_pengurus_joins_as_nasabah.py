"""Nasabah contracts: a Pengurus account joins a bank sampah as a Nasabah (PIL-541).

Joining is the only way a Pengurus gets the Nasabah role: there is no
"add role" endpoint, the role comes with a membership application.
"""

from typing import Any

from api.models import BankSampah, Nasabah, User
from tests.regression.helpers import RegressionTestCase

PENGELOLA = User.Role.PENGELOLA
NASABAH = User.Role.NASABAH


class PengurusJoinsAsNasabahTests(RegressionTestCase):
    """`self.user` is the Pengurus Utama of `self.bank`; `self.other_bank` is a second unit."""

    def setUp(self) -> None:
        super().setUp()
        self.user.alamat = "Jl. Kenanga No. 7"
        self.user.no_hp = "+628555555021"
        self.user.save(update_fields=["alamat", "no_hp", "updated_at"])
        self.other_bank = BankSampah.objects.create(
            nama="Bank Sampah Mawar", alamat="Depok", kota="Depok", no_hp_pic="+628122222222"
        )

    def apply(self, bank: BankSampah, user: User | None = None) -> Any:
        self.auth_as(user or self.user)
        return self.client.post(
            "/api/v1/onboarding/nasabah", {"bank_sampah_id": str(bank.id)}, format="json"
        )

    def roles(self, user: User | None = None) -> list[str]:
        user = user or self.user
        user.refresh_from_db()
        roles: list[str] = user.roles
        return roles

    def test_a_pengurus_can_join_its_own_bank_and_another_as_a_nasabah(self) -> None:
        for bank in (self.bank, self.other_bank):
            with self.subTest(bank=bank.nama):
                response = self.apply(bank)

                self.assertEqual(response.status_code, 201, response.data)
                self.assertEqual(response.data["status"], Nasabah.Status.PENDING)
                # Applying doesn't switch the session: the app stays on the
                # Pengurus dashboard until the user switches role (PIL-540).
                self.assertEqual(response.data["next_step"], "dashboard")

        self.assertEqual(self.roles(), [PENGELOLA, NASABAH])
        self.assertEqual(self.user.role, PENGELOLA)
        self.assertEqual(self.user.bank_sampah_id, self.bank.id)
        self.assertTrue(self.user.is_primary_pengelola)
        self.assertEqual(
            set(Nasabah.objects.filter(user=self.user).values_list("bank_sampah_id", flat=True)),
            {self.bank.id, self.other_bank.id},
        )
        self.auth_as(self.user)
        self.assertEqual(self.client.get("/api/v1/nasabah").status_code, 200)

    def test_the_new_membership_waits_for_that_banks_pengurus(self) -> None:
        pengurus_b = self.make_user("pengurus-b@example.com", PENGELOLA, self.other_bank)
        self.apply(self.other_bank)
        member = Nasabah.objects.get(user=self.user, bank_sampah=self.other_bank)

        self.auth_as(self.user)
        refused = self.client.post(f"/api/v1/nasabah/{member.id}/approve", {}, format="json")
        self.auth_as(pengurus_b)
        approved = self.client.post(f"/api/v1/nasabah/{member.id}/approve", {}, format="json")

        self.assertEqual(refused.status_code, 404)
        self.assertEqual(approved.status_code, 200, approved.data)
        member.refresh_from_db()
        self.assertEqual(member.status, Nasabah.Status.APPROVED)

    def test_applying_twice_to_the_same_bank_is_refused(self) -> None:
        first = self.apply(self.other_bank)
        second = self.apply(self.other_bank)

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(
            second.data, {"error": "Anda sudah terdaftar sebagai nasabah di bank sampah ini"}
        )
        self.assertEqual(Nasabah.objects.filter(user=self.user).count(), 1)
        self.assertEqual(self.roles(), [PENGELOLA, NASABAH])

    def test_an_application_refused_up_front_adds_no_role(self) -> None:
        pending_bank = BankSampah.objects.create(
            nama="Bank Sampah Baru",
            alamat="Depok",
            kota="Depok",
            no_hp_pic="+628133333333",
            status=BankSampah.Status.PENDING,
        )

        response = self.apply(pending_bank)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data, {"error": "Bank sampah tidak ditemukan atau belum tersedia"}
        )
        self.assertEqual(self.roles(), [PENGELOLA])

    def test_a_pengurus_without_an_address_gets_no_role(self) -> None:
        self.user.alamat = ""
        self.user.save(update_fields=["alamat", "updated_at"])

        response = self.apply(self.other_bank)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data, {"error": "Lengkapi alamat pada profil Anda terlebih dahulu"}
        )
        self.assertEqual(self.roles(), [PENGELOLA])

    def test_an_application_that_fails_while_saving_rolls_the_role_back(self) -> None:
        # The bank holds one row numbered NAS-0002, so every number derived
        # from its row count collides and the save gives up after the role
        # was already granted.
        Nasabah.objects.create(
            bank_sampah=self.other_bank,
            nomor="NAS-0002",
            nama="Lama",
            no_hp="+628111111111",
            email="lama@example.com",
            alamat="Jl. A",
        )

        response = self.apply(self.other_bank)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"error": "Gagal membuat nomor nasabah, silakan coba lagi"})
        self.assertEqual(self.roles(), [PENGELOLA])
        self.assertFalse(Nasabah.objects.filter(user=self.user).exists())

    def test_a_pengurus_with_an_unfinished_profile_is_refused(self) -> None:
        newcomer = User.objects.create_user(
            email="baru@example.com", nama="Baru", alamat="Jl. Baru", no_hp="+628555555024"
        )

        response = self.apply(self.other_bank, newcomer)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.roles(newcomer), [PENGELOLA])

    def test_a_nasabah_account_keeps_its_single_role(self) -> None:
        customer = User.objects.create_user(
            email="warga@example.com",
            nama="Warga",
            role=NASABAH,
            no_hp="+628555555022",
            alamat="Jl. Melati No. 5",
            is_profile_complete=True,
        )

        response = self.apply(self.other_bank, customer)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["next_step"], "nasabah_dashboard")
        self.assertEqual(self.roles(customer), [NASABAH])

    def test_an_account_that_is_neither_nasabah_nor_pengurus_is_refused(self) -> None:
        admin = User.objects.create_user(
            email="admin@example.com",
            nama="Admin",
            role=User.Role.SUPERADMIN,
            no_hp="+628555555023",
            alamat="Jl. Admin",
            is_profile_complete=True,
        )

        response = self.apply(self.other_bank, admin)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.roles(admin), [User.Role.SUPERADMIN])
        self.assertFalse(Nasabah.objects.filter(user=admin).exists())
