import os
import subprocess
import tempfile
from pathlib import Path

import yaml
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[1]


class DeploymentWorkflowTests(SimpleTestCase):
    def test_staging_seed_is_owned_by_verified_deploy_and_not_dispatch(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
        deploy = workflow["jobs"]["deploy_staging"]
        self.assertEqual(deploy["needs"], "verify")
        self.assertIn("github.event_name == 'push'", deploy["if"])
        self.assertIn("refs/heads/staging", deploy["if"])
        steps = deploy["steps"]
        names = [step.get("name", "") for step in steps]
        self.assertLess(names.index("Deploy verified commit"), names.index("Smoke check /healthz"))
        self.assertLess(
            names.index("Smoke check /healthz"), names.index("Seed verified staging deployment")
        )
        seed = steps[names.index("Seed verified staging deployment")]
        self.assertEqual(seed["run"], "python3 scripts/seed_staging.py")
        self.assertNotIn("continue-on-error", seed)
        self.assertNotIn("if", seed)
        self.assertFalse((ROOT / ".github/workflows/seed-staging-data.yml").exists())

    def test_production_validates_before_deploy_and_bootstraps_after_success(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-cloud-run.yml").read_text())
        # PyYAML's YAML 1.1 parser treats the Actions 'on' key as boolean True.
        self.assertEqual(workflow[True]["push"]["branches"], ["main"])
        steps = workflow["jobs"]["deploy"]["steps"]
        names = [step.get("name", "") for step in steps]
        self.assertLess(
            names.index("Validate production origin and Superadmin allowlist"),
            names.index("Authenticate to Google Cloud"),
        )
        self.assertLess(
            names.index("Deploy Cloud Run"), names.index("Bootstrap production Superadmins")
        )
        deploy = steps[names.index("Deploy Cloud Run")]["run"]
        self.assertIn("CORS_ALLOW_ALL_ORIGINS=false", deploy)
        self.assertIn("CORS_ALLOWED_ORIGINS=${PILAH_WEB_ORIGIN}", deploy)
        self.assertIn("CSRF_TRUSTED_ORIGINS=${PILAH_WEB_ORIGIN}", deploy)
        self.assertIn("PILAH_ENVIRONMENT=production", deploy)
        self.assertIn("PILAH_ALLOW_FAKE_GOOGLE_TOKEN=false", deploy)
        bootstrap = steps[names.index("Bootstrap production Superadmins")]
        self.assertEqual(bootstrap["run"], "python3 scripts/bootstrap_cloud_run.py")
        self.assertNotIn("continue-on-error", bootstrap)
        self.assertNotIn("if", bootstrap)

    def test_manual_deploy_rejects_invalid_allowlist_before_any_cloud_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fake_gcloud = Path(directory) / "gcloud"
            called = Path(directory) / "called"
            fake_gcloud.write_text(f"#!/bin/sh\ntouch '{called}'\nexit 99\n")
            fake_gcloud.chmod(0o700)
            for email in (".admin@example.com", "admin..name@example.com"):
                with self.subTest(email=email):
                    result = subprocess.run(
                        ["bash", str(ROOT / "scripts/deploy-cloud-run.sh")],
                        env={
                            **os.environ,
                            "PATH": f"{directory}:{os.environ['PATH']}",
                            "DB_PASSWORD": "placeholder",
                            "GCS_BUCKET": "placeholder",
                            "DJANGO_SECRET_KEY": "placeholder",
                            "PILAH_WEB_ORIGIN": "https://web.run.app",
                            "PILAH_SUPERADMIN_EMAILS": email,
                        },
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("PILAH_SUPERADMIN_EMAILS", result.stderr)
                    self.assertFalse(called.exists())

    def test_manual_deploy_rejects_invalid_origin_before_any_cloud_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fake_gcloud = Path(directory) / "gcloud"
            called = Path(directory) / "called"
            fake_gcloud.write_text(f"#!/bin/sh\ntouch '{called}'\nexit 99\n")
            fake_gcloud.chmod(0o700)
            environment = {
                **os.environ,
                "PATH": f"{directory}:{os.environ['PATH']}",
                "DB_PASSWORD": "placeholder",
                "GCS_BUCKET": "placeholder",
                "DJANGO_SECRET_KEY": "placeholder",
                "PILAH_SUPERADMIN_EMAILS": "admin@example.com",
                "PILAH_WEB_ORIGIN": "https://web.run.app/path",
            }
            result = subprocess.run(
                ["bash", str(ROOT / "scripts/deploy-cloud-run.sh")],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("PILAH_WEB_ORIGIN", result.stderr)
            self.assertFalse(called.exists())
