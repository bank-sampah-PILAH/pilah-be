"""PIL-304: harga jenis sampah ber-versi dengan tanggal berlaku (SDS 7.1.2, BR-03)."""

from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from api.models import BankSampah, HargaSampah, JenisSampah
from apps.waste_catalog.api import harga_berlaku


class HargaBerlakuTests(TestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(
            nama="Bank Sampah BTH", alamat="Depok", kota="Depok", no_hp_pic="+628123456789"
        )
        self.jenis = JenisSampah.objects.create(
            bank_sampah=self.bank,
            nomor="PLS-001",
            nama_sampah="Plastik PET",
            kategori="plastik",
        )
        self.sekarang = timezone.now()

    def _versi(self, harga: str, mulai_hari: int) -> HargaSampah:
        return HargaSampah.objects.create(
            jenis_sampah=self.jenis,
            bank_sampah=self.bank,
            harga_per_kg=Decimal(harga),
            berlaku_mulai=self.sekarang + timedelta(days=mulai_hari),
        )

    def test_harga_berlaku_is_the_latest_version_started_at_that_time(self) -> None:
        self._versi("3000", -10)
        self._versi("4000", -2)
        self._versi("5000", 3)

        self.assertEqual(harga_berlaku(self.jenis, self.sekarang - timedelta(days=5)), 3000)
        self.assertEqual(harga_berlaku(self.jenis, self.sekarang), 4000)
        self.assertEqual(harga_berlaku(self.jenis, self.sekarang + timedelta(days=4)), 5000)

    def test_later_version_wins_when_two_start_at_the_same_time(self) -> None:
        # Rows are never edited, so a pengurus corrects a scheduled price by
        # adding another one for the same time; the correction must win.
        self._versi("4000", 2)
        self._versi("4500", 2)

        self.assertEqual(harga_berlaku(self.jenis, self.sekarang + timedelta(days=3)), 4500)

    def test_database_rejects_a_price_that_is_not_positive(self) -> None:
        # Dijaga di database, bukan hanya serializer, agar jalur selain API
        # (admin, shell, data migration) tidak bisa menyimpan harga 0.
        for harga in ("0", "-1"):
            with self.subTest(harga), self.assertRaises(IntegrityError), transaction.atomic():
                self._versi(harga, 0)
