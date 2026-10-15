from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from django.test import TestCase
from django.utils import timezone

from api.models import BankSampah, Nasabah, Pencairan, Transaksi, User
from apps.ledger.services import BalanceService


class SaldoAtTests(TestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(nama="Melati", no_hp_pic="08123456789")
        self.pengurus = User.objects.create_user(email="pengurus@example.test", nama="Pengurus")
        self.nasabah = self._nasabah("001", self.bank)
        self.lain = self._nasabah("002", self.bank)
        self.sekarang = timezone.now()

    def _nasabah(self, nomor: str, bank: BankSampah) -> Nasabah:
        return Nasabah.objects.create(
            bank_sampah=bank,
            nomor=nomor,
            nama=f"N{nomor}",
            alamat="Depok",
            no_hp=f"0812{nomor}",
            email=f"n{nomor}@example.test",
        )

    def _setoran(
        self, nasabah: Nasabah, nilai: str, tanggal: datetime, bank: BankSampah | None = None
    ) -> Transaksi:
        return Transaksi.objects.create(
            nasabah=nasabah,
            bank_sampah=bank or nasabah.bank_sampah,
            dicatat_oleh=self.pengurus,
            tanggal=tanggal,
            total_nilai=Decimal(nilai),
        )

    def _pencairan(
        self, nasabah: Nasabah, sebelum: str, sesudah: str, tanggal: datetime
    ) -> Pencairan:
        return Pencairan.objects.create(
            nasabah=nasabah,
            bank_sampah=nasabah.bank_sampah,
            dicatat_oleh=self.pengurus,
            tanggal=tanggal,
            nominal=Decimal(sebelum) - Decimal(sesudah),
            metode="tunai",
            saldo_sebelum=Decimal(sebelum),
            saldo_sesudah=Decimal(sesudah),
        )

    def _saldo(self, nasabah: Nasabah | None = None, until_id: UUID | None = None) -> Decimal:
        return BalanceService.saldo_at(
            self.bank,
            (nasabah or self.nasabah).id,
            self.sekarang,
            until_id or UUID(int=2**128 - 1),
        )

    def test_nasabah_tanpa_riwayat_bersaldo_nol(self) -> None:
        self.assertEqual(self._saldo(), Decimal(0))

    def test_hanya_menghitung_riwayat_nasabah_itu_sendiri(self) -> None:
        sebelum = self.sekarang - timedelta(hours=2)
        self._setoran(self.nasabah, "10000.00", sebelum)
        self._setoran(self.lain, "99000.00", sebelum)
        self._pencairan(self.nasabah, "10000.00", "7000.00", sebelum + timedelta(hours=1))
        self._pencairan(self.lain, "99000.00", "50000.00", sebelum + timedelta(hours=1))

        self.assertEqual(self._saldo(), Decimal("7000.00"))

    def test_hanya_menghitung_riwayat_bank_sampah_yang_diminta(self) -> None:
        bank_lain = BankSampah.objects.create(nama="Kenanga", no_hp_pic="08123456780")
        sebelum = self.sekarang - timedelta(hours=2)
        self._setoran(self.nasabah, "10000.00", sebelum)
        self._setoran(self.nasabah, "55000.00", sebelum, bank=bank_lain)
        pencairan = self._pencairan(self.nasabah, "10000.00", "7000.00", sebelum)
        Pencairan.objects.filter(pk=pencairan.pk).update(bank_sampah=bank_lain)
        self._pencairan(self.nasabah, "10000.00", "9000.00", sebelum)

        self.assertEqual(self._saldo(), Decimal("9000.00"))

    def test_setoran_pada_waktu_yang_sama_dihitung_sampai_id_yang_diminta(self) -> None:
        pertama = self._setoran(self.nasabah, "1000.00", self.sekarang)
        kedua = self._setoran(self.nasabah, "2000.00", self.sekarang)
        urut = sorted([pertama, kedua], key=lambda setoran: setoran.id)

        self.assertEqual(self._saldo(until_id=urut[0].id), urut[0].total_nilai)
        self.assertEqual(self._saldo(until_id=urut[1].id), Decimal("3000.00"))

    def test_pencairan_pada_waktu_yang_sama_belum_ikut_terhitung(self) -> None:
        self._setoran(self.nasabah, "10000.00", self.sekarang - timedelta(hours=1))
        self._pencairan(self.nasabah, "10000.00", "4000.00", self.sekarang)

        self.assertEqual(self._saldo(), Decimal("10000.00"))
