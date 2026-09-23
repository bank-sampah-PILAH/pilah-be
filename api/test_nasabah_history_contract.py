from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, Transaksi, User


class NasabahHistoryContractTests(APITestCase):
    url = "/api/v1/nasabah/me/riwayat"

    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(nama="Melati", no_hp_pic="08123456789")
        self.user = User.objects.create_user(
            email="history@example.test", nama="Siti", role=User.Role.NASABAH
        )
        self.member = Nasabah.objects.create(
            user=self.user,
            bank_sampah=self.bank,
            nomor="001",
            nama="Siti",
            alamat="Depok",
            no_hp="08123456789",
        )
        self.manager = User.objects.create_user(email="staff@example.test", nama="Staff")
        self.client.force_authenticate(self.user)

    def test_empty_history_has_pagination_contract(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "count": 0,
                "next": None,
                "previous": None,
                "results": [],
            },
        )

    def test_all_pages_preserve_order_and_decimal_amounts(self) -> None:
        transactions = [
            Transaksi.objects.create(
                nasabah=self.member,
                bank_sampah=self.bank,
                dicatat_oleh=self.manager,
                total_nilai="12500.50",
                tanggal=timezone.now() + timedelta(minutes=i),
            )
            for i in range(3)
        ]
        rows = []
        for number in (1, 2, 3):
            response = self.client.get(self.url, {"page_size": 1, "page": number})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["count"], 3)
            rows.extend(response.data["results"])
        self.assertEqual(
            [row["id"] for row in rows], [str(item.id) for item in reversed(transactions)]
        )
        self.assertEqual(rows[0]["total_nilai"], "12500.50")
        self.assertEqual(set(rows[0]), {"id", "tanggal", "tipe", "total_nilai"})
        self.assertIsNone(response.data["next"])

    def test_customer_cannot_override_owner_with_query_parameters(self) -> None:
        other = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="002",
            nama="Other",
            alamat="Depok",
            no_hp="08999999",
        )
        Transaksi.objects.create(
            nasabah=other,
            bank_sampah=self.bank,
            dicatat_oleh=self.manager,
            total_nilai=999,
        )
        response = self.client.get(self.url, {"nasabah_id": str(other.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])

    def test_anonymous_cannot_read_history(self) -> None:
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)
