import os
import sys
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase
from gunicorn.app.wsgiapp import WSGIApplication

REPO_ROOT = Path(__file__).resolve().parents[1]
GUNICORN_CONFIG = str(REPO_ROOT / "gunicorn.conf.py")


class GunicornRuntimeTests(SimpleTestCase):
    def test_default_serves_parallel_requests_without_extra_workers(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                ["gunicorn", "--config", GUNICORN_CONFIG, "config.wsgi:application"],
            ),
            patch.dict(
                os.environ,
                {"GUNICORN_CMD_ARGS": "", "WEB_CONCURRENCY": "1"},
                clear=True,
            ),
        ):
            application = WSGIApplication()
        self.assertEqual(application.cfg.workers, 1)
        self.assertEqual(application.cfg.threads, 4)
        self.assertEqual(application.cfg.worker_class.__name__, "ThreadWorker")

    def test_operator_can_override_threads_with_environment(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                ["gunicorn", "--config", GUNICORN_CONFIG, "config.wsgi:application"],
            ),
            patch.dict(
                os.environ,
                {"GUNICORN_CMD_ARGS": "", "WEB_CONCURRENCY": "1", "GUNICORN_THREADS": "1"},
                clear=True,
            ),
        ):
            application = WSGIApplication()
        self.assertEqual(application.cfg.threads, 1)
        self.assertEqual(application.cfg.worker_class.__name__, "SyncWorker")

    def test_operator_can_restore_sync_workers_using_native_gunicorn_options(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                ["gunicorn", "--config", GUNICORN_CONFIG, "config.wsgi:application"],
            ),
            patch.dict(
                os.environ,
                {
                    "GUNICORN_CMD_ARGS": "--threads 1 --workers 2",
                    "WEB_CONCURRENCY": "1",
                    "GUNICORN_THREADS": "4",
                },
                clear=True,
            ),
        ):
            application = WSGIApplication()
        self.assertEqual(application.cfg.workers, 2)
        self.assertEqual(application.cfg.threads, 1)
        self.assertEqual(application.cfg.worker_class.__name__, "SyncWorker")

    def test_cloud_run_deploy_paths_keep_the_production_connection_budget(self) -> None:
        for path in (
            REPO_ROOT / "scripts/deploy-cloud-run.sh",
            REPO_ROOT / ".github/workflows/deploy-cloud-run.yml",
        ):
            with self.subTest(path=path.name):
                deploy = path.read_text()
                self.assertIn("GUNICORN_THREADS=1", deploy)
                self.assertIn("DB_CONN_MAX_AGE=0", deploy)
