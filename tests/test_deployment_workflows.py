import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import skipUnless

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
        self.assertIn("CORS_ALLOWED_ORIGINS=${PILAH_WEB_ORIGIN}", deploy)
        self.assertIn("CSRF_TRUSTED_ORIGINS=${PILAH_WEB_ORIGIN}", deploy)
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


def _nuclei_steps() -> dict[str, dict[str, object]]:
    workflow = yaml.safe_load((ROOT / ".github/workflows/nuclei-scan.yml").read_text())
    return {
        step["name"]: step for step in workflow["jobs"]["nuclei-scan"]["steps"] if "name" in step
    }


def _run_nuclei_step(
    name: str, env: dict[str, str], workdir: Path
) -> subprocess.CompletedProcess[str]:
    script = str(_nuclei_steps()[name]["run"])
    return subprocess.run(
        ["bash", "-eo", "pipefail", "-c", script],
        cwd=workdir,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )


class NucleiScanWorkflowTests(SimpleTestCase):
    def _resolve(
        self, url: str, target_url: str = "", environment: str = "staging"
    ) -> dict[str, str]:
        with tempfile.TemporaryDirectory() as directory:
            github_env = Path(directory) / "github_env"
            github_env.write_text("")
            result = _run_nuclei_step(
                "Resolve target",
                {
                    "ENVIRONMENT": environment,
                    "TARGET_URL_INPUT": target_url,
                    "STAGING_API_URL": url,
                    "PRODUCTION_API_URL": "",
                    "GITHUB_ENV": str(github_env),
                },
                Path(directory),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return dict(line.split("=", 1) for line in github_env.read_text().splitlines())

    def _resolve_fails(self, url: str) -> str:
        with tempfile.TemporaryDirectory() as directory:
            github_env = Path(directory) / "github_env"
            github_env.write_text("")
            result = _run_nuclei_step(
                "Resolve target",
                {
                    "ENVIRONMENT": "staging",
                    "TARGET_URL_INPUT": "",
                    "STAGING_API_URL": url,
                    "PRODUCTION_API_URL": "",
                    "GITHUB_ENV": str(github_env),
                },
                Path(directory),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(github_env.read_text(), "")
            return result.stdout + result.stderr

    def test_scan_targets_are_reduced_to_host_and_port(self) -> None:
        plain = self._resolve("https://api.example")
        self.assertEqual(plain["TARGET"], "https://api.example")
        self.assertEqual(plain["TLS_TARGET"], "api.example:443")
        # A trailing slash, a path and an explicit :443 must not leak into the TLS target.
        for url in (
            "https://api.example/",
            "https://api.example/path?q=1",
            "https://api.example:443",
        ):
            with self.subTest(url=url):
                resolved = self._resolve(url)
                self.assertEqual(resolved["TARGET"], "https://api.example")
                self.assertEqual(resolved["TLS_TARGET"], "api.example:443")
                self.assertEqual(resolved["RESULT_NAME"], "api.example-443")
        custom = self._resolve("https://api.example:8443/")
        self.assertEqual(custom["TARGET"], "https://api.example:8443")
        self.assertEqual(custom["TLS_TARGET"], "api.example:8443")

    def test_scan_target_from_the_caller_overrides_the_variable(self) -> None:
        resolved = self._resolve(
            "", target_url="https://deployed.run.app", environment="production"
        )
        self.assertEqual(resolved["TARGET"], "https://deployed.run.app")

    def test_scan_rejects_unusable_targets(self) -> None:
        for url in (
            "",
            "http://api.example",
            "https://api.example:99999",
            "https://api.example:abc",
            "https://user:pass@api.example",
            "https://[::1]",
        ):
            with self.subTest(url=url):
                self.assertIn("::error::", self._resolve_fails(url))

    def test_production_is_checked_on_the_api_root_not_healthz(self) -> None:
        # Cloud Run's frontend reserves /healthz and answers 404 itself.
        script = str(_nuclei_steps()["Check target is up"]["run"])
        self.assertIn("path=/api/v1/", script)
        self.assertIn("path=/healthz", script)
        self.assertLess(script.index("production"), script.index("path=/api/v1/"))

    @skipUnless(shutil.which("jq"), "jq is not installed")
    def test_gate_names_the_header_that_is_not_accepted(self) -> None:
        def finding(
            template: str, matcher: str | None, matched: str = "https://api.example"
        ) -> dict[str, object]:
            item: dict[str, object] = {
                "template-id": template,
                "host": "api.example",
                "info": {"severity": "info"},
                "matched-at": matched,
            }
            if matcher is not None:
                item["matcher-name"] = matcher
            return item

        def gate(findings: list[dict[str, object]]) -> subprocess.CompletedProcess[str]:
            with tempfile.TemporaryDirectory() as directory:
                results = Path(directory) / "results"
                results.mkdir()
                (results / "scan.jsonl").write_text(
                    "".join(json.dumps(item) + "\n" for item in findings)
                )
                return _run_nuclei_step("Gate", {}, Path(directory))

        accepted = [
            finding("http-missing-security-headers", "strict-transport-security"),
            finding("http-missing-security-headers", "permissions-policy"),
            finding("django-detect", None),
        ]
        self.assertEqual(gate(accepted).returncode, 0)
        # CSP shipped, so a missing CSP must turn the gate red even though HSTS is accepted.
        csp = gate([*accepted, finding("http-missing-security-headers", "content-security-policy")])
        self.assertNotEqual(csp.returncode, 0)
        self.assertIn("content-security-policy", csp.stdout + csp.stderr)
        docs = gate([finding("swagger-api", None, "https://api.example/api/docs/")])
        self.assertNotEqual(docs.returncode, 0)
        self.assertNotEqual(_run_nuclei_step("Gate", {}, Path(tempfile.mkdtemp())).returncode, 0)

    def test_post_deploy_scans_never_continue_on_error(self) -> None:
        ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"][
            "nuclei_post_deploy"
        ]
        self.assertEqual(ci["needs"], "deploy_staging")
        self.assertEqual(ci["with"], {"environment": "staging"})
        production = yaml.safe_load((ROOT / ".github/workflows/deploy-cloud-run.yml").read_text())
        scan = production["jobs"]["nuclei_post_deploy"]
        self.assertEqual(scan["needs"], "deploy")
        self.assertEqual(scan["with"]["environment"], "production")
        self.assertEqual(scan["with"]["target_url"], "${{ needs.deploy.outputs.url }}")
        for job in (ci, scan):
            self.assertNotIn("continue-on-error", job)
