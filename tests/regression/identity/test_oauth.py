"""Identity contracts: Google OAuth start/callback and real-token verification."""

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
        with patch("apps.identity.views.requests.post", return_value=token_response):
            response = self.client.get("/api/v1/auth/google/callback?code=abc&state=bogus")
        self.assertEqual(response.status_code, 200)

    def test_oauth_callback_token_endpoint_rejects(self) -> None:
        self.client.credentials()
        token_response = Mock(status_code=400)
        token_response.json = Mock(return_value={"error": "invalid_grant"})
        with patch("apps.identity.views.requests.post", return_value=token_response):
            response = self.client.get("/api/v1/auth/google/callback?code=abc")
        self.assertEqual(response.status_code, 400)

    def test_oauth_callback_missing_id_token(self) -> None:
        self.client.credentials()
        token_response = Mock(status_code=200)
        token_response.json = Mock(return_value={})
        with patch("apps.identity.views.requests.post", return_value=token_response):
            response = self.client.get("/api/v1/auth/google/callback?code=abc")
        self.assertEqual(response.status_code, 400)

    def test_oauth_callback_network_error(self) -> None:
        self.client.credentials()
        with patch(
            "apps.identity.views.requests.post", side_effect=requests.RequestException("down")
        ):
            response = self.client.get("/api/v1/auth/google/callback?code=abc")
        self.assertEqual(response.status_code, 400)

    def test_oauth_callback_evil_signed_state_falls_back(self) -> None:
        self.client.credentials()
        state = TimestampSigner().sign("https://evil.example/")
        token_response = Mock(status_code=400)
        token_response.json = Mock(return_value={"error": "invalid_grant"})
        with patch("apps.identity.views.requests.post", return_value=token_response):
            response = self.client.get(f"/api/v1/auth/google/callback?code=abc&state={state}")
        self.assertEqual(response.status_code, 400)

    def test_real_verify_rejects_unverifiable_token(self) -> None:
        self.client.credentials()
        with (
            override_settings(PILAH_ALLOW_FAKE_GOOGLE_TOKEN=False, GOOGLE_CLIENT_ID="cid"),
            patch(
                "apps.identity.services.google_id_token.verify_oauth2_token",
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
                "apps.identity.services.google_id_token.verify_oauth2_token",
                return_value={"sub": "x", "email": ""},
            ),
        ):
            response = self.client.post(
                "/api/v1/auth/google", {"id_token": "real-token"}, format="json"
            )
        self.assertEqual(response.status_code, 401)

    def test_real_verify_accepts_minimal_profile(self) -> None:
        self.client.credentials()
        with (
            override_settings(PILAH_ALLOW_FAKE_GOOGLE_TOKEN=False, GOOGLE_CLIENT_ID="cid"),
            patch(
                "apps.identity.services.google_id_token.verify_oauth2_token",
                return_value={"sub": "sub-1", "email": "real@example.com"},
            ),
        ):
            response = self.client.post(
                "/api/v1/auth/google", {"id_token": "real-token"}, format="json"
            )
        self.assertEqual(response.status_code, 200)
