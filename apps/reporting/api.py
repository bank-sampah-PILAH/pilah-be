"""Public port of the reporting context.

Ledger views need the Excel export; they call it here instead of importing
apps.reporting.exporter, so reporting owns its export format and the
dependency stays one-directional (reporting -> ledger models, ledger ->
reporting port).
"""

from django.db.models import QuerySet
from django.http import HttpRequest

from api.models import DraftPencairan, Transaksi
from apps.reporting import draft_export, exporter

__all__ = ["export_draft_pencairan", "export_excel"]


def export_excel(
    queryset: QuerySet[Transaksi], request: HttpRequest | None = None
) -> tuple[bytes, str]:
    return exporter.export_excel(queryset, request)


def export_draft_pencairan(draft: DraftPencairan, berkas: str) -> tuple[bytes, str, str]:
    return draft_export.export_draft_pencairan(draft, berkas)
