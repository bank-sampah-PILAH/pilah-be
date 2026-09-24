import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


class SecuritySettingsTests(SimpleTestCase):
    def _load_settings(
        self, *, debug: bool | None = None, fake_tokens: bool | None = None
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.pop("DJANGO_DEBUG", None)
        environment.pop("PILAH_ALLOW_FAKE_GOOGLE_TOKEN", None)
        if debug is not None:
            environment["DJANGO_DEBUG"] = str(debug).lower()
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

    def test_security_defaults_fail_closed(self) -> None:
        result = self._load_settings()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "False"])

    def test_fake_tokens_are_rejected_when_debug_is_disabled(self) -> None:
        result = self._load_settings(debug=False, fake_tokens=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PILAH_ALLOW_FAKE_GOOGLE_TOKEN", result.stderr)
