"""Data-layer tests for the nasabah riwayat statement (PIL-315).

The saldo walk, totals, tipe filtering and detail sub-rows are the load-bearing
logic of the PDF export; they are asserted here directly against
build_statement, including the BalanceService.saldo_at equivalence that pins
the tie-break rule. HTTP contract lives in apps/nasabah/test_history_pdf_export.py.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
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
from apps.reporting.statement import build_statement
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
            total_nilai=Decimal("10000.00"),
        )
        Pencairan.objects.create(
            nasabah=self.member,
            bank_sampah=self.bank,
            dicatat_oleh=self.manager,
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
        saldo = Decimal("0.00")
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

    def test_tipe_filter_limits_displayed_rows_only(self) -> None:
        data_pencairan = build_statement(self.member, self._request(tipe="pencairan"))
        self.assertEqual([row.tipe for row in data_pencairan.rows], ["Pencairan"])
        self.assertEqual(data_pencairan.total_setoran, Decimal(0))
        self.assertEqual(data_pencairan.saldo_akhir, Decimal("7000.00"))

        data_setoran = build_statement(self.member, self._request(tipe="setoran"))
        self.assertEqual([row.tipe for row in data_setoran.rows], ["Setoran"])
