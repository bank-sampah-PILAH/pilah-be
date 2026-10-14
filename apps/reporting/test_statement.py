"""Data-layer tests for the nasabah riwayat statement (PIL-315).

The saldo walk, totals, tipe filtering and detail sub-rows are the load-bearing
logic of the PDF export; they are asserted here directly against
build_statement, including the BalanceService.saldo_at equivalence that pins
the tie-break rule. HTTP contract lives in apps/nasabah/test_history_pdf_export.py.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from api.models import (
    BankSampah,
    DetailTransaksi,
    JenisSampah,
    Nasabah,
    Pencairan,
    Saldo,
    Transaksi,
    User,
)
from apps.ledger.api import saldo_at
from apps.reporting.render import _tanggal_label
from apps.reporting.statement import MAX_DISPLAYED_ROWS, StatementPeriodError, build_statement
from shared_kernel.kalkulasi import bulatkan_rupiah


class NasabahStatementDataTests(TestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(nama="Melati", no_hp_pic="08123456789")
        self.user = User.objects.create_user(
            email="stmt@example.test", nama="Siti", role=User.Role.NASABAH
        )
        self.manager = User.objects.create_user(email="staff@example.test", nama="Staff")
        self.member = Nasabah.objects.create(
            user=self.user,
            bank_sampah=self.bank,
            nomor="001",
            nama="Siti",
            alamat="Depok",
            no_hp="08120",
        )
        self.jenis = JenisSampah.objects.create(
            bank_sampah=self.bank,
            nomor="01",
            nama_sampah="Plastik PET",
            kategori="plastik",
            harga_per_kg=Decimal("3500.00"),
        )
        Transaksi.objects.create(
            nasabah=self.member,
            bank_sampah=self.bank,
            dicatat_oleh=self.manager,
            tanggal=timezone.now() - timedelta(minutes=2),
            total_nilai=Decimal("10000.00"),
        )
        Pencairan.objects.create(
            nasabah=self.member,
            bank_sampah=self.bank,
            dicatat_oleh=self.manager,
            tanggal=timezone.now() - timedelta(minutes=1),
            nominal=Decimal("3000.00"),
            metode="tunai",
            saldo_sebelum=Decimal("10000.00"),
            saldo_sesudah=Decimal("7000.00"),
        )

    def _request(self, **params: str) -> Request:
        factory = APIRequestFactory()
        request = factory.get("/api/v1/nasabah/me/riwayat/export-pdf", params)
        request.user = self.user
        return Request(request)

    # --- Data-layer: saldo walk, totals, sub-rows ------------------------

    def test_running_saldo_matches_saldo_at_for_every_row(self) -> None:
        # Mixed tipes sharing one identical tanggal exercise the tie-break
        # (setoran before pencairan) that BalanceService.saldo_at codifies.
        # Snapshots follow the ledger: saldo runs 0 → setoran → pencairan.
        same = timezone.now()
        # Snapshots must follow the FULL walk (setUp: +10000 setoran, −3000
        # legacy payout = 7000), since the rows rebase onto them. A 0-based
        # fixture would test against snapshots the walk never sees.
        saldo = Decimal("7000.00")
        for i in range(3):
            nilai = Decimal(f"{2000 + i * 500}.00")
            Transaksi.objects.create(
                nasabah=self.member,
                bank_sampah=self.bank,
                dicatat_oleh=self.manager,
                total_nilai=nilai,
                tanggal=same + timedelta(minutes=i),
            )
            saldo += nilai
            Pencairan.objects.create(
                nasabah=self.member,
                bank_sampah=self.bank,
                dicatat_oleh=self.manager,
                nominal=Decimal("1000.00"),
                metode="tunai",
                saldo_sebelum=saldo,
                saldo_sesudah=saldo - Decimal("1000.00"),
                tanggal=same + timedelta(minutes=i),
            )
            saldo -= Decimal("1000.00")

        data = build_statement(self.member, self._request())
        for row in data.rows:
            if row.tipe == "Setoran":
                self.assertEqual(
                    row.saldo,
                    bulatkan_rupiah(saldo_at(self.bank, self.member.id, row.tanggal, row.id)),
                )
            else:
                pencairan = Pencairan.objects.get(pk=row.id)
                self.assertEqual(row.saldo, bulatkan_rupiah(pencairan.saldo_sesudah))

    def test_summary_totals_and_saldo_akhir(self) -> None:
        Saldo.objects.create(nasabah=self.member, total_saldo=Decimal("16000.00"))
        data = build_statement(self.member, self._request())
        self.assertEqual(data.total_setoran, Decimal("10000.00"))
        self.assertEqual(data.total_pencairan, Decimal("3000.00"))
        # Saldo akhir follows the pencairan snapshot chain (7000 in setUp).
        self.assertEqual(data.saldo_akhir, Decimal("7000.00"))
        self.assertEqual(data.saldo_awal, Decimal(0))

    def test_detail_subrows_carry_item_snapshots(self) -> None:
        trans = Transaksi.objects.create(
            nasabah=self.member,
            bank_sampah=self.bank,
            dicatat_oleh=self.manager,
            total_nilai=Decimal("7000.00"),
        )
        DetailTransaksi.objects.create(
            transaksi=trans,
            jenis_sampah=self.jenis,
            nama_sampah_snapshot="Plastik PET",
            kategori_snapshot="plastik",
            harga_snapshot=Decimal("3500.00"),
            berat=Decimal("2.000"),
            subtotal=Decimal("7000.00"),
        )
        data = build_statement(self.member, self._request())
        target = next(row for row in data.rows if row.id == trans.id)
        self.assertEqual(len(target.items), 1)
        self.assertEqual(target.items[0].nama, "Plastik PET")

    def test_omitted_periode_label_reads_all_time_not_hari_ini(self) -> None:
        # The export's window default is "no filter" (all time), unlike the
        # XLSX exports whose filter defaults to hari ini; the label must say
        # so instead of inheriting period_label's hari-ini default.
        self.assertEqual(
            build_statement(self.member, self._request()).periode_label,
            "Semua Periode",
        )
        labeled = build_statement(self.member, self._request(periode="bulan_ini"))
        self.assertTrue(labeled.periode_label.startswith("Bulan Ini"))

    def test_legacy_payout_without_prior_setoran_rebases_saldo(self) -> None:
        # A legacy sen-era payout often references saldo the walk cannot
        # reconstruct from this member's rows alone; the row must show the
        # stored snapshot, and a LATER setoran must build on it rather than
        # on the unanchored walk (which would stay 0 + delta forever).
        Pencairan.objects.all().delete()
        Transaksi.objects.all().delete()
        legacy = Pencairan.objects.create(
            nasabah=self.member,
            bank_sampah=self.bank,
            dicatat_oleh=self.manager,
            tanggal=timezone.now() - timedelta(days=1),
            nominal=Decimal("1000.00"),
            metode="tunai",
            saldo_sebelum=Decimal("8000.00"),
            saldo_sesudah=Decimal("7000.00"),
        )
        later = Transaksi.objects.create(
            nasabah=self.member,
            bank_sampah=self.bank,
            dicatat_oleh=self.manager,
            tanggal=legacy.tanggal + timedelta(hours=1),
            total_nilai=Decimal("2500.00"),
        )
        data = build_statement(self.member, self._request())
        legacy_row = next(row for row in data.rows if row.id == legacy.id)
        later_row = next(row for row in data.rows if row.id == later.id)
        self.assertEqual(legacy_row.saldo, Decimal("7000.00"))
        self.assertEqual(later_row.saldo, Decimal("9500.00"))
        self.assertEqual(data.saldo_akhir, Decimal("9500.00"))

    def test_tipe_filter_limits_displayed_rows_only(self) -> None:
        data_pencairan = build_statement(self.member, self._request(tipe="pencairan"))
        self.assertEqual([row.tipe for row in data_pencairan.rows], ["Pencairan"])
        self.assertEqual(data_pencairan.total_setoran, Decimal(0))
        self.assertEqual(data_pencairan.saldo_akhir, Decimal("7000.00"))

        data_setoran = build_statement(self.member, self._request(tipe="setoran"))
        self.assertEqual([row.tipe for row in data_setoran.rows], ["Setoran"])

    # --- Request windows the statement refuses ----------------------------

    def test_reversed_custom_range_surfaces_as_statement_period_error(self) -> None:
        # apply_period's ValueError (reversed custom range) is re-tagged, so
        # the HTTP view can separate request errors from render errors.
        with self.assertRaises(StatementPeriodError):
            build_statement(
                self.member,
                self._request(
                    periode="custom",
                    dari_tanggal="2026-10-02",
                    sampai_tanggal="2026-10-01",
                ),
            )

    def test_row_cap_rejects_oversized_window_instead_of_truncating(self) -> None:
        Transaksi.objects.all().delete()
        Pencairan.objects.all().delete()
        base = timezone.make_aware(datetime(2026, 1, 1))
        Transaksi.objects.bulk_create(
            [
                Transaksi(
                    nasabah=self.member,
                    bank_sampah=self.bank,
                    dicatat_oleh=self.manager,
                    total_nilai=Decimal("100.00"),
                    tanggal=base + timedelta(minutes=i),
                )
                for i in range(MAX_DISPLAYED_ROWS + 1)
            ]
        )
        with self.assertRaises(StatementPeriodError) as ctx:
            build_statement(self.member, self._request())
        self.assertIn(str(MAX_DISPLAYED_ROWS), str(ctx.exception))
        self.assertIn("periode", str(ctx.exception))


class TanggalLabelTests(SimpleTestCase):
    """WIB calendar dates for the mutation table's plain-tanggal column."""

    def test_utc_evening_prints_the_next_wib_date(self) -> None:
        # 2026-10-01 19:00 UTC is 02:00 WIB on 10/02; a raw UTC strftime
        # (the old behavior) printed 01/10.
        utc_evening = datetime(2026, 10, 1, 19, 0, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(_tanggal_label(utc_evening), "02/10/2026")

    def test_utc_morning_stays_the_same_wib_date(self) -> None:
        utc_morning = datetime(2026, 10, 2, 2, 0, tzinfo=ZoneInfo("UTC"))
        # 09:00 WIB same day.
        self.assertEqual(_tanggal_label(utc_morning), "02/10/2026")
