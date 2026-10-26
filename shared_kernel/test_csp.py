"""Sifat yang harus berlaku pada SETIAP kebijakan CSP, bukan pada satu saja."""

from django.test import SimpleTestCase

from shared_kernel.csp import (
    DIRI,
    HTTPS,
    KEBIJAKAN_API,
    PembangunKebijakan,
    kebijakan_halaman,
    kebijakan_halaman_bernonce,
    nonce_baru,
)

NONCE_CONTOH = "CONTOHNONCE"

SEMUA_KEBIJAKAN = {
    "api": KEBIJAKAN_API,
    "halaman (produksi)": kebijakan_halaman(False),
    "halaman (pengembangan, CDN)": kebijakan_halaman(True),
    "halaman pengembang bernonce": kebijakan_halaman(True, NONCE_CONTOH),
    "dokumen tertutup bernonce": kebijakan_halaman_bernonce(NONCE_CONTOH),
}
"""Termasuk varian CDN, yang tidak pernah dilewati suite lewat permintaan HTTP.

Runner Django memaksa `DEBUG=False` selama test, jadi cabang itu hanya bisa
diuji dengan memanggil penyusunnya langsung. Tanpa baris ini separuh
`kebijakan_halaman` tidak pernah dijalankan test mana pun.
"""

BERNONCE = {"halaman pengembang bernonce", "dokumen tertutup bernonce"}
"""Kebijakan yang memang membawa nonce; sisanya tidak boleh membawanya.

Dipisah supaya menambah kebijakan bernonce baru tanpa mendaftarkannya di sini
membuat testnya gagal, alih-alih lolos karena namanya tidak dikenali.
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

    def test_nama_bernonce_memang_ada_di_semua_kebijakan(self) -> None:
        """Salah tulis nama di `BERNONCE` membuat test di bawah ini hampa."""
        self.assertLessEqual(BERNONCE, set(SEMUA_KEBIJAKAN))

    def test_hanya_kebijakan_bernonce_mengizinkan_skrip_inline(self) -> None:
        for nama, kebijakan in SEMUA_KEBIJAKAN.items():
            with self.subTest(kebijakan=nama):
                if nama in BERNONCE:
                    self.assertIn(f"'nonce-{NONCE_CONTOH}'", kebijakan)
                else:
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

    def test_arahan_yang_sama_dua_kali_ditolak(self) -> None:
        """Peramban memakai arahan pertama dan mengabaikan duplikatnya.

        Jadi `script-src` kedua tidak melonggarkan apa pun maupun memperketat
        apa pun: ia diam-diam mati. Itu mode kegagalan yang modul ini ada
        untuk mencegahnya, jadi penyusunnya menolaknya di tempat.
        """
        with self.assertRaises(ValueError):
            PembangunKebijakan().skrip(DIRI).skrip(HTTPS)

    def test_arahan_berbeda_tetap_boleh_berurutan(self) -> None:
        self.assertEqual(
            PembangunKebijakan().skrip(DIRI).gaya(DIRI).bangun(),
            "script-src 'self'; style-src 'self'",
        )


class KebijakanHalamanPengembangTests(SimpleTestCase):
    """Dua arahan yang hanya dibuka saat pengembangan.

    `api-test` memakai Google Identity Services: skripnya dari
    accounts.google.com, iframe tombol masuknya, dan panggilan `fetch` ke API.
    Tanpa `connect-src` dan `frame-src` keduanya jatuh ke `default-src 'self'`
    dan halaman itu gagal pada hal yang sulit ditebak dari pesan peramban.
    """

    def test_produksi_tidak_membuka_connect_maupun_frame(self) -> None:
        kebijakan = kebijakan_halaman(False)
        self.assertNotIn("connect-src", kebijakan)
        self.assertNotIn("frame-src", kebijakan)

    def test_pengembangan_membuka_connect_dan_frame(self) -> None:
        kebijakan = kebijakan_halaman(True)
        self.assertIn("connect-src 'self' https:", kebijakan)
        self.assertIn("frame-src https:", kebijakan)

    def test_nonce_menumpang_pada_sumber_yang_sudah_ada(self) -> None:
        """Nonce menambah izin untuk tag inline, bukan menggantikan `'self'`.

        `frame-src` disebut terpisah supaya `frame-ancestors` yang arahnya
        berlawanan tidak ikut tertukar tanpa ada yang menyadarinya.
        """
        kebijakan = kebijakan_halaman(True, NONCE_CONTOH)
        self.assertIn(f"script-src 'self' https: 'nonce-{NONCE_CONTOH}'", kebijakan)
        self.assertIn(f"style-src 'self' https: 'nonce-{NONCE_CONTOH}'", kebijakan)
        self.assertIn("frame-ancestors 'none'", kebijakan)
