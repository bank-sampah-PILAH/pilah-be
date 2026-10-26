"""Run PIL-393 locally or on Fly staging; all credentials stay in private files."""

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

STAGING = "https://pilah-be-staging.fly.dev/api/v1"
APP = "pilah-be-staging"
CONFIRMATION = "PIL-393-STAGING-ONLY"


def target_url(value: str) -> str:
    value = value.rstrip("/")
    if value != STAGING and not re.fullmatch(
        r"http://(?:127\.0\.0\.1|localhost):\d+/api/v1",  # NOSONAR: loopback-only local development.
        value,
    ):
        raise ValueError("Only the exact Fly staging API or loopback API is allowed")
    return value


def validate_run_id(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", value):
        raise ValueError("run-id must be 1–32 lowercase letters, digits or hyphens")
    return value


def private_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = (
        os.open(  # NOSONAR: only operator-selected local output paths reach this private writer.
            path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
        )
    )
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(data, output, indent=2)


def authenticate(path: Path, base: str, interval: float = 16) -> None:
    base = target_url(base)
    manifest = json.loads(path.read_text())  # NOSONAR: operator-selected local credential manifest.
    for index, account in enumerate(manifest["accounts"]):
        if account.get("access_token"):
            continue
        if index:
            time.sleep(interval)
        payload = json.dumps({"email": account["email"], "password": account["password"]}).encode()
        request = urllib.request.Request(
            base + "/auth/login", data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                session = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(
                f"Account {index}: login HTTP {error.code}; do not bypass throttling"
            ) from None
        user = session["user"]
        if (
            user["id"] != account["id"]
            or user["role"] != account["role"]
            or user["bank_sampah_id"] != manifest["bank_id"]
        ):
            raise RuntimeError(f"Account {index}: login identity mismatch")
        account["access_token"] = session["access_token"]
        private_write(path, manifest)
        print(f"Authenticated account {index + 1}/{len(manifest['accounts'])}", flush=True)


def fixture(args: argparse.Namespace, action: str, expected: int | None = None) -> dict[str, Any]:
    validate_run_id(args.run_id)
    base_url = target_url(args.base_url)
    if base_url == STAGING:
        with urllib.request.urlopen(
            STAGING.removesuffix("/api/v1") + "/healthz", timeout=45
        ) as health:
            if health.status != 200:
                raise RuntimeError("Staging health check failed before fixture access")
    command = [
        "python",
        "manage.py",
        "load_test_data",
        action,
        "--run-id",
        args.run_id,
        "--confirm",
        CONFIRMATION,
    ]
    if expected is not None:
        command += ["--expected-writes", str(expected)]
    if base_url == STAGING:
        source = (
            "import os,sys; sys.path.insert(0, '/app'); "
            "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); "
            "import django; django.setup()\n"
            + Path(__file__)
            .resolve()
            .parents[2]
            .joinpath("api/management/commands/load_test_data.py")
            .read_text()
            + "\nCommand().run_from_argv(sys.argv)\n"
        )
        command = [
            "flyctl",
            "ssh",
            "console",
            "--app",
            APP,
            "-C",
            shlex.join(["python", "-c", source, *command[2:]]),
        ]
    else:
        command[0] = args.python
    result = subprocess.run(  # NOSONAR: argv is shell-free; Fly's -C string uses shlex.join.
        command, check=False, capture_output=True, text=True, timeout=180, shell=False
    )
    if result.returncode:
        message = (result.stderr or result.stdout).strip().splitlines()
        raise RuntimeError(
            f"Fixture {action} failed: {message[-1] if message else 'no diagnostic'}"
        )
    # Fly's connection banner can precede the JSON result; never copy environment or secrets.
    data: dict[str, Any] = json.loads(
        next(line for line in reversed(result.stdout.splitlines()) if line.startswith("{"))
    )
    return data


def snapshot(output: Path) -> None:
    data: dict[str, Any] = {
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runner": platform.platform(),
        "cpu_count": os.cpu_count(),
        "runner_load_average": os.getloadavg(),
    }
    try:
        data["source_revision"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
        data["source_sha256"] = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                Path("api/management/commands/load_test_data.py"),
                *Path("tests/load").glob("*.py"),
                Path("tests/load/journeys.js"),
            ]
        }
        data["working_diff_sha256"] = hashlib.sha256(
            subprocess.check_output(["git", "diff", "HEAD"])
        ).hexdigest()
        machines = json.loads(
            subprocess.check_output(
                ["flyctl", "machine", "list", "--app", APP, "--json"], text=True, timeout=60
            )
        )
        data["machines"] = [
            {
                "id": m["id"],
                "state": m["state"],
                "region": m["region"],
                "guest": m["config"].get("guest"),
                "image": m["config"].get("image"),
                "events": m.get("events", []),
            }
            for m in machines
        ]
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        data["snapshot_unavailable"] = type(error).__name__
    private_write(output, data)


def run_trial(
    args: argparse.Namespace,
    mode: str,
    users: int,
    label: str,
    contention: str = "separate",
    smoke_role: str = "pengelola",
) -> bool:
    args.output.mkdir(  # NOSONAR: operator-selected local output.
        parents=True, exist_ok=True, mode=0o700
    )
    folder = args.output / label
    folder.mkdir(mode=0o700)
    fixture(args, "reset")
    snapshot(folder / "before.json")
    summary = folder / "summary.json"
    environment = os.environ | {
        "BASE_URL": args.base_url,
        "ACCOUNTS": str(args.accounts.resolve()),
        "USERS": str(users),
        "MODE": mode,
        "TRIAL_ID": label,
        "SUMMARY": str(summary.resolve()),
        "CONTENTION": contention,
        "SMOKE_ROLE": smoke_role,
        "PROBE_ROLE": args.probe_role or "",
    }
    telemetry_file = (folder / "telemetry.jsonl").open("w")
    monitor = None
    if args.base_url == STAGING:
        monitor_path = Path(__file__).with_name("monitor.py")
        monitor_source = monitor_path.read_text()  # NOSONAR: tracked source, quoted for Fly.
        monitor = subprocess.Popen(
            [
                "flyctl",
                "ssh",
                "console",
                "--app",
                APP,
                "-C",
                shlex.join(["python", "-u", "-c", monitor_source]),
            ],
            stdout=telemetry_file,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    result = subprocess.run(  # NOSONAR: selected k6 executable is one argv item; shell is disabled.
        [
            args.k6,
            "run",
            "--quiet",
            "--out",
            f"json={folder.resolve() / 'samples.json'}",
            str(Path(__file__).with_name("journeys.js")),
        ],
        env=environment,
        check=False,
        shell=False,
    )
    if monitor:
        monitor.send_signal(signal.SIGINT)
        try:
            monitor.wait(timeout=10)
        except subprocess.TimeoutExpired:
            monitor.terminate()
            monitor.wait(timeout=10)
    telemetry_file.close()
    metrics = json.loads(summary.read_text())["metrics"] if summary.exists() else {}
    expected = (
        int(metrics.get("new_writes", {}).get("values", {}).get("count", 0)) + args.probe_writes
    )
    audit = fixture(args, "audit", expected)
    private_write(folder / "audit.json", audit)
    snapshot(folder / "after.json")
    passed = result.returncode == 0 and audit["integrity_errors"] == 0
    private_write(
        folder / "result.json",
        {
            "trial": label,
            "mode": mode,
            "users": users,
            "contention": contention,
            "probe_role": args.probe_role,
            "k6_exit_code": result.returncode,
            "passed": passed,
            "expected_new_writes": expected,
            "telemetry": "telemetry.jsonl contains guest CPU/memory and sampled DB connections/lock waits; empty data means unavailable",
        },
    )
    return passed


def _parse_args() -> tuple[argparse.ArgumentParser, argparse.Namespace]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("auth", "smoke", "matrix", "burst", "probe", "snapshot", "audit", "cleanup"),
    )
    parser.add_argument("--base-url", type=target_url, default=STAGING)
    parser.add_argument("--accounts", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--k6", default="k6")
    parser.add_argument("--python", default="python")
    parser.add_argument("--users", type=int, choices=(10, 20, 30))
    parser.add_argument("--probe-role", choices=("pengelola", "nasabah"))
    parser.add_argument("--probe-writes", type=int, default=0)
    return parser, parser.parse_args()


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    try:
        validate_run_id(args.run_id)
    except ValueError as error:
        parser.error(str(error))
    manifest = json.loads(args.accounts.read_text())
    if args.run_id != manifest["run_id"]:
        parser.error("run-id must match the account manifest")
    if args.action == "probe" and (args.probe_role is None or args.users is None):
        parser.error("probe requires --users and --probe-role")
    if args.probe_writes < 0 or (args.probe_writes and args.action != "probe"):
        parser.error("Only probe runs may declare non-negative actual-client writes")
    if args.probe_role and args.action != "probe":
        parser.error("Only probe runs may reserve one virtual-user slot")


def _run_single_action(args: argparse.Namespace) -> bool:
    if args.action in ("audit", "cleanup"):
        print(json.dumps(fixture(args, args.action)))
    elif args.action == "auth":
        authenticate(args.accounts, args.base_url)
    elif args.action == "snapshot":
        snapshot(args.output / "deployment.json")
    else:
        return False
    return True


def _build_trials(args: argparse.Namespace) -> list[tuple[str, int, str, str, str]]:
    if args.action == "smoke":
        trials = [
            ("smoke", 1, f"baseline-{role}", "separate", role) for role in ("pengelola", "nasabah")
        ]
    elif args.action == "probe":
        assert args.users is not None and args.probe_role is not None
        trials = [
            (
                "realistic",
                args.users,
                f"probe-{args.users}-{args.probe_role}",
                "separate",
                "pengelola",
            )
        ]
    elif args.action == "matrix":
        levels = [args.users] if args.users is not None else [10, 20, 30]
        trials = [
            ("realistic", users, f"realistic-{users}-{repeat}", "separate", "pengelola")
            for users in levels
            for repeat in (1, 2)
        ]
    else:
        levels = [args.users] if args.users is not None else [10, 20, 30]
        trials = [
            ("burst", users, f"burst-{users}-{contention}-{repeat}", contention, "pengelola")
            for users in levels
            for contention in ("separate", "shared")
            for repeat in (1, 2, 3)
        ]

    return trials


def _run_trials(args: argparse.Namespace, trials: list[tuple[str, int, str, str, str]]) -> None:
    failed_level = None
    for mode, users, label, contention, role in trials:
        if failed_level is not None and users != failed_level:
            raise SystemExit(f"Stopped before escalating beyond {failed_level} users")
        if not run_trial(args, mode, users, label, contention, role):
            result = json.loads((args.output / label / "result.json").read_text())
            if mode == "burst" and result["k6_exit_code"] == 99:
                # Finish both cases/repeats at this level; never escalate a failed level.
                failed_level = users
            else:
                raise SystemExit(f"Stopped after failing {label}; investigate before escalation")
    if failed_level is not None:
        raise SystemExit(
            f"Burst latency failed at {failed_level} users; integrity results retained"
        )


def main() -> None:
    parser, args = _parse_args()
    _validate_args(parser, args)
    if _run_single_action(args):
        return
    _run_trials(args, _build_trials(args))


if __name__ == "__main__":
    main()
