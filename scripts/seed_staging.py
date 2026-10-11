"""Run the staging fixture only on the fixed Fly app, after CI deploy/health checks."""

import os
import re
import shlex
import subprocess


def seed_staging() -> None:
    if not os.environ.get("FLY_API_TOKEN"):
        raise ValueError("FLY_API_TOKEN is required")
    command = [
        "python",
        "/app/manage.py",
        "seed_testing_data",
        "--environment=staging",
        "--confirm=SEED-PILAH-STAGING-DATA",
    ]
    for flag in ("pengurus", "customer", "customer-two", "superadmin", "pending-pengurus", "induk"):
        key = f"PILAH_SEED_{flag.upper().replace('-', '_')}_EMAIL"
        email = os.environ.get(key, "induk.demo@example.com" if flag == "induk" else "")
        if not re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email):
            raise ValueError(f"Set {key} to a valid test-account email")
        command.append(f"--{flag}-email={email}")
    subprocess.run(
        ["flyctl", "ssh", "console", "--app", "pilah-be-staging", "--command", shlex.join(command)],
        check=True,
    )


if __name__ == "__main__":
    seed_staging()
