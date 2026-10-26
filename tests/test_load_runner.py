import argparse
import importlib.util
import json
import runpy
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

SPEC = importlib.util.spec_from_file_location("load_runner", Path(__file__).parent / "load/run.py")
assert SPEC is not None
assert SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

MONITOR_SPEC = importlib.util.spec_from_file_location(
    "load_monitor", Path(__file__).parent / "load/monitor.py"
)
assert MONITOR_SPEC is not None
assert MONITOR_SPEC.loader is not None
monitor = importlib.util.module_from_spec(MONITOR_SPEC)
MONITOR_SPEC.loader.exec_module(monitor)


class LoadRunnerTests(SimpleTestCase):
    def test_run_id_rejects_invalid_values_before_remote_commands(self) -> None:
        for run_id in ("../secret", "--help", "Uppercase", "a" * 33):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                runner.validate_run_id(run_id)

    def test_target_allowlist_rejects_production_and_lookalike_hosts(self) -> None:
        self.assertEqual(runner.target_url(runner.STAGING + "/"), runner.STAGING)
        self.assertEqual(
            runner.target_url("http://127.0.0.1:8000/api/v1"), "http://127.0.0.1:8000/api/v1"
        )
        for url in (
            "https://pilah-be-hi6b7cbwta-et.a.run.app/api/v1",
            runner.STAGING + ".evil",
            "https://example.com/api/v1",
            "https://pilah-be-staging.fly.dev@evil.example/api/v1",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                runner.target_url(url)

    def test_private_file_is_owner_only_and_refuses_symlink(self) -> None:
        with TemporaryDirectory() as folder:
            path = Path(folder) / "accounts.json"
            runner.private_write(path, {"accounts": []})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text()), {"accounts": []})
            link = Path(folder) / "symlink.json"
            link.symlink_to(path)
            with self.assertRaises(OSError):
                runner.private_write(link, {"corrupt": True})
            self.assertEqual(json.loads(path.read_text()), {"accounts": []})

    def test_authentication_mismatch_never_persists_token(self) -> None:
        with TemporaryDirectory() as folder:
            path = Path(folder) / "accounts.json"
            manifest = {
                "bank_id": "bank",
                "accounts": [
                    {
                        "id": "expected",
                        "role": "nasabah",
                        "email": "test@load.invalid",
                        "password": "secret",
                    },
                ],
            }
            runner.private_write(path, manifest)
            with patch.object(runner.urllib.request, "urlopen") as request:
                request.return_value.__enter__.return_value.read.return_value = json.dumps(
                    {
                        "user": {"id": "someone-else"},
                        "access_token": "never-persist",
                    }
                ).encode()
                with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                    runner.authenticate(path, "http://localhost:8000/api/v1", interval=0)
            self.assertEqual(json.loads(path.read_text()), manifest)

    def test_authentication_persists_matching_sessions_and_observes_login_limit(self) -> None:
        with TemporaryDirectory() as folder:
            path = Path(folder) / "accounts.json"
            manifest = {
                "bank_id": "bank",
                "accounts": [
                    {
                        "id": "first",
                        "role": "pengelola",
                        "email": "first@load.invalid",
                        "password": "secret",
                    },
                    {
                        "id": "cached",
                        "role": "nasabah",
                        "email": "cached@load.invalid",
                        "password": "secret",
                        "access_token": "already-authenticated",
                    },
                    {
                        "id": "third",
                        "role": "nasabah",
                        "email": "third@load.invalid",
                        "password": "secret",
                    },
                ],
            }
            runner.private_write(path, manifest)
            sessions = [
                {
                    "user": {
                        "id": account_id,
                        "role": role,
                        "bank_sampah_id": "bank",
                    },
                    "access_token": f"token-{account_id}",
                }
                for account_id, role in (("first", "pengelola"), ("third", "nasabah"))
            ]
            responses = []
            for session in sessions:
                response = MagicMock()
                response.__enter__.return_value = response
                response.read.return_value = json.dumps(session).encode()
                responses.append(response)
            with (
                patch.object(runner.urllib.request, "urlopen", side_effect=responses) as request,
                patch.object(runner.time, "sleep") as sleep,
                redirect_stdout(StringIO()),
            ):
                runner.authenticate(path, "http://localhost:8000/api/v1", interval=0)

            saved = json.loads(path.read_text())
            self.assertEqual(saved["accounts"][0]["access_token"], "token-first")
            self.assertEqual(saved["accounts"][1]["access_token"], "already-authenticated")
            self.assertEqual(saved["accounts"][2]["access_token"], "token-third")
            self.assertEqual(request.call_count, 2)
            sleep.assert_called_once_with(0)

    def test_authentication_reports_login_rate_limit(self) -> None:
        with TemporaryDirectory() as folder:
            path = Path(folder) / "accounts.json"
            runner.private_write(
                path,
                {
                    "accounts": [
                        {
                            "id": "first",
                            "role": "pengelola",
                            "email": "first@load.invalid",
                            "password": "secret",
                        }
                    ]
                },
            )
            error = runner.urllib.error.HTTPError(
                "http://localhost/auth/login", 429, "Too Many Requests", None, None
            )
            with patch.object(runner.urllib.request, "urlopen", side_effect=error):
                with self.assertRaisesRegex(RuntimeError, "login HTTP 429"):
                    runner.authenticate(path, "http://localhost:8000/api/v1")

    def test_authentication_rejects_unapproved_host_before_request(self) -> None:
        with TemporaryDirectory() as folder:
            path = Path(folder) / "accounts.json"
            runner.private_write(path, {"accounts": []})
            with patch.object(runner.urllib.request, "urlopen") as request:
                with self.assertRaisesRegex(ValueError, "Only the exact Fly staging API"):
                    runner.authenticate(path, "https://example.com/api/v1")
            request.assert_not_called()

    def test_local_fixture_uses_safe_argument_vector(self) -> None:
        args = argparse.Namespace(
            base_url="http://localhost:8000/api/v1",
            run_id="test-run",
        )
        with patch.object(
            runner.subprocess,
            "run",
            return_value=CompletedProcess([], 0, stdout='{"cleaned": true}\n', stderr=""),
        ) as run:
            self.assertEqual(runner.fixture(args, "cleanup"), {"cleaned": True})
        command = run.call_args.args[0]
        self.assertEqual(
            command[:4], [runner.sys.executable, "manage.py", "load_test_data", "cleanup"]
        )
        self.assertIs(run.call_args.kwargs["shell"], False)
        with patch.object(runner.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "Unsupported fixture action"):
                runner.fixture(args, "--help")
        run.assert_not_called()

    def test_staging_fixture_checks_health_and_runs_on_fly(self) -> None:
        args = argparse.Namespace(run_id="test-run", base_url=runner.STAGING)
        health = MagicMock(status=200)
        health.__enter__.return_value = health
        with (
            patch.object(
                runner.urllib.request,
                "urlopen",
                return_value=health,
            ),
            patch.object(
                runner.subprocess,
                "run",
                return_value=CompletedProcess([], 0, stdout='{"run_id":"test-run"}\n', stderr=""),
            ) as run,
        ):
            self.assertEqual(runner.fixture(args, "audit", expected=3), {"run_id": "test-run"})
        command = run.call_args.args[0]
        self.assertEqual(command[:5], ["flyctl", "ssh", "console", "--app", runner.APP])
        self.assertIn("--expected-writes 3", command[-1])
        self.assertIs(run.call_args.kwargs["shell"], False)

    def test_staging_fixture_stops_before_access_when_health_check_fails(self) -> None:
        args = argparse.Namespace(run_id="test-run", base_url=runner.STAGING)
        health = MagicMock(status=503)
        health.__enter__.return_value = health
        with (
            patch.object(
                runner.urllib.request,
                "urlopen",
                return_value=health,
            ),
            patch.object(runner.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "health check failed"):
                runner.fixture(args, "cleanup")
        run.assert_not_called()

    def test_fixture_surfaces_command_failure_without_leaking_environment(self) -> None:
        args = argparse.Namespace(run_id="test-run", base_url="http://localhost:8000/api/v1")
        with patch.object(
            runner.subprocess,
            "run",
            return_value=CompletedProcess([], 1, stdout="", stderr=""),
        ):
            with self.assertRaisesRegex(RuntimeError, "no diagnostic"):
                runner.fixture(args, "audit")

    def test_trial_plans_match_supported_levels_and_modes(self) -> None:
        args = argparse.Namespace(action="matrix", users=None, probe_role=None)
        trials = runner._build_trials(args)
        self.assertEqual([trial[1] for trial in trials], [10, 10, 20, 20, 30, 30])
        self.assertEqual(trials[0][2], "realistic-10-1")

        args.action = "burst"
        trials = runner._build_trials(args)
        self.assertEqual(len(trials), 18)
        self.assertEqual(trials[0][3], "separate")
        self.assertEqual(trials[3][3], "shared")

        args.action = "probe"
        args.users = 20
        args.probe_role = "nasabah"
        self.assertEqual(
            runner._build_trials(args),
            [("realistic", 20, "probe-20-nasabah", "separate", "pengelola")],
        )

    def test_local_trial_audits_writes_and_saves_result(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            args = argparse.Namespace(
                output=root / "results",
                base_url="http://127.0.0.1:8000/api/v1",
                accounts=root / "accounts.json",
                probe_role=None,
                probe_writes=0,
            )

            def run_k6(command: list[str], **kwargs: Any) -> CompletedProcess[str]:
                summary_path = Path(kwargs["env"]["SUMMARY"])
                summary_path.write_text(
                    json.dumps({"metrics": {"new_writes": {"values": {"count": 2}}}})
                )
                return CompletedProcess(command, 0, stdout="", stderr="")

            with (
                patch.object(
                    runner, "fixture", side_effect=[{"reset": True}, {"integrity_errors": 0}]
                ) as fixture,
                patch.object(runner, "snapshot"),
                patch.object(runner.subprocess, "run", side_effect=run_k6) as run,
            ):
                self.assertTrue(runner.run_trial(args, "realistic", 10, "realistic-10-test"))

            self.assertEqual(fixture.call_args_list[1].args[2], 2)
            self.assertEqual(run.call_args.args[0][0], "k6")
            self.assertIs(run.call_args.kwargs["shell"], False)
            result = json.loads((args.output / "realistic-10-test" / "result.json").read_text())
            self.assertEqual(result["expected_new_writes"], 2)
            self.assertTrue(result["passed"])

    def test_monitor_samples_guest_and_database_metrics(self) -> None:
        django = ModuleType("django")
        django.setup = MagicMock()  # type: ignore[attr-defined]
        conf = ModuleType("django.conf")
        conf.settings = SimpleNamespace(  # type: ignore[attr-defined]
            PILAH_ENVIRONMENT="staging", DATABASES={"default": {"HOST": "branch.neon.tech"}}
        )
        db = ModuleType("django.db")
        connection = MagicMock()
        db.connection = connection  # type: ignore[attr-defined]
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (4, 1, 0)
        reads = {"stat": 0}

        def read_proc(path: Path) -> str:
            if str(path) == "/proc/stat":
                reads["stat"] += 1
                if reads["stat"] == 1:
                    return "cpu 10 0 5 20 0 3 1 1\n"
                return "cpu 15 0 8 30 0 4 2 1\n"
            return "MemTotal: 1000 kB\nMemAvailable: 400 kB\n"

        output = StringIO()
        with (
            patch.dict(sys.modules, {"django": django, "django.conf": conf, "django.db": db}),
            patch.object(monitor.Path, "read_text", autospec=True, side_effect=read_proc),
            patch.object(monitor.time, "monotonic", side_effect=(0, 0, 0, 15, 15, 420)),
            patch.object(monitor.time, "sleep") as sleep,
            patch.object(monitor.time, "strftime", return_value="2026-10-26T00:00:00Z"),
            patch("sys.stdout", output),
        ):
            monitor.main()

        samples = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0]["memory_used_kib"], 600)
        self.assertEqual(samples[0]["db_connections"], 4)
        self.assertIn("cpu_percent_of_one_core", samples[1])
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertEqual(sleep.call_count, 2)

    def test_monitor_script_rejects_non_staging_configuration(self) -> None:
        django = ModuleType("django")
        django.setup = MagicMock()  # type: ignore[attr-defined]
        conf = ModuleType("django.conf")
        conf.settings = SimpleNamespace(  # type: ignore[attr-defined]
            PILAH_ENVIRONMENT="production", DATABASES={"default": {"HOST": "db.example.com"}}
        )
        db = ModuleType("django.db")
        db.connection = MagicMock()  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"django": django, "django.conf": conf, "django.db": db}):
            with self.assertRaisesRegex(SystemExit, "Only isolated Fly staging"):
                runpy.run_path(
                    str(Path(__file__).parent / "load" / "monitor.py"), run_name="__main__"
                )

    def test_burst_repeats_latency_failures_but_stops_on_script_faults(self) -> None:
        for exit_code, expected_calls in ((99, 6), (108, 1)):
            with self.subTest(exit_code=exit_code), TemporaryDirectory() as folder:
                root = Path(folder)
                accounts = root / "accounts.json"
                accounts.write_text(json.dumps({"run_id": "test-run"}))
                seen: list[tuple[int, str]] = []

                def trial(
                    arguments: Any,
                    mode: str,
                    users: int,
                    label: str,
                    *_rest: Any,
                    recorded: list[tuple[int, str]] = seen,
                    code: int = exit_code,
                ) -> bool:
                    recorded.append((users, label))
                    result_dir = arguments.output / label
                    result_dir.mkdir(parents=True)
                    (result_dir / "result.json").write_text(json.dumps({"k6_exit_code": code}))
                    return False

                argv = [
                    "run.py",
                    "burst",
                    "--accounts",
                    str(accounts),
                    "--run-id",
                    "test-run",
                    "--output",
                    str(root / "results"),
                ]
                with (
                    patch.object(sys, "argv", argv),
                    patch.object(runner, "run_trial", side_effect=trial),
                ):
                    with self.assertRaises(SystemExit):
                        runner.main()
                self.assertEqual(len(seen), expected_calls)
                self.assertTrue(all(users == 10 for users, _label in seen))

    def test_cleanup_cli_uses_guarded_fixture_without_starting_load(self) -> None:
        with TemporaryDirectory() as folder:
            path = Path(folder) / "accounts.json"
            path.write_text(json.dumps({"run_id": "test-run"}))
            argv = [
                "run.py",
                "cleanup",
                "--accounts",
                str(path),
                "--run-id",
                "test-run",
                "--output",
                folder,
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(runner, "fixture", return_value={"cleaned": True}) as fixture,
                patch.object(runner, "run_trial") as load,
                patch("sys.stdout", new_callable=StringIO),
            ):
                runner.main()
            self.assertEqual(fixture.call_args.args[1], "cleanup")
            load.assert_not_called()

    def test_staging_trial_stops_monitor_and_counts_actual_client_writes(self) -> None:
        def make_fixture(recorded: list[tuple[str, tuple[Any, ...]]]) -> Any:
            def fixture(_args: Any, action: str, *values: Any) -> dict[str, Any]:
                recorded.append((action, values))
                return {"integrity_errors": 0}

            return fixture

        for wait_times in ((None,), (runner.subprocess.TimeoutExpired("flyctl", 10), None)):
            with self.subTest(wait_times=wait_times), TemporaryDirectory() as folder:
                root = Path(folder)
                accounts = root / "accounts.json"
                accounts.write_text("{}")
                args = argparse.Namespace(
                    output=root / "results",
                    base_url=runner.STAGING,
                    accounts=accounts,
                    probe_role="pengelola",
                    probe_writes=1,
                )
                process = MagicMock()
                process.wait.side_effect = list(wait_times)
                fixtures: list[tuple[str, tuple[Any, ...]]] = []

                def k6(command: list[str], **kwargs: Any) -> CompletedProcess[str]:
                    Path(kwargs["env"]["SUMMARY"]).write_text(
                        json.dumps({"metrics": {"new_writes": {"values": {"count": 2}}}})
                    )
                    return CompletedProcess(command, 0, stdout="", stderr="")

                with (
                    patch.object(runner, "fixture", side_effect=make_fixture(fixtures)),
                    patch.object(runner, "snapshot"),
                    patch.object(runner.subprocess, "Popen", return_value=process) as popen,
                    patch.object(runner.subprocess, "run", side_effect=k6),
                ):
                    self.assertTrue(
                        runner.run_trial(
                            args, "realistic", 10, "probe-test", smoke_role="pengelola"
                        )
                    )
                process.send_signal.assert_called_once_with(runner.signal.SIGINT)
                if wait_times[0] is not None:
                    process.terminate.assert_called_once()
                    self.assertEqual(process.wait.call_count, 2)
                else:
                    process.terminate.assert_not_called()
                    process.wait.assert_called_once_with(timeout=10)
                self.assertEqual(fixtures[1], ("audit", (3,)))
                result = json.loads((args.output / "probe-test" / "result.json").read_text())
                self.assertEqual(result["expected_new_writes"], 3)
                self.assertTrue(result["passed"])
                self.assertIs(popen.call_args.kwargs["shell"], False)

    def test_snapshot_records_machine_details_and_unavailable_reason(self) -> None:
        with TemporaryDirectory() as folder:
            output = Path(folder) / "snapshot.json"
            machine = {
                "id": "machine-1",
                "state": "started",
                "region": "sin",
                "config": {"guest": {"cpus": 1}, "image": "image@sha256:abc"},
                "events": [],
            }

            def command(argv: list[str], **kwargs: Any) -> str | bytes:
                if argv[:2] == ["git", "rev-parse"]:
                    return "revision\n"
                if argv[:2] == ["git", "diff"]:
                    return b""
                return json.dumps([machine])

            with (
                patch.object(runner.subprocess, "check_output", side_effect=command),
                patch.object(runner.platform, "platform", return_value="test-platform"),
                patch.object(runner.os, "cpu_count", return_value=4),
                patch.object(runner.os, "getloadavg", return_value=(1.0, 0.5, 0.1)),
            ):
                runner.snapshot(output)
            saved = json.loads(output.read_text())
            self.assertEqual(saved["source_revision"], "revision")
            self.assertEqual(saved["machines"][0]["id"], "machine-1")
            self.assertTrue(saved["source_sha256"])

            with patch.object(runner.subprocess, "check_output", side_effect=FileNotFoundError):
                runner.snapshot(output)
            self.assertEqual(
                json.loads(output.read_text())["snapshot_unavailable"], "FileNotFoundError"
            )

    def test_validation_errors_stop_invalid_cli_arguments_before_any_work(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            accounts = root / "accounts.json"
            accounts.write_text(json.dumps({"run_id": "test-run"}))
            common = ["--accounts", str(accounts), "--output", str(root / "results")]
            invalid = (
                ["matrix", *common, "--run-id", "bad!"],
                ["matrix", *common, "--run-id", "different"],
                ["probe", *common, "--run-id", "test-run"],
                ["matrix", *common, "--run-id", "test-run", "--probe-writes", "-1"],
                ["matrix", *common, "--run-id", "test-run", "--probe-role", "pengelola"],
            )
            for arguments in invalid:
                with (
                    self.subTest(arguments=arguments),
                    patch.object(sys, "argv", ["run.py", *arguments]),
                    redirect_stderr(StringIO()),
                    self.assertRaises(SystemExit),
                ):
                    runner.main()

    def test_auth_and_snapshot_actions_dispatch_without_load(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            accounts = root / "accounts.json"
            accounts.write_text(json.dumps({"run_id": "test-run"}))
            common = ["--accounts", str(accounts), "--run-id", "test-run", "--output", str(root)]
            for action in ("auth", "snapshot"):
                with (
                    self.subTest(action=action),
                    patch.object(
                        sys,
                        "argv",
                        ["run.py", action, *common, "--base-url", "http://localhost:8000/api/v1"],
                    ),
                    patch.object(runner, "authenticate") as authenticate,
                    patch.object(runner, "snapshot") as snapshot,
                    patch.object(runner, "run_trial") as run_trial,
                ):
                    runner.main()
                    if action == "auth":
                        authenticate.assert_called_once()
                        snapshot.assert_not_called()
                    else:
                        snapshot.assert_called_once_with(root / "deployment.json")
                        authenticate.assert_not_called()
                    run_trial.assert_not_called()

    def test_smoke_plan_covers_each_role(self) -> None:
        args = argparse.Namespace(action="smoke")
        self.assertEqual(
            [trial[2] for trial in runner._build_trials(args)],
            ["baseline-pengelola", "baseline-nasabah"],
        )

    def test_burst_latency_failure_stops_after_finishing_same_level(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            args = argparse.Namespace(output=root)
            trials = [
                ("burst", 10, f"burst-{index}", "separate", "pengelola") for index in range(6)
            ]

            def fail_trial(_args: Any, _mode: str, _users: int, label: str, *_rest: Any) -> bool:
                (root / label).mkdir()
                (root / label / "result.json").write_text(json.dumps({"k6_exit_code": 99}))
                return False

            with patch.object(runner, "run_trial", side_effect=fail_trial):
                with self.assertRaisesRegex(SystemExit, "Burst latency failed at 10 users"):
                    runner._run_trials(args, trials)

    def test_script_entry_point_dispatches_local_cleanup(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            accounts = root / "accounts.json"
            accounts.write_text(json.dumps({"run_id": "test-run"}))
            argv = [
                "run.py",
                "cleanup",
                "--accounts",
                str(accounts),
                "--run-id",
                "test-run",
                "--output",
                folder,
                "--base-url",
                "http://localhost:8000/api/v1",
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    runner.subprocess,
                    "run",
                    return_value=CompletedProcess([], 0, stdout='{"cleaned":true}\n', stderr=""),
                ),
                redirect_stdout(StringIO()),
            ):
                runpy.run_path(str(Path(__file__).parent / "load" / "run.py"), run_name="__main__")
