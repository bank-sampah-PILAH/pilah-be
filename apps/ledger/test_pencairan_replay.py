from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from uuid import UUID

from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from api.models import BankSampah, Nasabah, Pencairan, Saldo, Transaksi, User
from apps.ledger.services import PencairanService


def _uuid(angka: int) -> UUID:
    return UUID(int=angka)


class HitungUlangSaldoTests(TestCase):
    """Editing a pencairan replays the nasabah's ledger and rewrites later snapshots."""

    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(nama="Melati", no_hp_pic="08123456789")
        self.pengurus = User.objects.create_user(
            email="pengurus@example.test", nama="Pengurus", bank_sampah=self.bank
        )
        self.nasabah = self._nasabah("001")
        self.sekarang = timezone.now().replace(microsecond=0)

    def _nasabah(self, nomor: str) -> Nasabah:
        return Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor=nomor,
            nama=f"N{nomor}",
            alamat="Depok",
            no_hp=f"0812{nomor}",
            email=f"n{nomor}@example.test",
        )

    def _setoran(
        self, nasabah: Nasabah, nilai: str, tanggal: datetime, pk: UUID | None = None
    ) -> Transaksi:
        return Transaksi.objects.create(
            **({"id": pk} if pk else {}),
            nasabah=nasabah,
            bank_sampah=self.bank,
            dicatat_oleh=self.pengurus,
            tanggal=tanggal,
            total_nilai=Decimal(nilai),
        )

    def _pencairan(
        self,
        nasabah: Nasabah,
        sebelum: str,
        nominal: str,
        tanggal: datetime,
        pk: UUID | None = None,
    ) -> Pencairan:
        sesudah = (Decimal(sebelum) - Decimal(nominal)).quantize(Decimal(1), rounding=ROUND_DOWN)
        return Pencairan.objects.create(
            **({"id": pk} if pk else {}),
            nasabah=nasabah,
            bank_sampah=self.bank,
            dicatat_oleh=self.pengurus,
            tanggal=tanggal,
            nominal=Decimal(nominal),
            metode="tunai",
            saldo_sebelum=Decimal(sebelum),
            saldo_sesudah=sesudah,
        )

    def _saldo(self, nasabah: Nasabah, total: str) -> None:
        Saldo.objects.update_or_create(nasabah=nasabah, defaults={"total_saldo": Decimal(total)})

    def _edit(self, pencairan: Pencairan, **payload: object) -> Pencairan:
        return PencairanService.edit_pencairan(
            self.pengurus, pencairan, {"alasan": "Salah ketik", **payload}
        )

    def _snapshot(self, pencairan: Pencairan) -> tuple[Decimal, Decimal]:
        pencairan.refresh_from_db()
        return pencairan.saldo_sebelum, pencairan.saldo_sesudah

    def test_nasabah_lain_tidak_ikut_diputar_ulang(self) -> None:
        t = self.sekarang
        self._setoran(self.nasabah, "100000", t - timedelta(hours=5))
        p1 = self._pencairan(self.nasabah, "100000", "50000", t - timedelta(hours=3))
        p2 = self._pencairan(self.nasabah, "50000", "20000", t - timedelta(hours=1))
        self._saldo(self.nasabah, "30000")
        lain = self._nasabah("002")
        self._setoran(lain, "7000", t - timedelta(hours=2))
        p_lain = self._pencairan(lain, "7000", "1000", t - timedelta(minutes=90))
        self._saldo(lain, "6000")

        self._edit(p1, nominal=Decimal(40000))

        self.assertEqual(self._snapshot(p1), (Decimal(100000), Decimal(60000)))
        self.assertEqual(self._snapshot(p2), (Decimal(60000), Decimal(40000)))
        self.assertEqual(Saldo.objects.get(nasabah=self.nasabah).total_saldo, Decimal(40000))
        self.assertEqual(self._snapshot(p_lain), (Decimal(7000), Decimal(6000)))
        self.assertEqual(Saldo.objects.get(nasabah=lain).total_saldo, Decimal(6000))

    def test_setoran_pada_waktu_yang_sama_dihitung_sebelum_pencairan(self) -> None:
        t = self.sekarang
        self._setoran(self.nasabah, "20000", t - timedelta(hours=4))
        # The setoran id sorts after the pencairan id, so only the rule that a setoran
        # comes first at an equal instant puts it ahead of the pencairan.
        self._setoran(self.nasabah, "10000", t, pk=_uuid(2**128 - 1))
        pencairan = self._pencairan(self.nasabah, "30000", "30000", t, pk=_uuid(1))
        self._saldo(self.nasabah, "0")

        self._edit(pencairan, nominal=Decimal(25000))

        self.assertEqual(self._snapshot(pencairan), (Decimal(30000), Decimal(5000)))
        self.assertEqual(Saldo.objects.get(nasabah=self.nasabah).total_saldo, Decimal(5000))

    def test_pencairan_pada_waktu_yang_sama_diurutkan_menurut_id_saat_yang_diedit_lebih_dulu(
        self,
    ) -> None:
        t = self.sekarang
        self._setoran(self.nasabah, "100000", t - timedelta(hours=1))
        diedit = self._pencairan(self.nasabah, "100000", "20000", t, pk=_uuid(1))
        lainnya = self._pencairan(self.nasabah, "80000", "10000", t, pk=_uuid(2))
        self._saldo(self.nasabah, "70000")

        self._edit(diedit, nominal=Decimal(30000))

        self.assertEqual(self._snapshot(diedit), (Decimal(100000), Decimal(70000)))
        self.assertEqual(self._snapshot(lainnya), (Decimal(70000), Decimal(60000)))

    def test_pencairan_pada_waktu_yang_sama_diurutkan_menurut_id_saat_yang_diedit_belakangan(
        self,
    ) -> None:
        t = self.sekarang
        self._setoran(self.nasabah, "100000", t - timedelta(hours=1))
        lainnya = self._pencairan(self.nasabah, "100000", "10000", t, pk=_uuid(1))
        diedit = self._pencairan(self.nasabah, "90000", "20000", t, pk=_uuid(2))
        self._saldo(self.nasabah, "70000")

        self._edit(diedit, nominal=Decimal(30000))

        self.assertEqual(self._snapshot(lainnya), (Decimal(100000), Decimal(90000)))
        self.assertEqual(self._snapshot(diedit), (Decimal(90000), Decimal(60000)))

    def test_nominal_boleh_sama_dengan_seluruh_saldo(self) -> None:
        t = self.sekarang
        self._setoran(self.nasabah, "50000", t - timedelta(hours=2))
        pencairan = self._pencairan(self.nasabah, "50000", "20000", t - timedelta(hours=1))
        self._saldo(self.nasabah, "30000")

        self._edit(pencairan, nominal=Decimal(50000))

        self.assertEqual(self._snapshot(pencairan), (Decimal(50000), Decimal(0)))
        self.assertEqual(Saldo.objects.get(nasabah=self.nasabah).total_saldo, Decimal(0))

    def test_nominal_melebihi_saldo_ditolak(self) -> None:
        t = self.sekarang
        self._setoran(self.nasabah, "50000", t - timedelta(hours=2))
        pencairan = self._pencairan(self.nasabah, "50000", "20000", t - timedelta(hours=1))
        self._saldo(self.nasabah, "30000")

        with self.assertRaises(ValidationError):
            self._edit(pencairan, nominal=Decimal(50001))

    def test_saldo_bersen_dari_data_lama_dibulatkan_ke_bawah(self) -> None:
        # PILAH 1.0 left sen in saldo; there is no setoran behind this opening balance.
        pencairan = self._pencairan(
            self.nasabah, "1000.75", "50", self.sekarang - timedelta(hours=1)
        )
        self._saldo(self.nasabah, "950")

        self._edit(pencairan, nominal=Decimal(100))

        self.assertEqual(self._snapshot(pencairan), (Decimal("1000.75"), Decimal(900)))
        self.assertEqual(Saldo.objects.get(nasabah=self.nasabah).total_saldo, Decimal(900))
