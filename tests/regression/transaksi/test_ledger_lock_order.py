"""Review on #145 (Rifqi, P1): writers of one nasabah's ledger must take their
row locks in one order, or two of them can deadlock.

Voiding a setoran locks the Saldo, then the setoran, then every later
pencairan. Editing a pencairan used to lock that pencairan first and the Saldo
after it, so each could hold the lock the other waited for, and PostgreSQL
aborted one with "deadlock detected" (a 500). Real row locks need PostgreSQL.
"""

import threading
from datetime import timedelta
from decimal import Decimal
from typing import Any
from unittest import skipUnless
from unittest.mock import patch

from django.db import connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from api.models import BankSampah, Nasabah, Pencairan, Saldo, Transaksi, User
from apps.ledger.services import PencairanService, TransactionService
from apps.waste_catalog.api import buat_jenis_sampah

WAIT = 10.0


@skipUnless(connection.vendor == "postgresql", "Row locks need PostgreSQL")
class LedgerLockOrderTests(TransactionTestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(
            nama="Bank Kunci", alamat="Depok", kota="Depok", no_hp_pic="+628123456789"
        )
        self.pengelola = User.objects.create_user(
            email="kunci@example.test",
            nama="Pengelola",
            bank_sampah=self.bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        self.nasabah = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-0001",
            nama="Budi",
            no_hp="+628111111111",
            alamat="Jl. A",
        )
        self.jenis = buat_jenis_sampah(
            bank_sampah=self.bank, nomor="PET", nama_sampah="Botol PET", harga_per_kg=Decimal(1000)
        )
        awal = timezone.now() - timedelta(hours=3)
        # Two setoran (10.000 and 20.000), then a 1.000 pencairan after both.
        self.dibatalkan = self._setor("10", awal)
        self._setor("20", awal + timedelta(hours=1))
        with transaction.atomic():
            self.pencairan = PencairanService.realisasi(
                user=self.pengelola,
                nasabah=self.nasabah,
                saldo=Saldo.objects.select_for_update().get(nasabah=self.nasabah),
                nominal=Decimal(1000),
                metode="tunai",
                tanggal=awal + timedelta(hours=2),
                keterangan="",
            )

    def _setor(self, berat: str, tanggal: Any) -> Transaksi:
        payload = {
            "nasabah_id": self.nasabah.id,
            "items": [{"jenis_sampah_id": self.jenis.id, "berat": Decimal(berat)}],
        }
        setoran = TransactionService.create_setoran(self.pengelola, payload)
        Transaksi.objects.filter(pk=setoran.pk).update(tanggal=tanggal)
        return Transaksi.objects.get(pk=setoran.pk)

    def test_a_void_and_a_pencairan_edit_on_one_ledger_do_not_deadlock(self) -> None:
        reached, proceed = threading.Event(), threading.Event()
        original = PencairanService._hitung_ulang_saldo
        errors: dict[str, BaseException] = {}

        def paused(*args: Any, **kwargs: Any) -> Any:
            # The edit has taken its first locks; hold here while the void starts.
            if threading.current_thread().name == "edit":
                reached.set()
                proceed.wait(WAIT)
            return original(*args, **kwargs)

        def run(name: str, work: Any) -> None:
            try:
                work()
            except BaseException as exc:  # recorded, then asserted on below
                errors[name] = exc
            finally:
                connection.close()

        def edit() -> None:
            PencairanService.edit_pencairan(
                self.pengelola,
                Pencairan.objects.get(pk=self.pencairan.pk),
                {"nominal": Decimal(2000), "alasan": "Salah nominal"},
            )

        def void() -> None:
            TransactionService.batalkan_setoran(
                self.pengelola, Transaksi.objects.get(pk=self.dibatalkan.pk), "Salah nasabah"
            )

        with patch.object(PencairanService, "_hitung_ulang_saldo", staticmethod(paused)):
            a = threading.Thread(target=run, args=("edit", edit), name="edit")
            a.start()
            self.assertTrue(reached.wait(WAIT), "the edit never reached its replay")
            b = threading.Thread(target=run, args=("void", void), name="void")
            b.start()
            b.join(1.0)
            proceed.set()
            a.join(WAIT)
            b.join(WAIT)

        self.assertEqual(errors, {}, "one of the two writers failed")
        self.pencairan.refresh_from_db()
        self.assertEqual(self.pencairan.nominal, Decimal(2000))
        self.assertEqual(
            Transaksi.objects.get(pk=self.dibatalkan.pk).status, Transaksi.Status.DIBATALKAN
        )
        # 10.000 + 20.000 - 2.000, then the void takes the 10.000 out.
        self.assertEqual(Saldo.objects.get(nasabah=self.nasabah).total_saldo, Decimal(18000))
