"""Dashboard contracts: stats, recent transactions, reporting, WA template."""

from datetime import datetime
from decimal import Decimal

from django.utils import timezone

from api.models import DetailTransaksi, Transaksi
from tests.regression.helpers import RegressionTestCase


class DashboardRegressionTests(RegressionTestCase):
    def test_stats_contract(self) -> None:
        response = self.client.get("/api/v1/dashboard/stats")
        self.assertEqual(response.status_code, 200)
        for key in (
            "bank_sampah_nama",
            "pengelola_nama",
            "periode",
            "nasabah_aktif",
            "transaksi_bulan_ini",
            "total_sampah_kg_bulan_ini",
            "total_nilai_bulan_ini",
        ):
            self.assertIn(key, response.data)

    def test_stats_reflect_new_data(self) -> None:
        self.make_transaksi()
        response = self.client.get("/api/v1/dashboard/stats")
        self.assertGreaterEqual(response.data["nasabah_aktif"], 1)
        self.assertGreaterEqual(response.data["transaksi_bulan_ini"], 1)

    def test_recent_transactions_contract(self) -> None:
        response = self.client.get("/api/v1/dashboard/recent-transactions")
        self.assertEqual(response.status_code, 200)
        self.assertIn("transactions", response.data)
        self.assertLessEqual(len(response.data["transactions"]), 3)

    def test_operational_trends_returns_aligned_zero_filled_periods(self) -> None:
        transaction_id = self.make_transaksi()
        Transaksi.objects.filter(pk=transaction_id).update(
            tanggal=timezone.make_aware(datetime(2024, 1, 3, 12))
        )
        response = self.client.get(
            "/api/v1/dashboard/operational-trends",
            {"start_date": "2024-01-01", "end_date": "2024-01-14", "granularity": "week"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["granularity"], "week")
        self.assertEqual([b["period_start"] for b in response.data["buckets"]], ["2024-01-01", "2024-01-08"])
        self.assertEqual(response.data["buckets"][0]["setoran_count"], 1)
        self.assertEqual(response.data["buckets"][0]["pencairan_count"], 0)
        self.assertEqual(response.data["buckets"][1]["setoran_total_nilai"], "0.00")

    def test_waste_categories_aggregates_weight_and_distinct_deposits(self) -> None:
        transaction_id = self.make_transaksi()
        Transaksi.objects.filter(pk=transaction_id).update(
            tanggal=timezone.make_aware(datetime.combine(timezone.localdate(), datetime.min.time()))
        )
        transaction = Transaksi.objects.get(pk=transaction_id)
        DetailTransaksi.objects.filter(transaksi=transaction).update(kategori_snapshot="plastik")
        response = self.client.get(
            "/api/v1/dashboard/waste-categories",
            {
                "start_date": timezone.localdate().isoformat(),
                "end_date": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["categories"], [
            {"category": "plastik", "total_weight_kg": Decimal("2.500"), "deposit_count": 1}
        ])

    def test_reporting_endpoints_validate_required_query_parameters(self) -> None:
        for path in (
            "/api/v1/dashboard/operational-trends",
            "/api/v1/dashboard/waste-categories",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 400)

    def test_wa_template_rejects_blank(self) -> None:
        response = self.client.put(
            "/api/v1/pengaturan/wa-template", {"template": ""}, format="json"
        )
        self.assertGreaterEqual(response.status_code, 400)

    def test_wa_template_read_contract(self) -> None:
        response = self.client.get("/api/v1/pengaturan/wa-template")
        self.assertEqual(response.status_code, 200)
        self.assertIn("template", response.data)
