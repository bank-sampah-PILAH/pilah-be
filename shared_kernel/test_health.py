from unittest.mock import patch

from django.db import OperationalError
from django.test import TestCase


class HealthzTests(TestCase):
    def test_reports_ok_when_database_answers(self) -> None:
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": True})

    def test_reports_degraded_when_database_is_unreachable(self) -> None:
        with patch("shared_kernel.health.connection.cursor", side_effect=OperationalError("down")):
            response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "degraded", "database": False})
