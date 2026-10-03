"""Pins the id fields that serializers read through nested `source` paths.

`bank_sampah.id` and `dicatat_oleh.id` are shared by several serializers, so a
wrong shared path would silently change every one of these responses.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from api.models import BankSampah, JadwalKegiatan, Nasabah, Pencairan, Transaksi, User
from api.serializers import (
    JadwalKegiatanSerializer,
    PencairanDetailSerializer,
)
from apps.authentication.serializers import AuthUserSerializer
from apps.ledger.serializers import (
    TransactionDetailSerializer,
    TransactionListSerializer,
)


class SerializerSourceTests(TestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(
            nama="Bank Sampah BTH",
            alamat="Depok",
            kota="Depok",
            no_hp_pic="+628123456789",
            status=BankSampah.Status.ACTIVE,
        )
        self.pengurus = User.objects.create_user(
            email="sari@example.com",
            nama="Ibu Sari",
            bank_sampah=self.bank,
            is_profile_complete=True,
        )
        self.nasabah = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-0001",
            nama="Ahmad Ridwan",
            no_hp="+628123456789",
            alamat="Jl. Mawar No. 12",
        )

    def test_pencairan_detail_exposes_bank_and_recorder_ids(self) -> None:
        pencairan = Pencairan.objects.create(
            nasabah=self.nasabah,
            bank_sampah=self.bank,
            dicatat_oleh=self.pengurus,
            nominal=Decimal(10000),
            metode=Pencairan.Metode.TUNAI,
            saldo_sebelum=Decimal(50000),
            saldo_sesudah=Decimal(40000),
        )

        data = PencairanDetailSerializer(pencairan).data

        self.assertEqual(str(data["bank_sampah_id"]), str(self.bank.id))
        self.assertEqual(str(data["dicatat_oleh"]), str(self.pengurus.id))

    def test_transaksi_serializers_expose_bank_and_recorder_ids(self) -> None:
        transaksi = Transaksi.objects.create(
            nasabah=self.nasabah,
            bank_sampah=self.bank,
            dicatat_oleh=self.pengurus,
            total_nilai=Decimal(0),
        )

        detail = TransactionDetailSerializer(transaksi).data
        listed = TransactionListSerializer(transaksi).data

        self.assertEqual(str(detail["bank_sampah_id"]), str(self.bank.id))
        self.assertEqual(str(detail["dicatat_oleh"]), str(self.pengurus.id))
        self.assertEqual(str(listed["dicatat_oleh"]), str(self.pengurus.id))

    def test_auth_user_exposes_bank_id_or_null(self) -> None:
        tanpa_bank = User.objects.create_user(email="baru@example.com", nama="Baru")

        self.assertEqual(
            str(AuthUserSerializer(self.pengurus).data["bank_sampah_id"]), str(self.bank.id)
        )
        self.assertIsNone(AuthUserSerializer(tanpa_bank).data["bank_sampah_id"])

    def test_jadwal_exposes_bank_id(self) -> None:
        mulai = timezone.now() + timedelta(days=1)
        jadwal = JadwalKegiatan.objects.create(
            bank_sampah=self.bank,
            dibuat_oleh=self.pengurus,
            jenis_kegiatan=JadwalKegiatan.JenisKegiatan.PENIMBANGAN,
            mulai_pada=mulai,
            selesai_pada=mulai + timedelta(hours=2),
            lokasi="Balai RW",
        )

        data = JadwalKegiatanSerializer(jadwal).data

        self.assertEqual(str(data["bank_sampah_id"]), str(self.bank.id))
