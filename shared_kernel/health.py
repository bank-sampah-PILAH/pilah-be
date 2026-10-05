from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET


@require_GET  # S3752: liveness probe; orchestrators poll with GET.
def healthz(request: HttpRequest) -> JsonResponse:
    """Liveness/readiness probe for container orchestrators.

    DB round-trip on every probe: cheap enough here, and catches the
    "app is up but its database connection is dead" failure mode.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db_ok = True
    except Exception:  # noqa: BLE001 - any DB failure means unhealthy
        db_ok = False

    return JsonResponse(
        {"status": "ok" if db_ok else "degraded", "database": db_ok},
        status=200 if db_ok else 503,
    )
