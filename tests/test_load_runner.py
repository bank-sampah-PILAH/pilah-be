import importlib.util
import json
import sys
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from django.test import SimpleTestCase

SPEC = importlib.util.spec_from_file_location("load_runner", Path(__file__).parent / "load/run.py")
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class LoadRunnerTests(SimpleTestCase):
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
