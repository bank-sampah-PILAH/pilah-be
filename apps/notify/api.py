"""Public port of the notify context.

Other contexts (ledger today, anything tomorrow) send notifications through
here — never by importing WhatsAppService directly. When delivery needs a
queue, only this function changes.
"""

from typing import Any

from api.models import Transaksi
from apps.notify.services import (  # noqa: F401  # re-exported: notify owns the template default
    DEFAULT_WA_TEMPLATE,
    WhatsAppService,
)

__all__ = ["DEFAULT_WA_TEMPLATE", "send_setoran_receipt"]


def send_setoran_receipt(transaksi: Transaksi) -> dict[str, Any]:
    return WhatsAppService.notify(transaksi)
