"""A committed writer must not change an export after its summary is read."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any
from unittest import skipUnless
from unittest.mock import patch

from django.db import DatabaseError, connection, connections, transaction
from django.db.models import QuerySet
from django.test import TestCase

from api.models import DetailTransaksi, Pencairan, Transaksi
from apps.reporting.operational import OperationalSummary, operational_summary
from apps.reporting.snapshot import export_snapshot
from apps.reporting.test_operational_report import OperationalReportFixture


class ExportSnapshotSetupTests(TestCase):
    def test_snapshot_sets_postgresql_read_only_repeatable_read(self) -> None:
        with (
            patch("apps.reporting.snapshot.connection.vendor", "postgresql"),
            patch("apps.reporting.snapshot.connection.cursor") as cursor,
        ):
            with export_snapshot():
                pass
        cursor.return_value.__enter__.return_value.execute.assert_any_call(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
        )


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

            with patch("apps.reporting.api.operational_summary", side_effect=after_summary):
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
            sum(
                row[3] or 0
                for row in wb["Laporan"].iter_rows(
                    min_row=2, max_row=wb["Laporan"].max_row - 1, values_only=True
                )
            ),
            3.5,
        )

    def test_committed_insert_between_summary_and_rows_is_not_partially_exported(self) -> None:
        def insert() -> None:
            self.deposit("2026-10-03T12:00:00+07:00", "9000", "1.125")

        self.assert_original_snapshot(self.workbook_with_interleaved_write(insert))
        self.assertEqual(self.workbook()["Ringkasan"]["B2"].value, 4)

    def test_committed_edit_between_summary_and_rows_preserves_original_values(self) -> None:
        def edit() -> None:
            Transaksi.objects.filter(pk=self.first.pk).update(total_nilai=Decimal(20000))
            DetailTransaksi.objects.filter(transaksi=self.first).update(
                berat=Decimal("2.500"), subtotal=Decimal(20000)
            )

        self.assert_original_snapshot(self.workbook_with_interleaved_write(edit))
        self.assertEqual(self.workbook()["Ringkasan"]["B4"].value, 28000)

    def test_snapshot_is_read_only_and_connection_recovers_after_failure(self) -> None:
        with self.assertRaises(DatabaseError), export_snapshot():
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                self.assertEqual(cursor.fetchone(), ("repeatable read",))
                cursor.execute("SHOW transaction_read_only")
                self.assertEqual(cursor.fetchone(), ("on",))
            Transaksi.objects.filter(pk=self.first.pk).update(total_nilai=99999)
        self.assertFalse(connection.in_atomic_block)
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            self.assertEqual(cursor.fetchone(), ("read committed",))
            cursor.execute("SHOW transaction_read_only")
            self.assertEqual(cursor.fetchone(), ("off",))
        # Ordinary writes on the reused connection still work after rollback.
        self.deposit("2026-10-03T12:00:00+07:00", "9000", "1.125")
        self.first.refresh_from_db()
        self.assertEqual(self.first.total_nilai, 12000)

    def test_snapshot_refuses_a_preexisting_read_committed_transaction(self) -> None:
        with transaction.atomic():
            Transaksi.objects.count()
            with self.assertRaisesMessage(RuntimeError, "cannot be nested"), export_snapshot():
                self.fail("A nested transaction must not silently weaken snapshot isolation")
