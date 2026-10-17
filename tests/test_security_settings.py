import importlib
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

import config.settings as settings_module


class SecuritySettingsTests(SimpleTestCase):
    @contextmanager
    def _reloaded_settings(self, overrides: dict[str, str]) -> Iterator[None]:
        """Reload config.settings with env overrides, then restore.

        Overrides are set (not popped): load_dotenv() re-reads the local .env,
        while an explicitly set value blocks the override (dotenv never
        overwrites an existing variable) — an empty string then counts as
        unset downstream. Restoring the environment plus one more reload leaves
        every other test's import state untouched.
        """
        saved = {key: os.environ.get(key) for key in overrides}
        try:
            os.environ.update(overrides)
            importlib.reload(settings_module)
            yield
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            importlib.reload(settings_module)

    def _load_settings(
        self, *, debug: bool | None = None, fake_tokens: bool | None = None
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["DJANGO_DEBUG"] = str(debug).lower() if debug is not None else "false"
        environment.pop("PILAH_ALLOW_FAKE_GOOGLE_TOKEN", None)
        if fake_tokens is not None:
            environment["PILAH_ALLOW_FAKE_GOOGLE_TOKEN"] = str(fake_tokens).lower()

        return subprocess.run(
            [
                sys.executable,
                "-c",
                "import config.settings; print(config.settings.DEBUG); "
                "print(config.settings.PILAH_ALLOW_FAKE_GOOGLE_TOKEN)",
            ],
            cwd=Path(__file__).resolve().parent.parent,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_missing_secret_key_fails_closed_when_not_debug(self) -> None:
        with (
            self.assertRaises(ImproperlyConfigured) as caught,
            self._reloaded_settings({"DJANGO_SECRET_KEY": "", "DJANGO_DEBUG": "false"}),
        ):
            pass

        self.assertIn("DJANGO_SECRET_KEY must be set", str(caught.exception))

    def test_missing_secret_key_falls_back_only_in_debug(self) -> None:
        with self._reloaded_settings({"DJANGO_SECRET_KEY": "", "DJANGO_DEBUG": "true"}):
            # Random per-process fallback: non-empty, and not the dev-runaway
            # case where the env value leaks through — no literal to assert.
            self.assertTrue(settings_module.SECRET_KEY)

    def test_missing_secret_key_fallback_is_random_per_process(self) -> None:
        first: str
        second: str
        with self._reloaded_settings({"DJANGO_SECRET_KEY": "", "DJANGO_DEBUG": "true"}):
            first = settings_module.SECRET_KEY
        with self._reloaded_settings({"DJANGO_SECRET_KEY": "", "DJANGO_DEBUG": "true"}):
            second = settings_module.SECRET_KEY
        self.assertNotEqual(first, second)

    def test_explicit_secret_key_is_kept_unchanged(self) -> None:
        with self._reloaded_settings({"DJANGO_SECRET_KEY": "staging-real-key"}):
            self.assertEqual(settings_module.SECRET_KEY, "staging-real-key")

    def test_security_defaults_fail_closed(self) -> None:
        result = self._load_settings()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "False"])

    def test_fake_tokens_are_rejected_when_debug_is_disabled(self) -> None:
        result = self._load_settings(debug=False, fake_tokens=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PILAH_ALLOW_FAKE_GOOGLE_TOKEN", result.stderr)
