"""Bootstrap via a Cloud Run Job using the deployed service's runtime configuration.

The service JSON contains credentials: capture it, never print it, and keep the
short-lived Job manifest in an owner-only temporary file (including secret refs).
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from typing import Any


def validate_configuration() -> None:
    origin = os.environ.get("PILAH_WEB_ORIGIN", "")
    if not re.fullmatch(
        r"https://[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+(?::[0-9]{1,5})?",
        origin,
    ):
        raise ValueError("PILAH_WEB_ORIGIN must be an exact HTTPS origin without a path")
    if ":" in origin.removeprefix("https://"):
        port = int(origin.rsplit(":", 1)[1])
        if not 1 <= port <= 65535:
            raise ValueError("PILAH_WEB_ORIGIN port is invalid")
    emails = [email.strip() for email in os.environ.get("PILAH_SUPERADMIN_EMAILS", "").split(",")]
    # Conservative ASCII dot-atoms/DNS labels accepted by Django validate_email,
    # bounded by User.email's storage length; this preflight has no Django dependency.
    if not all(
        len(email) <= 254
        and re.fullmatch(
            r"[A-Za-z0-9_%+-]+(?:\.[A-Za-z0-9_%+-]+)*@"
            r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
            r"[A-Za-z]{2,63}",
            email,
        )
        for email in emails
    ):
        raise ValueError("PILAH_SUPERADMIN_EMAILS must contain valid email addresses")


def bootstrap_cloud_run() -> None:
    validate_configuration()
    service_name = os.environ["SERVICE_NAME"]
    flags = ["--project", os.environ["PROJECT_ID"], "--region", os.environ["REGION"]]
    result = subprocess.run(
        ["gcloud", "run", "services", "describe", service_name, *flags, "--format=json"],
        check=True,
        capture_output=True,
        text=True,
    )
    service: dict[str, Any] = json.loads(result.stdout)
    template = service["spec"]["template"]
    runtime = template["spec"]
    source = runtime["containers"][0]
    env = {item["name"]: item.get("value") for item in source.get("env", [])}
    if env.get("PILAH_ENVIRONMENT") != "production":
        raise ValueError("Bootstrap requires the deployed production runtime")
    annotations = {
        key: value
        for key, value in template.get("metadata", {}).get("annotations", {}).items()
        if key
        in (
            "run.googleapis.com/cloudsql-instances",
            "run.googleapis.com/vpc-access-connector",
            "run.googleapis.com/vpc-access-egress",
            "run.googleapis.com/network-interfaces",
            "run.googleapis.com/secrets",
        )
    }
    container = {
        key: source[key] for key in ("image", "env", "resources", "volumeMounts") if key in source
    }
    container.update(command=["python"], args=["manage.py", "bootstrap_superadmins"])
    spec = {key: runtime[key] for key in ("serviceAccountName", "volumes") if key in runtime}
    spec.update(containers=[container], maxRetries=0, timeoutSeconds="300")
    job_name = f"{service_name}-bootstrap-superadmins"
    job = {
        "apiVersion": "run.googleapis.com/v1",
        "kind": "Job",
        "metadata": {"name": job_name},
        "spec": {
            "template": {
                "metadata": {"annotations": annotations},
                "spec": {
                    "taskCount": 1,
                    "parallelism": 1,
                    "template": {"spec": spec},
                },
            }
        },
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as manifest:
        json.dump(job, manifest)
        manifest.flush()
        subprocess.run(
            ["gcloud", "run", "jobs", "replace", manifest.name, *flags, "--quiet"],
            check=True,
            capture_output=True,
            text=True,
        )
    subprocess.run(
        ["gcloud", "run", "jobs", "execute", job_name, *flags, "--wait", "--quiet"],
        check=True,
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["--validate-only"]:
        validate_configuration()
    else:
        bootstrap_cloud_run()
