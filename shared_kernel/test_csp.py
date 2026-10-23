"""Sifat yang harus berlaku pada SETIAP kebijakan CSP, bukan pada satu saja."""

from django.test import SimpleTestCase

from shared_kernel.csp import (
    KEBIJAKAN_API,
    PembangunKebijakan,
    kebijakan_halaman,
    kebijakan_halaman_bernonce,
    nonce_baru,
)

SEMUA_KEBIJAKAN = {
    "api": KEBIJAKAN_API,
    "halaman (produksi)": kebijakan_halaman(False),
    "halaman (pengembangan, CDN)": kebijakan_halaman(True),
    "halaman bernonce": kebijakan_halaman_bernonce("CONTOHNONCE"),
}
"""Termasuk varian CDN, yang tidak pernah dilewati suite lewat permintaan HTTP.

Runner Django memaksa `DEBUG=False` selama test, jadi cabang itu hanya bisa
diuji dengan memanggil penyusunnya langsung. Tanpa baris ini separuh
`kebijakan_halaman` tidak pernah dijalankan test mana pun.
"""


class SetiapKebijakanTests(SimpleTestCase):
    def test_memasang_tiga_arahan_penutup(self) -> None:
        """`frame-ancestors`, `base-uri` dan `form-action` tidak diturunkan
        dari `default-src`, jadi melewatkannya kehilangan perlindungan tanpa
        tanda apa pun."""
        self.assertTrue(SEMUA_KEBIJAKAN, "himpunan kebijakan tidak boleh kosong")
        for nama, kebijakan in SEMUA_KEBIJAKAN.items():
            for arahan in ("frame-ancestors", "base-uri", "form-action"):
                with self.subTest(kebijakan=nama, arahan=arahan):
                    self.assertIn(arahan, kebijakan)

    def test_tidak_ada_kebijakan_memakai_unsafe(self) -> None:
        """Satu `'unsafe-inline'` pada script-src membatalkan seluruh gunanya."""
        for nama, kebijakan in SEMUA_KEBIJAKAN.items():
            with self.subTest(kebijakan=nama):
                self.assertNotIn("'unsafe-inline'", kebijakan)
                self.assertNotIn("'unsafe-eval'", kebijakan)

    def test_hanya_kebijakan_bernonce_mengizinkan_skrip_inline(self) -> None:
        for nama, kebijakan in SEMUA_KEBIJAKAN.items():
            if nama == "halaman bernonce":
                self.assertIn("'nonce-CONTOHNONCE'", kebijakan)
            else:
                with self.subTest(kebijakan=nama):
                    self.assertNotIn("nonce-", kebijakan)


class NonceTests(SimpleTestCase):
    def test_nonce_tidak_berulang(self) -> None:
        """Nonce yang bisa diramalkan sama saja dengan `'unsafe-inline'`."""
        self.assertEqual(len({nonce_baru() for _ in range(64)}), 64)

    def test_nonce_cukup_panjang(self) -> None:
        self.assertGreaterEqual(len(nonce_baru()), 16)


class PembangunKebijakanTests(SimpleTestCase):
    def test_urutan_arahan_mengikuti_urutan_pemanggilan(self) -> None:
        """Supaya kebijakan bisa dibaca dari kode yang membangunnya."""
        hasil = PembangunKebijakan().bawaan("'none'").skrip("'self'").base_uri("'none'").bangun()
        self.assertEqual(hasil, "default-src 'none'; script-src 'self'; base-uri 'none'")

    def test_beberapa_sumber_dipisah_spasi(self) -> None:
        hasil = PembangunKebijakan().skrip("'self'", "https:").bangun()
        self.assertEqual(hasil, "script-src 'self' https:")

    def test_pembangun_kosong_menghasilkan_string_kosong(self) -> None:
        self.assertEqual(PembangunKebijakan().bangun(), "")
