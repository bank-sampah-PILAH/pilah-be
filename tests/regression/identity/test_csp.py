"""Kontrak Content-Security-Policy: satu kebijakan per konteks respons.

Temuan nyata dari pemindaian OWASP ZAP terotentikasi terhadap backend lokal
(0 High, 2 Medium, 1 Low, 3 Informational) tinggal satu setelah ditriase:
tidak ada header CSP sama sekali, padahal `SecurityMiddleware` sudah memasang
X-Frame-Options, X-Content-Type-Options, Referrer-Policy dan COOP.
"""

from django.test import override_settings

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
