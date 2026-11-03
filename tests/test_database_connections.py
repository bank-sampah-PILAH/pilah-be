import os
import runpy
from pathlib import Path
from typing import Any
from unittest.mock import patch

from django.test import SimpleTestCase


class DatabaseConnectionSettingsTests(SimpleTestCase):
    def database_settings(self, max_age: str | None = None) -> dict[str, Any]:
        with patch.dict(os.environ, {"DJANGO_DEBUG": "true", "PYTHON_DOTENV_DISABLED": "1"}):
            os.environ.pop("DB_CONN_MAX_AGE", None)
            if max_age is not None:
                os.environ["DB_CONN_MAX_AGE"] = max_age
            loaded = runpy.run_path(str(Path(__file__).resolve().parents[1] / "config/settings.py"))
            database: dict[str, Any] = loaded["DATABASES"]["default"]
            return database

    def test_default_reuses_connections_for_a_bounded_minute_with_health_checks(self) -> None:
        database = self.database_settings()
        self.assertEqual(database.get("CONN_MAX_AGE"), 60)
        self.assertTrue(database["CONN_HEALTH_CHECKS"])
