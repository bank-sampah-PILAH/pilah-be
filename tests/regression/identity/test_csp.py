"""Kontrak Content-Security-Policy: satu kebijakan per konteks respons.

Temuan nyata dari pemindaian OWASP ZAP terotentikasi terhadap backend lokal
(0 High, 2 Medium, 1 Low, 3 Informational) tinggal satu setelah ditriase:
tidak ada header CSP sama sekali, padahal `SecurityMiddleware` sudah memasang
X-Frame-Options, X-Content-Type-Options, Referrer-Policy dan COOP.
"""

import os

from django.test import SimpleTestCase

from tests.regression.helpers import RegressionTestCase


class CspApiTests(RegressionTestCase):
    def test_respons_api_membawa_kebijakan_paling_ketat(self) -> None:
        """JSON tidak memuat subsumber apa pun, jadi tidak ada yang perlu
        diizinkan — dan `default-src 'none'` tidak bisa merusak apa pun."""
        self.client.credentials()
        response = self.client.get("/api/v1/auth/google/start")
        kebijakan = response.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'none'", kebijakan)
        self.assertIn("frame-ancestors 'none'", kebijakan)
        self.assertIn("base-uri 'none'", kebijakan)


class CspPopupOAuthTests(RegressionTestCase):
    """Satu-satunya halaman publik yang menjalankan skrip inline.

    Halaman ini juga yang mencetak nilai dari luar, jadi di sinilah CSP
    benar-benar berguna sebagai lapisan kedua. `script-src 'self'` akan
    memblokir skripnya sendiri, jadi yang dipakai nonce per respons.
    """

    def _popup(self) -> "object":
        self.client.credentials()
        return self.client.get("/api/v1/auth/google/callback", {"error": "access_denied"})

    def test_kebijakan_mengizinkan_skrip_hanya_lewat_nonce(self) -> None:
        response = self._popup()
        kebijakan = response.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'none'", kebijakan)
        self.assertIn("script-src 'nonce-", kebijakan)
        self.assertNotIn("'unsafe-inline'", kebijakan)

    def test_nonce_pada_header_sama_dengan_nonce_pada_tag_skrip(self) -> None:
        """Nonce yang tidak cocok memblokir skripnya sendiri, dan tidak ada
        test lain yang akan menyadarinya."""
        response = self._popup()
        kebijakan = response.headers["Content-Security-Policy"]
        awal = kebijakan.index("'nonce-") + len("'nonce-")
        nonce = kebijakan[awal : kebijakan.index("'", awal)]
        self.assertIn(f'<script nonce="{nonce}">', response.content.decode())

    def test_nonce_berbeda_untuk_setiap_respons(self) -> None:
        """Nonce yang bisa diramalkan sama saja dengan 'unsafe-inline'."""
        kebijakan = [self._popup().headers["Content-Security-Policy"] for _ in range(2)]
        self.assertNotEqual(kebijakan[0], kebijakan[1])


def _debug_saat_setelan_dimuat() -> bool:
    """Nilai yang benar-benar memilih daftar renderer.

    Bukan `settings.DEBUG`: Django memaksanya `False` selama test berjalan,
    jadi di dalam test nilai itu tidak pernah mencerminkan konfigurasi yang
    menyusun `DEFAULT_RENDERER_CLASSES` saat impor.
    """
    return os.getenv("DJANGO_DEBUG", "false").lower() == "true"


class RendererProduksiTests(SimpleTestCase):
    """API JSON tidak perlu melayani HTML di produksi.

    `DEFAULT_RENDERER_CLASSES` tidak pernah diset, jadi bawaan DRF berlaku dan
    `BrowsableAPIRenderer` ikut aktif. Artinya setiap endpoint API membalas
    dokumen HTML begitu klien mengirim `Accept: text/html` — permukaan HTML
    yang tidak dipakai klien Flutter, dan yang memaksa kebijakan CSP jauh
    lebih longgar untuk seluruh API.

    Test ini salah tiga kali sebelum benar, selalu karena `DEBUG` di dalam
    test bukan `DEBUG` yang memilih renderer:

    1. `override_settings(DEBUG=False)` — daftar renderer diturunkan saat
       setelan dimuat dan tidak bisa diubah setelah impor, jadi test LULUS
       hanya karena lingkungannya memang sudah produksi.
    2. Membandingkan dengan `settings.DEBUG` dari dalam `RegressionTestCase` —
       `tests/regression/helpers.py` membungkus kelas dasar itu dengan
       `override_settings(DEBUG=True)` untuk alur token Google palsu.
    3. Membandingkan dengan `settings.DEBUG` dari `SimpleTestCase` — runner
       Django memaksa `DEBUG=False` selama test, apa pun konfigurasinya.

    Yang dipakai sekarang variabel lingkungan yang benar-benar menyusun
    daftarnya, dan invariannya dikunci pada KEDUA konfigurasi.
    """

    @staticmethod
    def _nama_renderer() -> list[str]:
        from rest_framework.settings import api_settings

        return [r.__name__ for r in api_settings.DEFAULT_RENDERER_CLASSES]

    def test_json_selalu_menjadi_renderer_utama(self) -> None:
        self.assertEqual(self._nama_renderer()[0], "JSONRenderer")

    def test_browsable_renderer_mengikuti_debug(self) -> None:
        """Satu-satunya alasan sah halaman itu ada adalah kenyamanan lokal."""
        self.assertEqual(
            "BrowsableAPIRenderer" in self._nama_renderer(),
            _debug_saat_setelan_dimuat(),
            "browsable API harus mengikuti DEBUG: aktif saat pengembangan, tidak ada di produksi",
        )

    def test_endpoint_api_tidak_melayani_html_di_konfigurasi_produksi(self) -> None:
        """Konsekuensi yang bisa diamati, diuji ketika konfigurasinya memang
        konfigurasi produksi — bukan lewat DEBUG palsu."""
        if _debug_saat_setelan_dimuat():
            self.skipTest("butuh konfigurasi produksi (DJANGO_DEBUG tidak aktif)")
        response = self.client.get("/api/v1/auth/google/start", HTTP_ACCEPT="text/html")
        self.assertNotIn("text/html", response.get("Content-Type", ""))


class CspHalamanDjangoTests(SimpleTestCase):
    """Halaman HTML yang tersisa di produksi setelah browsable API dimatikan:
    admin, dan popup OAuth yang punya kebijakannya sendiri.

    Admin Django 6 ternyata bersih dari skrip dan gaya inline — ketiga
    `<script id="django-admin-…-constants">` pada templatenya semua memakai
    `src=` dengan atribut `data-*`, bukan JavaScript inline. Jadi halaman ini
    tidak butuh `'unsafe-inline'` sama sekali, dan kebijakannya diperiksa
    justru untuk memastikan tidak ada yang menambahkannya nanti.
    """

    def test_admin_membawa_kebijakan_tanpa_unsafe_inline(self) -> None:
        response = self.client.get("/admin/login/")
        self.assertEqual(response.status_code, 200)
        kebijakan = response.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", kebijakan)
        self.assertIn("frame-ancestors 'none'", kebijakan)
        self.assertIn("base-uri 'none'", kebijakan)
        self.assertIn("form-action 'self'", kebijakan)
        self.assertNotIn("'unsafe-inline'", kebijakan)

    def test_admin_tidak_memuat_skrip_atau_gaya_inline(self) -> None:
        """Alasan kebijakan di atas boleh seketat itu, dikunci sebagai fakta.

        Kalau versi Django berikutnya memasukkan kembali skrip inline ke
        admin, test ini gagal lebih dulu dan menjelaskan sebabnya — alih-alih
        halaman admin yang rusak tanpa petunjuk di produksi.
        """
        import re

        body = self.client.get("/admin/login/").content.decode()
        self.assertEqual(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", body), [])
        self.assertEqual(re.findall(r"<style[^>]*>", body), [])
        self.assertEqual(re.findall(r'\sstyle="', body), [])
