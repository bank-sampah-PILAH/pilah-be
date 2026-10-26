import argparse
import importlib.util
import json
import sys
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
            python="python3",
            run_id="test-run",
        )
        with patch.object(
            runner.subprocess,
            "run",
            return_value=CompletedProcess([], 0, stdout='{"cleaned": true}\n', stderr=""),
        ) as run:
            self.assertEqual(runner.fixture(args, "cleanup"), {"cleaned": True})
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["python3", "manage.py", "load_test_data", "cleanup"])
        self.assertIs(run.call_args.kwargs["shell"], False)

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
                k6="k6",
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
                patch.object(runner.subprocess, "run", side_effect=run_k6),
            ):
                self.assertTrue(runner.run_trial(args, "realistic", 10, "realistic-10-test"))

            self.assertEqual(fixture.call_args_list[1].args[2], 2)
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
