"""Run each config module in a fresh namespace.

`runpy.run_module` executes the module's code without touching `sys.modules`,
so the live `config.settings` / `config.urls` the rest of the suite relies on
are never reloaded or mutated.
"""

import os
import runpy
from typing import Any
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.core.handlers.asgi import ASGIHandler
from django.core.handlers.wsgi import WSGIHandler
from django.test import SimpleTestCase, override_settings
from django.urls import Resolver404, URLResolver
from django.urls.resolvers import RegexPattern


def _run(module_name: str) -> dict[str, Any]:
    return runpy.run_module(module_name, run_name=f"{module_name}.probe")


class ServerEntrypointTests(SimpleTestCase):
    def test_asgi_module_exposes_the_django_application(self) -> None:
        self.assertIsInstance(_run("config.asgi")["application"], ASGIHandler)

    def test_wsgi_module_exposes_the_django_application(self) -> None:
        self.assertIsInstance(_run("config.wsgi")["application"], WSGIHandler)


class SettingsInProcessTests(SimpleTestCase):
    def test_migration_linter_app_is_registered_only_when_requested(self) -> None:
        with patch.dict(os.environ, {"MIGRATION_LINTER": "1"}):
            self.assertIn("django_migration_linter", _run("config.settings")["INSTALLED_APPS"])
        with patch.dict(os.environ, {"MIGRATION_LINTER": "0"}):
            self.assertNotIn("django_migration_linter", _run("config.settings")["INSTALLED_APPS"])

    def test_fake_google_tokens_refuse_to_load_without_debug(self) -> None:
        env = {"DJANGO_DEBUG": "false", "PILAH_ALLOW_FAKE_GOOGLE_TOKEN": "true"}
        with (
            patch.dict(os.environ, env),
            self.assertRaisesRegex(ImproperlyConfigured, "PILAH_ALLOW_FAKE_GOOGLE_TOKEN"),
        ):
            _run("config.settings")

    def test_production_without_superadmin_emails_warns_that_logins_are_rejected(self) -> None:
        env = {
            "DJANGO_DEBUG": "false",
            "PILAH_ALLOW_FAKE_GOOGLE_TOKEN": "false",
            "PILAH_SUPERADMIN_EMAILS": "",
        }
        with patch.dict(os.environ, env), self.assertLogs(level="WARNING") as logs:
            _run("config.settings")

        self.assertIn("PILAH_SUPERADMIN_EMAILS is empty", logs.output[0])


class MediaRoutingTests(SimpleTestCase):
    @staticmethod
    def _routes_logo() -> bool:
        resolver = URLResolver(RegexPattern(r"^/"), _run("config.urls")["urlpatterns"])
        try:
            resolver.resolve("/media/bank_sampah/logo/a.png")
        except Resolver404:
            return False
        return True

    def test_logo_media_is_routed_only_when_serving_media_is_enabled(self) -> None:
        with override_settings(SERVE_MEDIA=False):
            self.assertFalse(self._routes_logo())
        with override_settings(SERVE_MEDIA=True):
            self.assertTrue(self._routes_logo())
