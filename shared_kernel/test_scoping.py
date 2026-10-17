from django.test import TestCase

from api.models import BankSampah, JenisSampah
from shared_kernel.scoping import for_bank


class ForBankTests(TestCase):
    def test_only_rows_of_the_given_bank_are_returned(self) -> None:
        mine = BankSampah.objects.create(nama="Bank A", alamat="x", kota="Depok")
        other = BankSampah.objects.create(nama="Bank B", alamat="x", kota="Depok")
        own = JenisSampah.objects.create(bank_sampah=mine, nomor="1", nama_sampah="PET")
        JenisSampah.objects.create(bank_sampah=other, nomor="1", nama_sampah="PET")

        self.assertEqual(list(for_bank(JenisSampah.objects.all(), mine)), [own])
