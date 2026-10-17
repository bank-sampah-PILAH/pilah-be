"""Numeric XLSX interoperability and bounded summary-query regressions."""

from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from openpyxl import load_workbook

from api.models import DetailTransaksi, Pencairan, Transaksi
from apps.ledger.services import TransactionFilterService
from apps.reporting.operational import operational_summary
from apps.reporting.test_operational_report import OperationalReportFixture


class ReviewRegressionTests(OperationalReportFixture):
    def test_export_totals_are_numbers_without_spreadsheet_recalculation(self) -> None:
        response = self.client.get(self.export_url, self.params)
        self.assertEqual(response.status_code, 200)
        for data_only in (False, True):
            with self.subTest(data_only=data_only):
                wb = load_workbook(BytesIO(response.content), data_only=data_only)
                sheet = wb["Laporan"]
                self.assertEqual(sheet["E2"].value, 20000)
                self.assertEqual(sheet["E3"].value, 20000)
                self.assertEqual(sheet["E2"].data_type, "n")
                self.assertEqual(sheet["E3"].value, wb["Ringkasan"]["B4"].value)

    def test_category_totals_sum_stored_item_values_not_group_price_times_weight(self) -> None:
        for event in (self.first, self.second):
            event.total_nilai = Decimal(1)
            event.save(update_fields=["total_nilai"])
            DetailTransaksi.objects.filter(transaksi=event).update(
                harga_snapshot=Decimal(3), berat=Decimal("0.500"), subtotal=Decimal(1)
            )
        sheet = self.workbook()["Laporan"]
        self.assertEqual(sheet["D2"].value, 1)
        self.assertEqual(sheet["E2"].value, 2)  # Two rounded items, not 3 * 1 kg.
        self.assertEqual(sheet["E3"].value, 2)

    def test_legacy_fractional_item_values_are_truncated_before_summing(self) -> None:
        for event in (self.first, self.second):
            event.total_nilai = Decimal("1.99")
            event.save(update_fields=["total_nilai"])
            DetailTransaksi.objects.filter(transaksi=event).update(subtotal=Decimal("1.99"))
        wb = self.workbook()
        self.assertEqual(wb["Laporan"]["E2"].value, 2)
        self.assertEqual(wb["Laporan"]["E3"].value, 2)
        self.assertEqual(wb["Ringkasan"]["B4"].value, 2)

    def test_summary_uses_three_aggregate_queries_and_preserves_signed_round_down(self) -> None:
        self.first.total_nilai = Decimal("-12000.99")
        self.first.save(update_fields=["total_nilai"])
        self.second.total_nilai = Decimal("8000.99")
        self.second.save(update_fields=["total_nilai"])
        self.payout.nominal = Decimal("5000.99")
        self.payout.save(update_fields=["nominal"])
        deposits = Transaksi.objects.filter(pk__in=[self.first.pk, self.second.pk])
        payouts = Pencairan.objects.filter(pk=self.payout.pk)
        with CaptureQueriesContext(connection) as queries:
            summary = operational_summary(deposits, payouts)
        self.assertEqual(summary["total_setoran"], -4000)
        self.assertEqual(summary["total_pencairan"], 5000)
        self.assertEqual(summary["saldo"], -9000)
        self.assertEqual(summary["jumlah_transaksi"], 3)
        self.assertEqual(summary["total_berat"], "3.500")
        self.assertEqual(len(queries), 3)
        self.assertTrue(all("SUM(" in row["sql"].upper() for row in queries))

    def test_feed_filters_each_ledger_once_for_rows_and_summary(self) -> None:
        with patch.object(
            TransactionFilterService, "apply_period", wraps=TransactionFilterService.apply_period
        ) as apply_period:
            response = self.client.get(self.feed_url, {**self.params, "page_size": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(response.data["summary"]["jumlah_transaksi"], 3)
        self.assertEqual(apply_period.call_count, 2)
