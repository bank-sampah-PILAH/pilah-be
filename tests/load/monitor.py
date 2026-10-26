"""Read guest CPU/memory and PostgreSQL connection/lock samples on Fly staging."""

import json
import os
import sys
import time
from pathlib import Path


def main() -> None:
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.conf import settings
    from django.db import connection

    host = settings.DATABASES["default"]["HOST"]
    if settings.PILAH_ENVIRONMENT != "staging" or (
        not isinstance(host, str) or not host.endswith(".neon.tech")
    ):
        raise SystemExit("Only isolated Fly staging may be monitored")
    previous = None
    until = time.monotonic() + 420
    while time.monotonic() < until:
        now = time.monotonic()
        cpu = [int(n) for n in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
        memory = {
            key: value
            for key, value in (
                line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()
            )
        }
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*), count(*) FILTER (WHERE state='active'), "
                "count(*) FILTER (WHERE wait_event_type='Lock') "
                "FROM pg_stat_activity WHERE datname=current_database()"
            )
            connections, active, waiting = cursor.fetchone()
        data = {
            "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "memory_used_kib": int(memory["MemTotal"].split()[0])
            - int(memory["MemAvailable"].split()[0]),
            "db_connections": connections,
            "db_active": active,
            "db_lock_waiters": waiting,
        }
        if previous:
            old_time, old_cpu = previous
            busy_ticks = sum(cpu[i] - old_cpu[i] for i in (0, 1, 2, 5, 6, 7))
            data["cpu_percent_of_one_core"] = (
                100 * busy_ticks / os.sysconf("SC_CLK_TCK") / (now - old_time)
            )
        previous = now, cpu
        print(json.dumps(data), flush=True)
        time.sleep(15)


if __name__ == "__main__":
    main()
