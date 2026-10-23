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
