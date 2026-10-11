"""Port of the ledger context.

Other bounded contexts must not import apps.ledger.services directly (guarded
by tests/test_architecture.py); the operations other contexts reach for —
period filtering and balance lookups — go through this port like every other
cross-context operation.
"""

from datetime import datetime
from decimal import Decimal
from typing import TypeVar
from uuid import UUID

from django.db.models import Model, QuerySet
from django.http import HttpRequest

from api.models import BankSampah
from apps.ledger.services import BalanceService, TransactionFilterService

__all__ = ["apply_period", "saldo_at"]

_Dated = TypeVar("_Dated", bound=Model)


def apply_period(
    queryset: QuerySet[_Dated], request: HttpRequest, default: str | None = "hari_ini"
) -> QuerySet[_Dated]:
    """Filter an event queryset (``tanggal`` field) by the ``periode`` param.

    Thin pass-through to ledger's ``TransactionFilterService``; see there for
    the accepted values and the custom-range date params. ``default=None``
    means "omit the param = no date filter".
    """
    return TransactionFilterService.apply_period(queryset, request, default)


def saldo_at(bank_sampah: BankSampah, nasabah_id: UUID, until: datetime, until_id: UUID) -> Decimal:
    """Running saldo of a nasabah at a point in time (thin pass-through)."""
    return BalanceService.saldo_at(bank_sampah, nasabah_id, until, until_id)
