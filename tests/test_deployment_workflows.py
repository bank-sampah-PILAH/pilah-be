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
        self.assertLess(
            names.index("Verify staging reviewer secrets"), names.index("Deploy verified commit")
        )
        self.assertLess(names.index("Build staging image"), names.index("Trivy scan staging image"))
        self.assertLess(names.index("Trivy scan staging image"), names.index("Push verified image"))
        self.assertLess(names.index("Push verified image"), names.index("Deploy verified commit"))
        trivy = steps[names.index("Trivy scan staging image")]
        self.assertEqual(trivy["with"]["image-ref"], "${{ env.IMAGE_URI }}")
        self.assertEqual(trivy["with"]["exit-code"], "1")
        self.assertEqual(trivy["with"]["severity"], "HIGH,CRITICAL")
        self.assertTrue(trivy["with"]["ignore-unfixed"])
        self.assertNotIn("if", trivy)
        self.assertNotIn("continue-on-error", trivy)
        self.assertEqual(
            deploy["env"]["IMAGE_URI"], "registry.fly.io/pilah-be-staging:${{ github.sha }}"
        )
        self.assertIn('docker push "$IMAGE_URI"', steps[names.index("Push verified image")]["run"])
        self.assertIn(
            'flyctl deploy --app pilah-be-staging --image "$IMAGE_URI"',
            steps[names.index("Deploy verified commit")]["run"],
        )
        self.assertLess(names.index("Deploy verified commit"), names.index("Smoke check /healthz"))
        self.assertLess(
            names.index("Smoke check /healthz"), names.index("Seed verified staging deployment")
        )
        seed = steps[names.index("Seed verified staging deployment")]
        self.assertEqual(seed["run"], "python3 scripts/seed_staging.py")
        self.assertNotIn("continue-on-error", seed)
        self.assertNotIn("if", seed)
        preflight = steps[names.index("Verify staging reviewer secrets")]
        for secret in (
            "PILAH_REVIEW_ACCOUNT_PASSWORD",
            "PILAH_REVIEW_SUPERADMIN_EMAILS",
            "PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS",
        ):
            self.assertIn(secret, preflight["run"])
        self.assertFalse((ROOT / ".github/workflows/seed-staging-data.yml").exists())

    def test_dependency_prs_run_only_pip_audit(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/scheduled-checks.yml").read_text())
        self.assertEqual(workflow[True]["pull_request"]["paths"], ["requirements.txt"])
        self.assertEqual(workflow[True]["schedule"][0]["cron"], "23 2 * * 1")
        self.assertIn("workflow_dispatch", workflow[True])
        self.assertEqual(
            workflow["jobs"]["secret-scan"]["if"], "github.event_name != 'pull_request'"
        )
        self.assertEqual(
            workflow["jobs"]["migration-linter"]["if"], "github.event_name != 'pull_request'"
        )
        self.assertNotIn("if", workflow["jobs"]["pip-audit"])

    def test_dependabot_updates_use_seven_day_cooldowns(self) -> None:
        config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
        self.assertEqual(len(config["updates"]), 2)
        self.assertTrue(
            all(update["cooldown"]["default-days"] == 7 for update in config["updates"])
        )

    def test_production_validates_before_deploy_and_seeds_after_success(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-cloud-run.yml").read_text())
        # PyYAML's YAML 1.1 parser treats the Actions 'on' key as boolean True.
        self.assertEqual(workflow[True]["push"]["branches"], ["main"])
        steps = workflow["jobs"]["deploy"]["steps"]
        names = [step.get("name", "") for step in steps]
        self.assertLess(
            names.index("Validate production origin and auth allowlists"),
            names.index("Authenticate to Google Cloud"),
        )
        self.assertLess(
            names.index("Deploy Cloud Run"),
            names.index("Bootstrap Superadmins and seed production demo accounts"),
        )
        deploy = steps[names.index("Deploy Cloud Run")]["run"]
        self.assertIn("CORS_ALLOW_ALL_ORIGINS=false", deploy)
        self.assertEqual(
            workflow["env"]["PILAH_WEB_ALLOWED_ORIGINS"],
            "${{ vars.PILAH_WEB_ALLOWED_ORIGINS || vars.PILAH_WEB_ORIGIN }}",
        )
        self.assertIn("CORS_ALLOWED_ORIGINS=${PILAH_WEB_ALLOWED_ORIGINS}", deploy)
        self.assertIn("CSRF_TRUSTED_ORIGINS=${PILAH_WEB_ALLOWED_ORIGINS}", deploy)
        self.assertIn("PILAH_ENVIRONMENT=production", deploy)
        self.assertIn("PILAH_ALLOW_FAKE_GOOGLE_TOKEN=false", deploy)
        self.assertIn("PILAH_REVIEW_SUPERADMIN_EMAILS=${PILAH_REVIEW_SUPERADMIN_EMAILS}", deploy)
        self.assertEqual(
            workflow["env"]["PILAH_REVIEW_SUPERADMIN_EMAILS"],
            "${{ vars.PILAH_REVIEW_SUPERADMIN_EMAILS }}",
        )
        bootstrap = steps[names.index("Bootstrap Superadmins and seed production demo accounts")]
        self.assertEqual(bootstrap["run"], "python3 scripts/bootstrap_cloud_run.py")
        self.assertNotIn("continue-on-error", bootstrap)
        self.assertNotIn("if", bootstrap)

    def test_review_seed_secret_and_email_exemptions_are_wired_to_cloud_run(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-cloud-run.yml").read_text())
        deploy = workflow["jobs"]["deploy"]["steps"]
        deploy_command = deploy[
            next(i for i, step in enumerate(deploy) if step.get("name") == "Deploy Cloud Run")
        ]["run"]

        self.assertEqual(
            workflow["env"]["PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS"],
            "${{ vars.PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS }}",
        )
        self.assertIn(
            "PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS=${PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS}",
            deploy_command,
        )
        self.assertIn(
            '--set-secrets "PILAH_REVIEW_ACCOUNT_PASSWORD=PILAH_REVIEW_ACCOUNT_PASSWORD:latest"',
            deploy_command,
        )
        self.assertNotIn("PILAH_REVIEW_ACCOUNT_PASSWORD:", workflow["env"])

        manual_script = (ROOT / "scripts/deploy-cloud-run.sh").read_text()
        self.assertIn("PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS", manual_script)
        self.assertIn(
            '--set-secrets="PILAH_REVIEW_ACCOUNT_PASSWORD=PILAH_REVIEW_ACCOUNT_PASSWORD:latest"',
            manual_script,
        )

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
                            "PILAH_REVIEW_SUPERADMIN_EMAILS": "pilah.superadmin@pilah.com",
                            "PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS": ",".join(
                                (
                                    "pilah.pengelola@pilah.com",
                                    "pilah.pengurus@pilah.com",
                                    "pilah.nasabah@pilah.com",
                                    "pilah.superadmin@pilah.com",
                                )
                            ),
                        },
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("PILAH_SUPERADMIN_EMAILS", result.stderr)
                    self.assertFalse(called.exists())
            result = subprocess.run(
                ["bash", str(ROOT / "scripts/deploy-cloud-run.sh")],
                env={
                    **os.environ,
                    "PATH": f"{directory}:{os.environ['PATH']}",
                    "DB_PASSWORD": "placeholder",
                    "GCS_BUCKET": "placeholder",
                    "DJANGO_SECRET_KEY": "placeholder",
                    "PILAH_WEB_ORIGIN": "https://web.run.app",
                    "PILAH_SUPERADMIN_EMAILS": "admin@example.com",
                    "PILAH_REVIEW_SUPERADMIN_EMAILS": " Admin@Example.com ",
                    "PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS": ",".join(
                        (
                            "pilah.pengelola@pilah.com",
                            "pilah.pengurus@pilah.com",
                            "pilah.nasabah@pilah.com",
                            "pilah.superadmin@pilah.com",
                        )
                    ),
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("PILAH_REVIEW_SUPERADMIN_EMAILS", result.stderr)
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
                "PILAH_REVIEW_SUPERADMIN_EMAILS": "pilah.superadmin@pilah.com",
                "PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS": ",".join(
                    (
                        "pilah.pengelola@pilah.com",
                        "pilah.pengurus@pilah.com",
                        "pilah.nasabah@pilah.com",
                        "pilah.superadmin@pilah.com",
                    )
                ),
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
