import tomllib
from pathlib import Path

from django.test import SimpleTestCase, override_settings


class StagingDashboardCorsTests(SimpleTestCase):
    def test_only_configured_dashboard_receives_preflight_permission(self) -> None:
        config = tomllib.loads((Path(__file__).resolve().parents[1] / "fly.toml").read_text())
        env = config["env"]
        with override_settings(
            CORS_ALLOW_ALL_ORIGINS=env["CORS_ALLOW_ALL_ORIGINS"] == "true",
            CORS_ALLOWED_ORIGINS=env.get("CORS_ALLOWED_ORIGINS", "").split(","),
        ):
            for origin, allowed in (
                ("https://pilah-web-staging.fly.dev", True),
                ("https://evil.example.com", False),
                ("https://pilah-web-staging.fly.dev.evil.example.com", False),
            ):
                with self.subTest(origin=origin):
                    response = self.client.options(
                        "/api/v1/auth/google",
                        HTTP_ORIGIN=origin,
                        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
                        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,authorization",
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(
                        response.get("Access-Control-Allow-Origin"), origin if allowed else None
                    )
