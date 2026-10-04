"""Dashboard contracts: stats, recent transactions, WA template."""

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

    def test_wa_template_rejects_blank(self) -> None:
        response = self.client.put(
            "/api/v1/pengaturan/wa-template", {"template": ""}, format="json"
        )
        self.assertGreaterEqual(response.status_code, 400)

    def test_wa_template_read_contract(self) -> None:
        response = self.client.get("/api/v1/pengaturan/wa-template")
        self.assertEqual(response.status_code, 200)
        self.assertIn("template", response.data)
