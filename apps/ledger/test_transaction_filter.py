from datetime import date, datetime
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import RequestFactory, TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from api.models import BankSampah, Nasabah, Transaksi, User
from apps.ledger.services import TransactionFilterService

WIB = ZoneInfo("Asia/Jakarta")
HARI_INI = date(2026, 10, 14)


class ApplyPeriodTests(TestCase):
    """The `periode` filter picks whole local days, edges included."""

    def setUp(self) -> None:
        bank = BankSampah.objects.create(nama="Melati", no_hp_pic="08123456789")
        self.pengurus = User.objects.create_user(email="pengurus@example.test", nama="Pengurus")
        self.nasabah = Nasabah.objects.create(
            bank_sampah=bank,
            nomor="001",
            nama="N001",
            alamat="Depok",
            no_hp="0812001",
            email="n001@example.test",
        )
        self.bank = bank
        patcher = mock.patch.object(timezone, "localdate", return_value=HARI_INI)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _catat(self, nilai: int, *waktu: int) -> None:
        Transaksi.objects.create(
            nasabah=self.nasabah,
            bank_sampah=self.bank,
            dicatat_oleh=self.pengurus,
            tanggal=datetime(*waktu, tzinfo=WIB),
            total_nilai=Decimal(nilai),
        )

    def _nilai(self, default: str | None = "hari_ini", **params: str) -> set[int]:
        request = RequestFactory().get("/", params)
        hasil = TransactionFilterService.apply_period(Transaksi.objects.all(), request, default)
        return {int(t.total_nilai) for t in hasil}

    def test_tanpa_periode_memakai_default(self) -> None:
        self._catat(1, 2026, 10, 14, 8, 0)
        self._catat(2, 2026, 10, 13, 23, 59)

        self.assertEqual(self._nilai(), {1})
        self.assertEqual(self._nilai(default=None), {1, 2})

    def test_bulan_ini_mulai_dari_tanggal_satu_tengah_malam(self) -> None:
        self._catat(1, 2026, 9, 30, 23, 59)
        self._catat(2, 2026, 10, 1, 0, 0)
        self._catat(3, 2026, 10, 14, 23, 59)

        self.assertEqual(self._nilai(periode="bulan_ini"), {2, 3})

    def test_bulan_lalu_mencakup_tanggal_satu_sampai_akhir_bulan(self) -> None:
        self._catat(1, 2026, 8, 31, 23, 59)
        self._catat(2, 2026, 9, 1, 0, 0)
        self._catat(3, 2026, 9, 30, 12, 0)
        self._catat(4, 2026, 10, 1, 0, 0)

        self.assertEqual(self._nilai(periode="bulan_lalu"), {2, 3})

    def test_custom_wajib_memuat_kedua_tanggal(self) -> None:
        for params in ({"dari_tanggal": "2026-10-01"}, {"sampai_tanggal": "2026-10-14"}):
            with self.subTest(params=params), self.assertRaises(ValidationError) as ctx:
                self._nilai(periode="custom", **params)
            self.assertEqual(
                dict(ctx.exception.detail),
                {"error": "dari_tanggal dan sampai_tanggal wajib diisi"},
            )

    def test_custom_terbalik_ditolak(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._nilai(periode="custom", dari_tanggal="2026-10-14", sampai_tanggal="2026-10-13")

        self.assertEqual(
            str(ctx.exception), "Tanggal akhir tidak boleh lebih awal dari tanggal awal"
        )

    def test_periode_tidak_dikenal_ditolak(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            self._nilai(periode="kemarin")

        self.assertEqual(dict(ctx.exception.detail), {"periode": "Periode tidak valid"})

    def test_tanggal_custom_tidak_valid_ditolak_dengan_pesan_format(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            self._nilai(periode="custom", dari_tanggal="14/10/2026", sampai_tanggal="2026-10-14")

        self.assertEqual(dict(ctx.exception.detail), {"error": "Format tanggal harus YYYY-MM-DD"})
