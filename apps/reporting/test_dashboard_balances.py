from decimal import Decimal

from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, Saldo, User


class DashboardBalanceTests(APITestCase):
    url = "/api/v1/dashboard/stats"

    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(nama="Melati", no_hp_pic="081200")
        self.manager = User.objects.create_user(
            email="balances@example.test",
            nama="Pengurus",
            role=User.Role.PENGELOLA,
            bank_sampah=self.bank,
            is_profile_complete=True,
        )
        self.client.force_authenticate(self.manager)

    def balance(
        self,
        amount: str,
        *,
        bank: BankSampah | None = None,
        active: bool = True,
        nomor: str = "001",
    ) -> Saldo:
        member = Nasabah.objects.create(
            bank_sampah=bank or self.bank,
            nomor=nomor,
            nama="Demo",
            no_hp=f"0812{nomor}",
            email=f"{nomor}@example.test",
            alamat="Depok",
            is_active=active,
        )
        return Saldo.objects.create(nasabah=member, total_saldo=Decimal(amount))

    def test_current_savings_include_inactive_members_and_ignore_month_filter(self) -> None:
        self.balance("12000")
        self.balance("3000", active=False, nomor="002")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_saldo_nasabah"], "15000")
        self.assertEqual(response.data["total_nilai_bulan_ini"], 0)
        self.assertIsNone(response.data["kas_operasional"])
        self.assertEqual(response.data["kas_operasional_status"], "belum_tersedia")

    def test_empty_bank_has_real_zero_savings_but_unknown_cash(self) -> None:
        data = self.client.get(self.url).data
        self.assertEqual(data["total_saldo_nasabah"], "0")
        self.assertIsNone(data["kas_operasional"])

    def test_foreign_bank_and_forged_query_cannot_change_scope(self) -> None:
        other = BankSampah.objects.create(nama="Other", no_hp_pic="081299")
        self.balance("500")
        self.balance("900000", bank=other)
        response = self.client.get(self.url, {"bank_sampah_id": str(other.id)})
        self.assertEqual(response.data["total_saldo_nasabah"], "500")

    def test_legacy_fraction_is_truncated_without_mutating_balance(self) -> None:
        row = self.balance("1234.99")
        self.assertEqual(self.client.get(self.url).data["total_saldo_nasabah"], "1234")
        row.refresh_from_db()
        self.assertEqual(row.total_saldo, Decimal("1234.99"))

    def test_negative_legacy_balance_is_not_hidden(self) -> None:
        self.balance("-100")
        self.assertEqual(self.client.get(self.url).data["total_saldo_nasabah"], "-100")

    def test_response_exposes_aggregate_only(self) -> None:
        self.balance("100")
        data = self.client.get(self.url).data
        self.assertEqual(
            set(data),
            {
                "bank_sampah_nama",
                "pengelola_nama",
                "periode",
                "nasabah_aktif",
                "transaksi_bulan_ini",
                "total_sampah_kg_bulan_ini",
                "total_nilai_bulan_ini",
                "total_saldo_nasabah",
                "kas_operasional",
                "kas_operasional_status",
            },
        )

    def test_unauthenticated_or_invalid_token_cannot_read_balances(self) -> None:
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid")
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_wrong_role_incomplete_profile_and_inactive_bank_are_denied(self) -> None:
        for changes in ({"role": User.Role.NASABAH}, {"is_profile_complete": False}):
            with self.subTest(changes=changes):
                original = {key: getattr(self.manager, key) for key in changes}
                for key, value in changes.items():
                    setattr(self.manager, key, value)
                self.assertEqual(self.client.get(self.url).status_code, 403)
                for key, value in original.items():
                    setattr(self.manager, key, value)
        self.bank.is_active = False
        self.bank.save()
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_balances_are_read_only(self) -> None:
        row = self.balance("100")
        self.assertEqual(
            self.client.post(self.url, {"total_saldo_nasabah": "999"}).status_code, 405
        )
        row.refresh_from_db()
        self.assertEqual(row.total_saldo, Decimal(100))

    def test_private_financial_response_is_not_cacheable(self) -> None:
        self.assertEqual(self.client.get(self.url)["Cache-Control"], "no-store, private")
