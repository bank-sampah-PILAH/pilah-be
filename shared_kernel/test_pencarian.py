from django.test import SimpleTestCase
from rest_framework import serializers

from shared_kernel.pencarian import validasi_pencarian


class ValidasiPencarianTests(SimpleTestCase):
    def test_teks_biasa_dikembalikan_apa_adanya(self) -> None:
        self.assertEqual(validasi_pencarian("Siti Aminah"), "Siti Aminah")
        self.assertEqual(validasi_pencarian(""), "")

    def test_karakter_kontrol_c0_ditolak_dengan_kunci_search(self) -> None:
        for raw in ("a\x00b", "a\x01b", "a\x1fb", "a\x7fb"):
            with self.subTest(raw=raw), self.assertRaises(serializers.ValidationError) as ctx:
                validasi_pencarian(raw)
            self.assertIn("search", ctx.exception.detail)

    def test_tab_dan_baris_baru_ditolak_juga(self) -> None:
        with self.assertRaises(serializers.ValidationError):
            validasi_pencarian("a\nb")
