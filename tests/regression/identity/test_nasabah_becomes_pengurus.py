"""Identity contracts: a Nasabah account becomes a Pengurus (PIL-542).

The Pengurus role comes only with a flow that proves the right to it: a
valid invite from a bank's team, or a bank registration that a superadmin
still has to approve. There is no "add role" endpoint.
"""

from datetime import timedelta
from typing import Any
from unittest.mock import patch

from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from api.models import BankSampah, Nasabah, Saldo, User
from apps.bank_sampah.services import ApprovalService, BankOnboardingService
from tests.regression.helpers import RegressionTestCase, logo

PENGELOLA = User.Role.PENGELOLA
NASABAH = User.Role.NASABAH
INVITE = "undangan-sah"


class NasabahBecomesPengurusTests(RegressionTestCase):
    """`self.customer` is a Nasabah of `self.bank`; `self.inviting_bank` invites."""

    def setUp(self) -> None:
        super().setUp()
        self.customer = User.objects.create_user(
            email="warga@example.com",
            nama="Warga Rajin",
            role=NASABAH,
            jenis_kelamin=User.Gender.FEMALE,
            tanggal_lahir="1995-03-10",
            no_hp="+628555555031",
            alamat="Jl. Melati No. 5",
            is_profile_complete=True,
        )
        self.member = Nasabah.objects.create(
            user=self.customer,
            bank_sampah=self.bank,
            nomor="NAS-0001",
            nama=self.customer.nama,
            alamat=self.customer.alamat,
            no_hp=self.customer.no_hp,
            email=self.customer.email,
        )
        Saldo.objects.create(nasabah=self.member)
        self.inviting_bank = BankSampah.objects.create(
            nama="Bank Sampah Mawar",
            alamat="Depok",
            kota="Depok",
            no_hp_pic="+628122222222",
            invite_token=INVITE,
            invite_token_expires=timezone.now() + timedelta(days=1),
        )

    def auth_with_role(self, user: User, role: str) -> None:
        token = AccessToken.for_user(user)
        token["role"] = role
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def accept(self, token: str = INVITE, user: User | None = None) -> Any:
        self.auth_as(user or self.customer)
        return self.client.post("/api/v1/invites/accept", {"token": token}, format="json")

    def register_bank(self, user: User | None = None) -> Any:
        self.auth_as(user or self.customer)
        return self.client.post(
            "/api/v1/onboarding/bank-sampah",
            self.bank_payload(),
            format="multipart",
        )

    @staticmethod
    def bank_payload() -> dict[str, Any]:
        return {
            "nama": "Bank Sampah Warga",
            "alamat": "Jl. Panjang Sekali No. 100",
            "kota": "Depok",
            "no_hp_pic": "081234567890",
            "foto_kegiatan": logo("kegiatan.png"),
        }

    def refreshed(self, user: User | None = None) -> User:
        user = user or self.customer
        user.refresh_from_db()
        return user

    def record_a_setoran(self) -> None:
        self.auth_as(self.user)
        response = self.client.post(
            "/api/v1/transaksi",
            {
                "nasabah_id": str(self.member.id),
                "items": [{"jenis_sampah_id": self.make_jenis(), "berat": "2.000"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def nasabah_view(self) -> tuple[Any, ...]:
        """What the customer sees as a Nasabah: membership, saldo and riwayat."""
        self.member.refresh_from_db()
        self.auth_as(self.customer)
        return (
            self.member.status,
            self.member.bank_sampah_id,
            self.client.get("/api/v1/nasabah/me/saldo").data["total_saldo"],
            self.client.get("/api/v1/nasabah/me/riwayat").data,
        )

    def test_a_nasabah_who_accepts_a_valid_invite_joins_that_banks_team(self) -> None:
        self.record_a_setoran()
        before = self.nasabah_view()

        response = self.accept()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["outcome"], "join_success")
        customer = self.refreshed()
        self.assertEqual(customer.roles, [NASABAH, PENGELOLA])
        self.assertEqual(customer.role, NASABAH)
        self.assertEqual(customer.bank_sampah_id, self.inviting_bank.id)
        self.assertFalse(customer.is_primary_pengelola)
        self.assertEqual(self.nasabah_view(), before)
        self.assertEqual(before[2], "7000.00")

        self.auth_with_role(customer, PENGELOLA)
        team = self.client.get("/api/v1/team")
        self.assertEqual(team.status_code, 200, team.data)
        self.assertIn(str(customer.id), {member["id"] for member in team.data["members"]})

    def test_an_invalid_or_expired_invite_adds_no_role(self) -> None:
        expired = BankSampah.objects.create(
            nama="Bank Sampah Lama",
            alamat="Depok",
            kota="Depok",
            no_hp_pic="+628133333333",
            invite_token="undangan-lama",
            invite_token_expires=timezone.now() - timedelta(minutes=1),
        )
        for token in ("bukan-undangan", expired.invite_token):
            with self.subTest(token=token):
                response = self.accept(token)

                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.data, {"error": "Tautan undangan tidak valid atau sudah kedaluwarsa"}
                )
                customer = self.refreshed()
                self.assertEqual(customer.roles, [NASABAH])
                self.assertIsNone(customer.bank_sampah_id)

    def test_an_account_already_on_a_team_cannot_join_another(self) -> None:
        self.customer.roles = [NASABAH, PENGELOLA]
        self.customer.bank_sampah = self.bank
        self.customer.save(update_fields=["roles", "bank_sampah", "updated_at"])

        response = self.accept()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"error": "Akun ini sudah tergabung dengan bank sampah"})
        self.assertEqual(self.refreshed().bank_sampah_id, self.bank.id)

    def test_a_nasabah_who_registers_a_bank_is_a_pengurus_only_once_it_is_approved(self) -> None:
        self.record_a_setoran()
        before = self.nasabah_view()

        response = self.register_bank()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], BankSampah.Status.PENDING)
        customer = self.refreshed()
        self.assertEqual(customer.roles, [NASABAH, PENGELOLA])
        self.assertEqual(customer.role, NASABAH)
        self.assertTrue(customer.is_primary_pengelola)
        self.assertEqual(self.nasabah_view(), before)

        self.auth_with_role(customer, PENGELOLA)
        self.assertEqual(self.client.get("/api/v1/nasabah").status_code, 403)

        admin = User.objects.create_user(email="admin@example.com", role=User.Role.SUPERADMIN)
        assert customer.bank_sampah is not None
        ApprovalService.approve(customer.bank_sampah, admin)

        self.assertEqual(self.client.get("/api/v1/nasabah").status_code, 200)

    def test_a_bank_registration_that_fails_midway_adds_no_role(self) -> None:
        User.objects.create_user(email="admin@example.com", role=User.Role.SUPERADMIN)

        with (
            patch("apps.bank_sampah.services.queue_push", side_effect=RuntimeError("push down")),
            self.assertRaises(RuntimeError),
        ):
            BankOnboardingService.register_bank_sampah(self.customer, self.bank_payload())

        customer = self.refreshed()
        self.assertEqual(customer.roles, [NASABAH])
        self.assertIsNone(customer.bank_sampah_id)
        self.assertFalse(BankSampah.objects.filter(nama="Bank Sampah Warga").exists())

    def test_an_account_that_is_neither_nasabah_nor_pengurus_cannot_become_one(self) -> None:
        admin = User.objects.create_user(
            email="admin@example.com",
            nama="Admin",
            role=User.Role.SUPERADMIN,
            is_profile_complete=True,
        )

        accepted = self.accept(user=admin)
        registered = self.register_bank(user=admin)

        self.assertEqual(accepted.status_code, 403)
        self.assertEqual(registered.status_code, 403)
        admin = self.refreshed(admin)
        self.assertEqual(admin.roles, [User.Role.SUPERADMIN])
        self.assertIsNone(admin.bank_sampah_id)
        for service_call in (
            lambda: BankOnboardingService.accept_invite(admin, INVITE),
            lambda: BankOnboardingService.register_bank_sampah(admin, self.bank_payload()),
        ):
            with self.assertRaisesRegex(PermissionError, "pengelola atau nasabah"):
                service_call()
