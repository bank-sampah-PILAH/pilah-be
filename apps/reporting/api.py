"""Public port of the reporting context.

Views outside the reporting context need its exports; they call them here
instead of importing apps.reporting.exporter/statement directly, so reporting
owns its export formats and the dependency stays one-directional (reporting ->
api.models, other BCs -> reporting port).
"""

from django.db.models import QuerySet
from django.http import HttpRequest

from api.models import Nasabah, Transaksi
from apps.reporting import exporter, statement

__all__ = ["export_excel", "export_statement_pdf"]


def export_excel(
    queryset: QuerySet[Transaksi], request: HttpRequest | None = None
) -> tuple[bytes, str]:
    return exporter.export_excel(queryset, request)


def export_statement_pdf(member: Nasabah, request: HttpRequest) -> tuple[bytes, str] | None:
    """Riwayat aktivitas statement PDF; None when the window holds no activity."""
    return statement.export_statement_pdf(member, request)
