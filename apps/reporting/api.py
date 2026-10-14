"""Public port of the reporting context.

Views outside the reporting context need its exports; they call them here
instead of importing apps.reporting.exporter/statement directly, so reporting
owns its export formats and the dependency stays one-directional (reporting ->
api.models, other BCs -> reporting port).
"""

from django.db.models import QuerySet
from django.http import HttpRequest

from api.models import DraftPencairan, Nasabah, Pencairan, Transaksi
from apps.reporting import draft_export, exporter, statement
from apps.reporting.operational import OperationalSummary, operational_queries, operational_summary

__all__ = [
    "StatementPeriodError",
    "export_draft_pencairan",
    "export_excel",
    "export_statement_pdf",
    "operational_queries",
    "operational_summary",
]


def export_excel(
    queryset: QuerySet[Transaksi],
    request: HttpRequest | None = None,
    *,
    payouts: QuerySet[Pencairan] | None = None,
    summary: OperationalSummary | None = None,
) -> tuple[bytes, str]:
    return exporter.export_excel(queryset, request, payouts=payouts, summary=summary)


def export_statement_pdf(member: Nasabah, request: HttpRequest) -> tuple[bytes, str] | None:
    """Riwayat aktivitas statement PDF; None when the window holds no activity."""
    return statement.export_statement_pdf(member, request)


# Re-exported so callers outside reporting can distinguish a period request
# error (→ 400) from a render failure (→ 500) by type, without importing the
# reporting module directly.
StatementPeriodError = statement.StatementPeriodError


def export_draft_pencairan(draft: DraftPencairan, berkas: str) -> tuple[bytes, str, str]:
    return draft_export.export_draft_pencairan(draft, berkas)
