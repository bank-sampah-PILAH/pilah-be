from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from api.models import BankSampah, Nasabah, Saldo, Transaksi, User


class NasabahHomeTests(APITestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(
            nama="Melati", no_hp_pic="08123456789", wa_gateway_token="private-token"
        )
        self.user = User.objects.create_user(
            email="siti@example.test", nama="Siti", role=User.Role.NASABAH
        )
        self.member = Nasabah.objects.create(
            user=self.user,
            bank_sampah=self.bank,
            nomor="001",
            nama="Siti",
            alamat="Depok",
            no_hp="08123456789",
        )
        self.manager = User.objects.create_user(email="manager@example.test", nama="Manager")
        self.client.force_authenticate(self.user)
        self.url = "/api/v1/nasabah/me/beranda"

    def test_home_returns_own_membership_balance_and_safe_bank(self) -> None:
        Saldo.objects.create(nasabah=self.member, total_saldo=Decimal("12500.50"))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["saldo"]["total_saldo"], "12500.50")
        self.assertEqual(response.data["keanggotaan"]["id"], str(self.member.id))
        self.assertEqual(response.data["bank_sampah"]["nama"], "Melati")
        self.assertNotIn("wa_gateway_token", response.data["bank_sampah"])
        self.assertEqual(response.data["user"]["nama"], "Siti")

    def test_empty_home_does_not_create_balance_on_read(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["saldo"]["total_saldo"], "0.00")
        self.assertEqual(response.data["aktivitas_terbaru"], [])
        self.assertFalse(Saldo.objects.exists())

    def test_membership_and_bank_must_both_be_active(self) -> None:
        for status in (Nasabah.Status.PENDING, Nasabah.Status.REJECTED):
            with self.subTest(status=status):
                self.member.status = status
                self.member.save()
                self.assertEqual(self.client.get(self.url).status_code, 403)
        self.member.status = Nasabah.Status.APPROVED
        self.member.is_active = False
        self.member.save()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.member.is_active = True
        self.member.save()
        for bank_status, active in (("pending", True), ("rejected", True), ("active", False)):
            self.bank.status, self.bank.is_active = bank_status, active
            self.bank.save()
            self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_authentication_and_nasabah_role_required(self) -> None:
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.client.force_authenticate(self.manager)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data, {"error": "Endpoint ini hanya untuk nasabah"})

    def test_no_membership_is_forbidden(self) -> None:
        self.member.delete()
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_membership_selection_cannot_access_another_user(self) -> None:
        other = User.objects.create_user(
            email="other@example.test", nama="Other", role=User.Role.NASABAH
        )
        member = Nasabah.objects.create(
            user=other,
            bank_sampah=self.bank,
            nomor="002",
            nama="Other",
            alamat="Depok",
            no_hp="089999999",
        )
        self.assertEqual(
            self.client.get(self.url, {"keanggotaan_id": str(member.id)}).status_code, 404
        )
        for identifier in ("invalid", ""):
            with self.subTest(identifier=identifier):
                response = self.client.get(self.url, {"keanggotaan_id": identifier})
                self.assertEqual(response.status_code, 422)

    def test_multiple_memberships_require_explicit_selection(self) -> None:
        bank = BankSampah.objects.create(nama="Mawar", no_hp_pic="0899999")
        member = Nasabah.objects.create(
            user=self.user,
            bank_sampah=bank,
            nomor="001",
            nama="Siti",
            alamat="Depok",
            no_hp="08123456789",
        )
        self.assertEqual(self.client.get(self.url).status_code, 422)
        response = self.client.get(self.url, {"keanggotaan_id": str(member.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["bank_sampah"]["nama"], "Mawar")

    def test_history_is_paginated_ordered_and_scoped(self) -> None:
        for value in range(7):
            Transaksi.objects.create(
                nasabah=self.member,
                bank_sampah=self.bank,
                dicatat_oleh=self.manager,
                total_nilai=value,
                tanggal=timezone.now() + timedelta(minutes=value),
            )
        other = Nasabah.objects.create(
            bank_sampah=self.bank, nomor="002", nama="Other", alamat="Depok", no_hp="089999999"
        )
        Transaksi.objects.create(
            nasabah=other, bank_sampah=self.bank, dicatat_oleh=self.manager, total_nilai=999
        )
        home = self.client.get(self.url)
        self.assertEqual(home.status_code, 200)
        self.assertEqual(len(home.data["aktivitas_terbaru"]), 5)
        response = self.client.get("/api/v1/nasabah/me/riwayat", {"page_size": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 7)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertEqual(response.data["results"][0]["total_nilai"], "6.00")
        self.assertIsNotNone(response.data["next"])

    def test_detail_endpoints_use_same_membership_gate(self) -> None:
        for path in ("saldo", "bank-sampah", "riwayat"):
            with self.subTest(path=path):
                url = f"/api/v1/nasabah/me/{path}"
                self.assertEqual(self.client.get(url).status_code, 200)
                self.member.is_active = False
                self.member.save()
                self.assertEqual(self.client.get(url).status_code, 403)
                self.member.is_active = True
                self.member.save()

    def test_home_is_read_only(self) -> None:
        for path in ("beranda", "saldo", "bank-sampah", "riwayat"):
            for method in (
                self.client.post,
                self.client.put,
                self.client.patch,
                self.client.delete,
            ):
                with self.subTest(path=path, method=method.__name__):
                    self.assertEqual(method(f"/api/v1/nasabah/me/{path}", {}).status_code, 405)

    def test_selected_inactive_membership_is_forbidden(self) -> None:
        for status in (Nasabah.Status.PENDING, Nasabah.Status.REJECTED):
            self.member.status = status
            self.member.save()
            for path in ("beranda", "saldo", "bank-sampah", "riwayat"):
                response = self.client.get(
                    f"/api/v1/nasabah/me/{path}", {"keanggotaan_id": str(self.member.id)}
                )
                self.assertEqual(response.status_code, 403)

    def test_selected_bank_scopes_balance_and_history(self) -> None:
        bank = BankSampah.objects.create(nama="Mawar", no_hp_pic="0899999")
        member = Nasabah.objects.create(
            user=self.user,
            bank_sampah=bank,
            nomor="001",
            nama="Siti",
            alamat="Depok",
            no_hp="08123456789",
        )
        Saldo.objects.create(nasabah=self.member, total_saldo=100)
        Saldo.objects.create(nasabah=member, total_saldo=200)
        Transaksi.objects.create(
            nasabah=self.member, bank_sampah=self.bank, dicatat_oleh=self.manager, total_nilai=100
        )
        selected = {"keanggotaan_id": str(member.id)}
        response = self.client.get(self.url, selected)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["saldo"]["total_saldo"], "200.00")
        self.assertEqual(response.data["aktivitas_terbaru"], [])
        response = self.client.get("/api/v1/nasabah/me/riwayat", selected)
        self.assertEqual(response.data["count"], 0)

    def test_jwt_and_deactivated_account(self) -> None:
        self.client.force_authenticate(None)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_equal_transaction_dates_use_creation_time_before_uuid(self) -> None:
        timestamp = timezone.now()
        expected: list[str] = []
        for index in range(7):
            transaction = Transaksi.objects.create(
                id=UUID(int=100 - index),
                nasabah=self.member,
                bank_sampah=self.bank,
                dicatat_oleh=self.manager,
                total_nilai=index,
                tanggal=timestamp,
            )
            Transaksi.objects.filter(pk=transaction.pk).update(
                created_at=timestamp + timedelta(seconds=index)
            )
            expected.insert(0, str(transaction.id))
        home = self.client.get(self.url)
        self.assertEqual(home.status_code, 200)
        self.assertEqual([item["id"] for item in home.data["aktivitas_terbaru"]], expected[:5])
        actual: list[str] = []
        for page in range(1, 5):
            response = self.client.get("/api/v1/nasabah/me/riwayat", {"page_size": 2, "page": page})
            self.assertEqual(response.status_code, 200)
            actual.extend(item["id"] for item in response.data["results"])
        self.assertEqual(actual, expected)
        # UUID is only the final stable fallback when both timestamps match.
        Transaksi.objects.all().update(created_at=timestamp)
        response = self.client.get("/api/v1/nasabah/me/riwayat")
        self.assertEqual(
            [item["id"] for item in response.data["results"]], list(reversed(expected))
        )

    def test_default_and_selected_membership_share_eligibility_rules(self) -> None:
        cases = [
            ("approved", True, "active", True, 200),
            ("pending", True, "active", True, 403),
            ("rejected", True, "active", True, 403),
            ("approved", False, "active", True, 403),
            ("approved", True, "pending", True, 403),
            ("approved", True, "rejected", True, 403),
            ("approved", True, "active", False, 403),
        ]
        for status, active, bank_status, bank_active, expected in cases:
            self.member.status, self.member.is_active = status, active
            self.member.save()
            self.bank.status, self.bank.is_active = bank_status, bank_active
            self.bank.save()
            for path in ("beranda", "saldo", "bank-sampah", "riwayat"):
                for query in ({}, {"keanggotaan_id": str(self.member.id)}):
                    with self.subTest(
                        case=(status, active, bank_status, bank_active), path=path, query=query
                    ):
                        response = self.client.get(f"/api/v1/nasabah/me/{path}", query)
                        self.assertEqual(response.status_code, expected)

    def test_missing_and_foreign_memberships_share_generic_404(self) -> None:
        other = User.objects.create_user(
            email="foreign@example.test", nama="Other", role=User.Role.NASABAH
        )
        foreign = Nasabah.objects.create(
            user=other,
            bank_sampah=self.bank,
            nomor="002",
            nama="Other",
            alamat="Depok",
            no_hp="08999",
            status=Nasabah.Status.REJECTED,
        )
        for identifier in (str(UUID(int=1)), str(foreign.id)):
            response = self.client.get(self.url, {"keanggotaan_id": identifier})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.data, {"error": "Resource tidak ditemukan"})
