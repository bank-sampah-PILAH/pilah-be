from django.test import override_settings
from rest_framework.test import APITestCase

from shared_kernel.http_headers import HEADER_PERMINTAAN_KUSTOM, HEADER_RESPONS_TEREKSPOS


class CORSRegressionTests(APITestCase):
    def test_preflight_allows_configured_origin_and_authorization_header(self) -> None:
        with override_settings(
            CORS_ALLOW_ALL_ORIGINS=False,
            CORS_ALLOWED_ORIGINS=["http://localhost:7357"],
        ):
            response = self.client.options(
                "/api/v1/auth/google",
                HTTP_ORIGIN="http://localhost:7357",
                HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
                HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], "http://localhost:7357")
        self.assertIn("authorization", response["Access-Control-Allow-Headers"].lower())

    def test_preflight_does_not_allow_unlisted_origin(self) -> None:
        with override_settings(
            CORS_ALLOW_ALL_ORIGINS=False,
            CORS_ALLOWED_ORIGINS=["http://localhost:7357"],
        ):
            response = self.client.options(
                "/api/v1/auth/google",
                HTTP_ORIGIN="https://unlisted.example",
                HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
                HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type",
            )

        self.assertNotIn("Access-Control-Allow-Origin", response)

    def test_preflight_allows_the_idempotency_key_header(self) -> None:
        with override_settings(
            CORS_ALLOW_ALL_ORIGINS=False,
            CORS_ALLOWED_ORIGINS=["http://localhost:7357"],
        ):
            response = self.client.options(
                "/api/v1/transaksi",
                HTTP_ORIGIN="http://localhost:7357",
                HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
                HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type,idempotency-key",
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("idempotency-key", response["Access-Control-Allow-Headers"].lower())

    def test_response_exposes_content_disposition_to_the_browser(self) -> None:
        # Report exports send the file name in Content-Disposition. A browser
        # hides every response header from JavaScript unless it is listed in
        # Access-Control-Expose-Headers, so without this the download succeeds
        # but the client cannot recover the file name.
        with override_settings(
            CORS_ALLOW_ALL_ORIGINS=False,
            CORS_ALLOWED_ORIGINS=["http://localhost:7357"],
        ):
            response = self.client.get(
                "/api/v1/transaksi",
                HTTP_ORIGIN="http://localhost:7357",
            )

        self.assertIn("Access-Control-Expose-Headers", response)
        self.assertIn(
            "content-disposition",
            response["Access-Control-Expose-Headers"].lower(),
        )

    def test_every_registered_custom_request_header_passes_preflight(self) -> None:
        # Pins the registry in shared_kernel/http_headers.py to the preflight
        # answer. Adding a header there without letting CORS_ALLOW_HEADERS
        # derive from it is the exact defect this file exists to prevent, and
        # it is invisible to the native app.
        requested = ",".join(header.lower() for header in HEADER_PERMINTAAN_KUSTOM)
        with override_settings(
            CORS_ALLOW_ALL_ORIGINS=False,
            CORS_ALLOWED_ORIGINS=["http://localhost:7357"],
        ):
            response = self.client.options(
                "/api/v1/transaksi",
                HTTP_ORIGIN="http://localhost:7357",
                HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
                HTTP_ACCESS_CONTROL_REQUEST_HEADERS=requested,
            )

        allowed = response["Access-Control-Allow-Headers"].lower()
        self.assertTrue(HEADER_PERMINTAAN_KUSTOM, "registry must not be empty")
        for header in HEADER_PERMINTAAN_KUSTOM:
            with self.subTest(header=header):
                self.assertIn(header.lower(), allowed)

    def test_preflight_does_not_allow_an_unregistered_custom_header(self) -> None:
        with override_settings(
            CORS_ALLOW_ALL_ORIGINS=False,
            CORS_ALLOWED_ORIGINS=["http://localhost:7357"],
        ):
            response = self.client.options(
                "/api/v1/transaksi",
                HTTP_ORIGIN="http://localhost:7357",
                HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
                HTTP_ACCESS_CONTROL_REQUEST_HEADERS="x-pilah-tidak-terdaftar",
            )

        allowed = response["Access-Control-Allow-Headers"].lower()
        self.assertNotIn("x-pilah-tidak-terdaftar", allowed)
        self.assertNotIn("*", allowed)

    def test_exposes_exactly_the_registered_response_headers(self) -> None:
        with override_settings(
            CORS_ALLOW_ALL_ORIGINS=False,
            CORS_ALLOWED_ORIGINS=["http://localhost:7357"],
        ):
            response = self.client.get(
                "/api/v1/transaksi",
                HTTP_ORIGIN="http://localhost:7357",
            )

        exposed = [
            value.strip().lower()
            for value in response["Access-Control-Expose-Headers"].split(",")
            if value.strip()
        ]
        self.assertEqual(exposed, [header.lower() for header in HEADER_RESPONS_TEREKSPOS])
