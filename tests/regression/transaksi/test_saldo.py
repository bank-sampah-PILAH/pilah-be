"""Saldo contracts: balances follow transactions and stay bank-scoped."""

from api.models import BankSampah, Nasabah, Saldo
from tests.regression.helpers import RegressionTestCase


class SaldoRegressionTests(RegressionTestCase):
    def test_saldo_tracks_transaction_value(self) -> None:
        nasabah = self.make_nasabah()
        jenis_id = self.make_jenis()
        self.client.post(
            "/api/v1/transaksi",
            {
                "nasabah_id": str(nasabah.id),
                "items": [{"jenis_sampah_id": jenis_id, "berat": "2.500"}],
            },
            format="json",
        )
        response = self.client.get(f"/api/v1/nasabah/{nasabah.id}/saldo")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_saldo"], "8750.00")

    def test_saldo_created_on_first_read(self) -> None:
        nasabah = self.make_nasabah()
        Saldo.objects.filter(nasabah=nasabah).delete()
        response = self.client.get(f"/api/v1/nasabah/{nasabah.id}/saldo")
        self.assertEqual(response.status_code, 200)
        self.assertIn("total_saldo", response.data)

    def test_saldo_other_bank_invisible(self) -> None:
        other_bank = BankSampah.objects.create(
            nama="Lain", alamat="Jl. Lain No. 10", kota="Depok", no_hp_pic="+628999999999"
        )
        other_nasabah = Nasabah.objects.create(
            bank_sampah=other_bank,
            nomor="NAS-9",
            nama="Orang Lain",
            no_hp="+628999999998",
            alamat="Jl. Lain No. 11",
        )
        Saldo.objects.create(nasabah=other_nasabah)
        self.assertEqual(
            self.client.get(f"/api/v1/nasabah/{other_nasabah.id}/saldo").status_code, 404
        )
