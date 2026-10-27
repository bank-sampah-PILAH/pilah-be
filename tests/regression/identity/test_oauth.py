"""Identity contracts: Google OAuth start/callback and real-token verification."""

import json
from typing import Any
from unittest.mock import Mock, patch

import requests
from django.core.signing import TimestampSigner
from django.test import override_settings

from tests.regression.helpers import RegressionTestCase


class OAuthRegressionTests(RegressionTestCase):
    def test_oauth_start_unconfigured_or_redirects(self) -> None:
        self.client.credentials()
        response = self.client.get("/api/v1/auth/google/start")
        self.assertIn(response.status_code, (302, 503))

    @override_settings(GOOGLE_CLIENT_ID="cid", GOOGLE_CLIENT_SECRET="csec")
    def test_oauth_start_configured_redirects(self) -> None:
        self.client.credentials()
        response = self.client.get("/api/v1/auth/google/start")
        self.assertEqual(response.status_code, 302)
        self.assertIn("accounts.google.com", response["Location"])

    def test_oauth_start_rejects_external_next(self) -> None:
        self.client.credentials()
        with override_settings(GOOGLE_CLIENT_ID="cid", GOOGLE_CLIENT_SECRET="csec"):
            response = self.client.get("/api/v1/auth/google/start?next=https://evil.example/")
        self.assertEqual(response.status_code, 302)

    def test_oauth_callback_error_param(self) -> None:
        self.client.credentials()
        response = self.client.get("/api/v1/auth/google/callback?error=access_denied")
        self.assertEqual(response.status_code, 400)

    def test_oauth_callback_missing_code(self) -> None:
        self.client.credentials()
        self.assertEqual(self.client.get("/api/v1/auth/google/callback").status_code, 400)

    def test_oauth_callback_bad_state_still_exchanges(self) -> None:
        self.client.credentials()
        token_response = Mock(status_code=200)
        token_response.json = Mock(return_value={"id_token": "dev:baru@example.com:Baru"})
        with patch("apps.authentication.views.requests.post", return_value=token_response):
            response = self.client.get("/api/v1/auth/google/callback?code=abc&state=bogus")
        self.assertEqual(response.status_code, 200)

    def test_oauth_callback_token_endpoint_rejects(self) -> None:
        self.client.credentials()
        token_response = Mock(status_code=400)
        token_response.json = Mock(return_value={"error": "invalid_grant"})
        with patch("apps.authentication.views.requests.post", return_value=token_response):
            response = self.client.get("/api/v1/auth/google/callback?code=abc")
        self.assertEqual(response.status_code, 400)

    def test_oauth_callback_missing_id_token(self) -> None:
        self.client.credentials()
        token_response = Mock(status_code=200)
        token_response.json = Mock(return_value={})
        with patch("apps.authentication.views.requests.post", return_value=token_response):
            response = self.client.get("/api/v1/auth/google/callback?code=abc")
        self.assertEqual(response.status_code, 400)

    def test_oauth_callback_network_error(self) -> None:
        self.client.credentials()
        with patch(
            "apps.authentication.views.requests.post", side_effect=requests.RequestException("down")
        ):
            response = self.client.get("/api/v1/auth/google/callback?code=abc")
        self.assertEqual(response.status_code, 400)

    def test_oauth_callback_evil_signed_state_falls_back(self) -> None:
        self.client.credentials()
        state = TimestampSigner().sign("https://evil.example/")
        token_response = Mock(status_code=400)
        token_response.json = Mock(return_value={"error": "invalid_grant"})
        with patch("apps.authentication.views.requests.post", return_value=token_response):
            response = self.client.get(f"/api/v1/auth/google/callback?code=abc&state={state}")
        self.assertEqual(response.status_code, 400)

    def test_real_verify_rejects_unverifiable_token(self) -> None:
        self.client.credentials()
        with (
            override_settings(PILAH_ALLOW_FAKE_GOOGLE_TOKEN=False, GOOGLE_CLIENT_ID="cid"),
            patch(
                "apps.authentication.services.google_id_token.verify_oauth2_token",
                side_effect=Exception("bad"),
            ),
        ):
            response = self.client.post(
                "/api/v1/auth/google", {"id_token": "real-token"}, format="json"
            )
        self.assertEqual(response.status_code, 401)

    def test_real_verify_rejects_profile_without_email(self) -> None:
        self.client.credentials()
        with (
            override_settings(PILAH_ALLOW_FAKE_GOOGLE_TOKEN=False, GOOGLE_CLIENT_ID="cid"),
            patch(
                "apps.authentication.services.google_id_token.verify_oauth2_token",
                return_value={"sub": "x", "email": ""},
            ),
        ):
            response = self.client.post(
                "/api/v1/auth/google", {"id_token": "real-token"}, format="json"
            )
        self.assertEqual(response.status_code, 401)

    def test_real_verify_rejects_token_with_wrong_web_audience(self) -> None:
        self.client.credentials()

        def verify_audience(
            _token: str, _request: object, audience: str | None
        ) -> dict[str, object]:
            if audience != "web-client-id":
                raise ValueError("Wrong audience")
            return {"sub": "sub-1", "email": "real@example.com", "email_verified": True}

        with (
            override_settings(
                PILAH_ALLOW_FAKE_GOOGLE_TOKEN=False, GOOGLE_CLIENT_ID="other-client-id"
            ),
            patch(
                "apps.authentication.services.google_id_token.verify_oauth2_token",
                side_effect=verify_audience,
            ) as verify,
        ):
            response = self.client.post(
                "/api/v1/auth/google", {"id_token": "token-for-web-client"}, format="json"
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(verify.call_args.args[2], "other-client-id")

    def test_real_verify_accepts_minimal_profile(self) -> None:
        self.client.credentials()
        with (
            override_settings(
                PILAH_ALLOW_FAKE_GOOGLE_TOKEN=False,
                GOOGLE_CLIENT_ID="web-client-id",
            ),
            patch(
                "apps.authentication.services.google_id_token.verify_oauth2_token",
                return_value={
                    "sub": "sub-1",
                    "email": "real@example.com",
                    "email_verified": True,
                },
            ) as verify,
        ):
            response = self.client.post(
                "/api/v1/auth/google", {"id_token": "real-token"}, format="json"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(verify.call_args.args[2], "web-client-id")


class OAuthPopupEscapingTests(RegressionTestCase):
    """Halaman popup OAuth menyusun HTML sendiri, jadi setiap nilai yang ikut
    tercetak harus lolos dari konteksnya.

    ``?error=`` sampai ke halaman tanpa autentikasi apa pun, dan ``json.dumps``
    tidak meloloskan ``<``, ``>``, maupun ``/``. Nilai itu mendarat di dua
    tempat dengan aturan lolos yang berbeda: badan ``<pre>`` (konteks HTML) dan
    blok ``<script>`` (konteks skrip). Masing-masing dikunci terpisah, karena
    memperbaiki satu tidak memperbaiki yang lain.
    """

    PEMBOBOL = "</pre><script>alert(document.domain)</script>"

    def _popup(self, **params: str) -> str:
        self.client.credentials()
        response = self.client.get("/api/v1/auth/google/callback", params)
        body: str = response.content.decode()
        return body

    @staticmethod
    def _blok_pre(body: str) -> str:
        awal = body.index("<pre>") + len("<pre>")
        return body[awal : body.index("</pre>", awal)]

    def test_blok_pre_tidak_bisa_ditutup_oleh_nilai_error(self) -> None:
        blok = self._blok_pre(self._popup(error=self.PEMBOBOL))
        self.assertNotIn("<", blok)
        self.assertNotIn(">", blok)
        self.assertIn("&lt;/pre&gt;", blok)

    @staticmethod
    def _blok_skrip(body: str) -> str:
        """Tag pembukanya membawa atribut nonce, jadi dicari sampai `>`."""
        awal = body.index(">", body.index("<script")) + 1
        return body[awal : body.index("</script>", awal)]

    def test_blok_skrip_tidak_bisa_ditutup_oleh_nilai_error(self) -> None:
        blok = self._blok_skrip(self._popup(error=self.PEMBOBOL))
        self.assertNotIn("</script", blok)
        self.assertNotIn("<script", blok)

    def test_next_url_bertanda_tangan_tidak_menambah_elemen_skrip(self) -> None:
        """`next` hanya diperiksa berawalan "/" sebelum ditandatangani, jadi
        tanda tangan justru meloloskan markup ke dalam blok skrip callback.

        Nilai ini hanya terbaca pada jalur tukar-token, bukan pada cabang
        `?error=`, jadi pertukaran tokennya distub di batas HTTP.

        Pemeriksaannya menghitung elemen skrip pada seluruh dokumen, bukan
        memotong blok pertama. Versi pertama test ini memotong, dan lulus
        terhadap kode yang masih bocor: pemotong `</script>` justru berhenti
        pada tag tutup milik penyerang, sehingga `<script>` suntikan berada di
        luar potongan dan tidak pernah ikut diperiksa.
        """
        jahat = "/</script><script>alert(document.domain)</script>"
        self.assertTrue(jahat.startswith("/"), "harus lolos satu-satunya validasi start")
        state = TimestampSigner().sign(jahat)
        token_response = Mock(status_code=400)
        token_response.json = Mock(return_value={"error": "invalid_grant"})
        self.client.credentials()
        with patch("apps.authentication.views.requests.post", return_value=token_response):
            response = self.client.get(
                "/api/v1/auth/google/callback", {"code": "abc", "state": state}
            )
        body = response.content.decode()
        self.assertIn("window.location.href", body)
        self.assertEqual(body.count("<script"), 1)
        self.assertEqual(body.count("</script"), 1)

    @staticmethod
    def _pesan_terparse(body: str) -> Any:
        """Ambil literal `const message = …;` lalu parse sebagai JSON.

        `\u003c` adalah escape JSON yang sah, jadi parser Python membacanya
        sama seperti `JSON.parse` di browser. Test ini karena itu memeriksa
        kontrak yang betul-betul dilihat klien, bukan tiruannya.
        """
        awal = body.index("const message = ") + len("const message = ")
        return json.loads(body[awal : body.index(";\n", awal)])

    def test_payload_wajar_tetap_terkirim_utuh(self) -> None:
        """Meloloskan nilai tidak boleh mengubah kontrak `postMessage`."""
        pesan = self._pesan_terparse(self._popup(error="access_denied"))
        self.assertEqual(pesan["type"], "pilah-google-oauth")
        self.assertFalse(pesan["ok"])
        self.assertEqual(pesan["payload"], {"error": "access_denied"})

    def test_payload_berbahaya_tetap_utuh_setelah_diparse(self) -> None:
        """Meloloskan bukan menyaring: datanya tetap sama persis, yang hilang
        hanya kemampuannya dieksekusi.

        Kalau perbaikannya memotong atau membuang karakter, pengurus akan
        membaca pesan galat Google yang sudah berubah — jadi kesamaan string
        ini sengaja dikunci, bukan sekadar ketiadaan tag.
        """
        pesan = self._pesan_terparse(self._popup(error=self.PEMBOBOL))
        self.assertEqual(pesan["payload"], {"error": self.PEMBOBOL})
