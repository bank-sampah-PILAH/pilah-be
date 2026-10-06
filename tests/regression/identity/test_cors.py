from django.test import override_settings
from rest_framework.test import APITestCase


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
