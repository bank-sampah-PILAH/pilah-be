import json
import os
import re
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


OWN_REPOSITORY = "bank-sampah-PILAH/pilah-be"


class NucleiScanWorkflowTests(SimpleTestCase):
    def _resolve_run(
        self,
        url: str,
        target_url: str = "",
        environment: str = "staging",
        repository: str = OWN_REPOSITORY,
    ) -> tuple[subprocess.CompletedProcess[str], str]:
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
                    "GITHUB_REPOSITORY": repository,
                },
                Path(directory),
            )
            return result, github_env.read_text()

    def _resolve(
        self, url: str, target_url: str = "", environment: str = "staging"
    ) -> dict[str, str]:
        result, written = self._resolve_run(url, target_url, environment)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return dict(line.split("=", 1) for line in written.splitlines())

    def _resolve_fails(
        self, url: str, target_url: str = "", repository: str = OWN_REPOSITORY
    ) -> str:
        result, written = self._resolve_run(url, target_url, repository=repository)
        self.assertNotEqual(result.returncode, 0)
        # A rejected target must never reach $GITHUB_ENV, not even partially.
        self.assertEqual(written, "")
        return result.stdout + result.stderr

    def test_scan_targets_are_reduced_to_host_and_port(self) -> None:
        plain = self._resolve("https://api.example")
        self.assertEqual(plain["TARGET"], "https://api.example")
        self.assertEqual(plain["TLS_TARGET"], "api.example:443")
        # A trailing slash and an explicit :443 must not leak into the TLS target.
        for url in ("https://api.example/", "https://api.example:443"):
            with self.subTest(url=url):
                resolved = self._resolve(url)
                self.assertEqual(resolved["TARGET"], "https://api.example")
                self.assertEqual(resolved["TLS_TARGET"], "api.example:443")
                self.assertEqual(resolved["RESULT_NAME"], "api.example-443")
        custom = self._resolve("https://api.example:8443/")
        self.assertEqual(custom["TARGET"], "https://api.example:8443")
        self.assertEqual(custom["TLS_TARGET"], "api.example:8443")

    def test_scan_rejects_urls_that_would_change_the_scan_scope(self) -> None:
        # STAGING_API_URL=https://host/api/v1 used to scan https://host without a word.
        for url in (
            "https://api.example/api/v1",
            "https://api.example/path?q=1",
            "https://api.example?q=1",
            "https://api.example#frag",
        ):
            with self.subTest(url=url):
                self.assertIn("::error::", self._resolve_fails(url))

    def test_scan_rejects_a_target_that_smuggles_environment_variables(self) -> None:
        # The target lands in $GITHUB_ENV one KEY=value per line; a newline in it would
        # let a caller define any variable for the later steps.
        for url in (
            "https://ok.example\nEVIL=injected",
            "https://ok.example\r\nEVIL=injected",
            "https://ok.example EVIL=injected",
        ):
            with self.subTest(url=repr(url)):
                self.assertIn("::error::", self._resolve_fails("", target_url=url))

    def test_scan_only_takes_target_url_from_this_repository(self) -> None:
        # The workflow is reusable from a public repository, so another repository could
        # otherwise point the scan at any host.
        self.assertIn(
            "::error::",
            self._resolve_fails(
                "", target_url="https://deployed.run.app", repository="someone/else"
            ),
        )
        # Variables resolve in the caller's repository too, so the check is not limited to
        # the target_url input.
        self.assertIn(
            "::error::", self._resolve_fails("https://api.example", repository="someone/else")
        )
        # Its own callers (the staging and production deploys) keep working.
        resolved = self._resolve("", target_url="https://deployed.run.app")
        self.assertEqual(resolved["TARGET"], "https://deployed.run.app")

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

    def _up_check(self, environment: str, status: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            fake_curl = Path(directory) / "curl"
            fake_curl.write_text('#!/bin/sh\nprintf "%s" "$FAKE_STATUS"\n')
            fake_curl.chmod(0o700)
            return _run_nuclei_step(
                "Check target is up",
                {
                    "ENVIRONMENT": environment,
                    "TARGET": "https://api.example",
                    "FAKE_STATUS": status,
                    "PATH": f"{directory}:{os.environ['PATH']}",
                },
                Path(directory),
            )

    def test_production_up_check_does_not_mistake_a_proxy_for_the_api(self) -> None:
        # 401 is Django refusing an anonymous request. A 403 can be Cloud Run, IAP or a WAF
        # answering instead, and the scan would then inspect the proxy's error page and
        # stay green without ever reaching the API.
        for status in ("200", "401"):
            with self.subTest(status=status):
                self.assertEqual(self._up_check("production", status).returncode, 0)
        for status in ("403", "404", "500", "000"):
            with self.subTest(status=status):
                self.assertNotEqual(self._up_check("production", status).returncode, 0)
        self.assertEqual(self._up_check("staging", "200").returncode, 0)
        self.assertNotEqual(self._up_check("staging", "401").returncode, 0)

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

    def _template_paths(self) -> list[str]:
        script = str(_nuclei_steps()["Scan"]["run"])
        http = re.findall(r"^\s+(http/[\w/-]+)(?: \\|; do)$", script, re.MULTILINE)
        ssl_block = re.search(r"for t in (expired-ssl.*?); do", script, re.DOTALL)
        assert ssl_block is not None
        ssl = [f"ssl/{name}" for name in ssl_block.group(1).replace("\\", " ").split()]
        return [*http, *ssl]

    def _scan(self, present: list[str]) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "bin").mkdir()
            fake_docker = work / "bin" / "docker"
            fake_docker.write_text("#!/bin/sh\nexit 0\n")
            fake_docker.chmod(0o700)
            for template in present:
                path = work / "nuclei-templates" / f"{template}.yaml"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("id: x\n")
            return _run_nuclei_step(
                "Scan",
                {
                    "NUCLEI_IMAGE": "nuclei:test",
                    "TARGET": "https://api.example",
                    "TLS_TARGET": "api.example:443",
                    "RESULT_NAME": "api.example-443",
                    "PATH": f"{work / 'bin'}:{os.environ['PATH']}",
                },
                work,
            )

    def test_templates_are_downloaded_with_the_update_check_left_on(self) -> None:
        # With -duc, `-update-templates` downloads nothing into an empty directory and
        # still exits 0, so on a fresh runner the scan would start with no templates.
        script = str(_nuclei_steps()["Fetch templates"]["run"])
        self.assertIn("-update-templates", script)
        self.assertNotIn("-duc", script)

    def test_scan_stops_when_a_template_it_needs_is_missing(self) -> None:
        # Nuclei only prints [ERR] for a missing template and scans with the rest, which
        # narrows coverage without a red run; and with none it dies on a confusing error.
        paths = self._template_paths()
        self.assertEqual(len(paths), 24)
        complete = self._scan(paths)
        self.assertEqual(complete.returncode, 0, complete.stdout + complete.stderr)
        for absent in (paths[0], paths[-1]):
            with self.subTest(absent=absent):
                partial = self._scan([p for p in paths if p != absent])
                self.assertNotEqual(partial.returncode, 0)
                self.assertIn(absent, partial.stdout + partial.stderr)
        self.assertNotEqual(self._scan([]).returncode, 0)

    def test_third_party_code_is_pinned_to_an_immutable_reference(self) -> None:
        # A tag (v4, v3.11.0) can be moved by its owner, so the scan would start running
        # different code with no commit here. A commit SHA or an image digest cannot move.
        job = yaml.safe_load((ROOT / ".github/workflows/nuclei-scan.yml").read_text())["jobs"][
            "nuclei-scan"
        ]
        self.assertRegex(job["env"]["NUCLEI_IMAGE"], r"@sha256:[0-9a-f]{64}$")
        used = [step["uses"] for step in job["steps"] if "uses" in step]
        self.assertTrue(used)
        for action in used:
            with self.subTest(action=action):
                self.assertRegex(action, r"@[0-9a-f]{40}$")

    def test_post_deploy_scans_never_continue_on_error(self) -> None:
        ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"][
            "nuclei_post_deploy"
        ]
        self.assertEqual(ci["needs"], "deploy_staging")
        # The scan targets the URL the staging deploy just used, not a repository variable
        # that can drift or be mistyped.
        self.assertEqual(
            ci["with"],
            {"environment": "staging", "target_url": "${{ needs.deploy_staging.outputs.url }}"},
        )
        ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertEqual(ci_workflow.count("pilah-be-staging.fly.dev"), 1)
        deploy = yaml.safe_load(ci_workflow)["jobs"]["deploy_staging"]
        self.assertEqual(deploy["outputs"], {"url": "${{ env.STAGING_URL }}"})
        self.assertEqual(deploy["environment"]["url"], "${{ env.STAGING_URL }}")
        production = yaml.safe_load((ROOT / ".github/workflows/deploy-cloud-run.yml").read_text())
        scan = production["jobs"]["nuclei_post_deploy"]
        self.assertEqual(scan["needs"], "deploy")
        self.assertEqual(scan["with"]["environment"], "production")
        self.assertEqual(scan["with"]["target_url"], "${{ needs.deploy.outputs.url }}")
        for job in (ci, scan):
            self.assertNotIn("continue-on-error", job)
