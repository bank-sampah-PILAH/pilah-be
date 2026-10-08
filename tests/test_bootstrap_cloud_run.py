import json
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

from django.test import SimpleTestCase

from scripts.bootstrap_cloud_run import bootstrap_cloud_run, validate_configuration


class BootstrapCloudRunTests(SimpleTestCase):
    def test_job_uses_deployed_image_runtime_identity_and_environment_and_waits(self) -> None:
        service: dict[str, Any] = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "run.googleapis.com/cloudsql-instances": "project:region:db",
                            "run.googleapis.com/vpc-access-connector": "connector",
                        }
                    },
                    "spec": {
                        "serviceAccountName": "runtime@example.iam.gserviceaccount.com",
                        "containers": [
                            {
                                "image": "registry/image:verified-sha",
                                "env": [
                                    {"name": "DB_PASSWORD", "value": "never-print-me"},
                                    {"name": "PILAH_ENVIRONMENT", "value": "production"},
                                    {
                                        "name": "PILAH_SUPERADMIN_EMAILS",
                                        "value": "admin@example.com",
                                    },
                                    {
                                        "name": "DJANGO_SECRET_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {"name": "secret", "key": "latest"},
                                        },
                                    },
                                ],
                            }
                        ],
                    },
                }
            },
        }
        env = {
            "PROJECT_ID": "project",
            "REGION": "region",
            "SERVICE_NAME": "pilah-be",
            "PILAH_WEB_ORIGIN": "https://pilah-web-real-provider.run.app",
            "PILAH_SUPERADMIN_EMAILS": "admin@example.com",
        }
        commands: list[list[str]] = []

        def gcloud(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            commands.append(argv)
            if "describe" in argv:
                return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(service))
            if "replace" in argv:
                path = Path(argv[4])
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                job = json.loads(path.read_text())
                template = job["spec"]["template"]["spec"]["template"]
                spec = template["spec"]
                self.assertEqual(
                    spec["serviceAccountName"],
                    service["spec"]["template"]["spec"]["serviceAccountName"],
                )
                container = spec["containers"][0]
                self.assertEqual(
                    container["env"], service["spec"]["template"]["spec"]["containers"][0]["env"]
                )
                self.assertEqual(container["image"], "registry/image:verified-sha")
                self.assertEqual(container["command"], ["python"])
                self.assertEqual(container["args"], ["manage.py", "bootstrap_superadmins"])
                self.assertEqual(
                    template["metadata"]["annotations"],
                    service["spec"]["template"]["metadata"]["annotations"],
                )
            return subprocess.CompletedProcess(argv, 0, stdout="")

        with patch.dict(os.environ, env, clear=True), patch("subprocess.run", side_effect=gcloud):
            bootstrap_cloud_run()
        self.assertEqual([cmd[3] for cmd in commands], ["describe", "replace", "execute"])
        self.assertIn("--wait", commands[-1])
        self.assertTrue(all("never-print-me" not in " ".join(cmd) for cmd in commands))

    def test_missing_or_invalid_origin_and_allowlist_fail_before_cloud_calls(self) -> None:
        for origin in (
            "",
            "http://web.run.app",
            "https://web.run.app/path",
            "https://web.run.app/",
            "https://web.run.app?x=1",
            "https://user@web.run.app",
            "https://*.run.app",
            "https://web.run.app|DB_PASSWORD=bad",
        ):
            with (
                self.subTest(origin=origin),
                patch.dict(
                    os.environ,
                    {
                        "PILAH_WEB_ORIGIN": origin,
                        "PILAH_SUPERADMIN_EMAILS": "admin@example.com",
                    },
                    clear=True,
                ),
                patch("subprocess.run") as run,
            ):
                with self.assertRaises(ValueError):
                    validate_configuration()
                run.assert_not_called()
        for allowlist in ("", "invalid", "admin@example.com,"):
            with (
                self.subTest(allowlist=allowlist),
                patch.dict(
                    os.environ,
                    {
                        "PILAH_WEB_ORIGIN": "https://web.run.app",
                        "PILAH_SUPERADMIN_EMAILS": allowlist,
                    },
                    clear=True,
                ),
            ):
                with self.assertRaises(ValueError):
                    validate_configuration()
