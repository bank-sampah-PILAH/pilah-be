import importlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

from django.core.asgi import get_asgi_application
from django.core.exceptions import ImproperlyConfigured
from django.core.wsgi import get_wsgi_application
from django.test import SimpleTestCase, override_settings
from django.urls import clear_url_caches, resolve


class ServerEntrypointTests(SimpleTestCase):
    def test_asgi_module_exposes_the_django_application(self) -> None:
        import config.asgi

        importlib.reload(config.asgi)

        self.assertTrue(callable(config.asgi.application))
        self.assertIsInstance(config.asgi.application, type(get_asgi_application()))

    def test_wsgi_module_exposes_the_django_application(self) -> None:
        import config.wsgi

        importlib.reload(config.wsgi)

        self.assertTrue(callable(config.wsgi.application))
        self.assertIsInstance(config.wsgi.application, type(get_wsgi_application()))


@contextmanager
def _reloaded(module_name: str, env: dict[str, str]) -> Iterator[object]:
    """Re-run a config module under a patched environment, then restore it."""
    module = importlib.import_module(module_name)
    try:
        with patch.dict(os.environ, env):
            yield importlib.reload(module)
    finally:
        importlib.reload(module)


class SettingsInProcessTests(SimpleTestCase):
    def test_migration_linter_app_is_registered_only_when_requested(self) -> None:
        with _reloaded("config.settings", {"MIGRATION_LINTER": "1"}) as module:
            self.assertIn("django_migration_linter", module.INSTALLED_APPS)  # type: ignore[attr-defined]

        import config.settings

        self.assertNotIn("django_migration_linter", config.settings.INSTALLED_APPS)

    def test_fake_google_tokens_refuse_to_load_without_debug(self) -> None:
        import config.settings

        env = {"DJANGO_DEBUG": "false", "PILAH_ALLOW_FAKE_GOOGLE_TOKEN": "true"}
        try:
            with (
                patch.dict(os.environ, env),
                self.assertRaisesRegex(ImproperlyConfigured, "PILAH_ALLOW_FAKE_GOOGLE_TOKEN"),
            ):
                importlib.reload(config.settings)
        finally:
            importlib.reload(config.settings)


class MediaRoutingTests(SimpleTestCase):
    def tearDown(self) -> None:
        import config.urls

        importlib.reload(config.urls)
        clear_url_caches()

    def test_logo_media_is_routed_only_when_serving_media_is_enabled(self) -> None:
        import config.urls

        with override_settings(SERVE_MEDIA=False):
            importlib.reload(config.urls)
            clear_url_caches()
            self.assertFalse(self._routes_logo())

        with override_settings(SERVE_MEDIA=True):
            importlib.reload(config.urls)
            clear_url_caches()
            self.assertTrue(self._routes_logo())

    @staticmethod
    def _routes_logo() -> bool:
        from django.urls import Resolver404

        try:
            resolve("/media/bank_sampah/logo/a.png")
        except Resolver404:
            return False
        return True
