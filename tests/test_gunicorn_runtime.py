import os
import sys
from unittest.mock import patch

from django.test import SimpleTestCase
from gunicorn.app.wsgiapp import WSGIApplication


class GunicornRuntimeTests(SimpleTestCase):
    def test_default_serves_parallel_requests_without_extra_workers(self) -> None:
        with (
            patch.object(sys, "argv", ["gunicorn", "config.wsgi:application"]),
            patch.dict(os.environ, {"GUNICORN_CMD_ARGS": "", "WEB_CONCURRENCY": "1"}),
        ):
            application = WSGIApplication()
        self.assertEqual(application.cfg.workers, 1)
        self.assertEqual(application.cfg.threads, 4)
        self.assertEqual(application.cfg.worker_class.__name__, "ThreadWorker")
