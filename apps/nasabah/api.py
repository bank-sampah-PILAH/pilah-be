"""Public port of the membership context.

Read/write access to Nasabah rows from other contexts goes through here so
the locking and eligibility rules live in one place. Callers needing the
row lock must already be inside @transaction.atomic.
"""

from collections.abc import Iterable
from uuid import UUID

from django.db.models import QuerySet

from api.models import BankSampah, Nasabah


def _eligible_in(bank: BankSampah) -> QuerySet[Nasabah]:
    return Nasabah.objects.filter(bank_sampah=bank, is_active=True, status=Nasabah.Status.APPROVED)


def _eligible(bank: BankSampah, nasabah_id: UUID) -> QuerySet[Nasabah]:
    return _eligible_in(bank).filter(id=nasabah_id)


def get_locked_nasabah(bank: BankSampah, nasabah_id: UUID) -> Nasabah | None:
    return _eligible(bank, nasabah_id).select_for_update().first()


def get_eligible_nasabah_map(bank: BankSampah, nasabah_ids: Iterable[UUID]) -> dict[UUID, Nasabah]:
    """Same eligibility as `get_locked_nasabah`, for many nasabah in one query and no row lock.

    Saldo comes along; a nasabah who is not eligible is absent from the result.
    """
    rows = _eligible_in(bank).filter(id__in=list(nasabah_ids)).select_related("saldo")
    return {nasabah.id: nasabah for nasabah in rows}
