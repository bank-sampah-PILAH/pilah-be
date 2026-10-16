"""A committed writer must not change an export after its summary is read."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any
from unittest import skipUnless
from unittest.mock import patch

from django.db import connection, connections, transaction
from django.db.models import QuerySet

from api.models import DetailTransaksi, Pencairan, Transaksi
from apps.reporting.operational import OperationalSummary, operational_summary
from apps.reporting.test_operational_report import OperationalReportFixture


@skipUnless(connection.vendor == "postgresql", "Real PostgreSQL snapshot regression")
class ExportSnapshotTests(OperationalReportFixture):
    def workbook_with_interleaved_write(self, mutation: Callable[[], None]) -> Any:
        def writer() -> None:
            try:
                with transaction.atomic():
                    mutation()
            finally:
                connections["default"].close()

        # The executor outlives the HTTP request: on timeout, the reader's
        # transaction unwinds before we join the writer, avoiding a test deadlock.
        with ThreadPoolExecutor(max_workers=1) as executor:

            def after_summary(
                deposits: QuerySet[Transaksi], payouts: QuerySet[Pencairan]
            ) -> OperationalSummary:
                summary = operational_summary(deposits, payouts)
                executor.submit(writer).result(timeout=10)
                return summary

            with patch("apps.ledger.views.operational_summary", side_effect=after_summary):
                return self.workbook()

    def assert_original_snapshot(self, wb: Any) -> None:
        rows = list(wb["Riwayat Transaksi"].iter_rows(min_row=5, values_only=True))
        self.assertEqual(len({row[13] for row in rows}), wb["Ringkasan"]["B2"].value)
        self.assertEqual(sum(row[11] or 0 for row in rows), wb["Ringkasan"]["B4"].value)
        self.assertEqual(sum(row[12] or 0 for row in rows), wb["Ringkasan"]["B5"].value)
        self.assertEqual(sum(row[6] or 0 for row in rows), wb["Ringkasan"]["B3"].value)
        self.assertEqual(wb["Ringkasan"]["B2"].value, 3)
        self.assertEqual(wb["Ringkasan"]["B3"].value, 3.5)
        self.assertEqual(wb["Ringkasan"]["B4"].value, 20000)
        self.assertEqual(wb["Ringkasan"]["B6"].value, 15000)
        self.assertEqual(
            sum(row[3] or 0 for row in wb["Laporan"].iter_rows(min_row=2, values_only=True)), 3.5
        )

    def test_committed_insert_between_summary_and_rows_is_not_partially_exported(self) -> None:
        def insert() -> None:
            self.deposit("2026-10-03T12:00:00+07:00", "9000", "1.125")

        self.assert_original_snapshot(self.workbook_with_interleaved_write(insert))
        self.assertEqual(self.workbook()["Ringkasan"]["B2"].value, 4)

    def test_committed_edit_between_summary_and_rows_preserves_original_values(self) -> None:
        def edit() -> None:
            Transaksi.objects.filter(pk=self.first.pk).update(total_nilai=Decimal("20000"))
            DetailTransaksi.objects.filter(transaksi=self.first).update(
                berat=Decimal("2.500"), subtotal=Decimal("20000")
            )

        self.assert_original_snapshot(self.workbook_with_interleaved_write(edit))
        self.assertEqual(self.workbook()["Ringkasan"]["B4"].value, 28000)
