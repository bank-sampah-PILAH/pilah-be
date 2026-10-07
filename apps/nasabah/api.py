"""Public port of the membership context.

Read/write access to Nasabah rows from other contexts goes through here so
the locking and eligibility rules live in one place. Callers needing the
row lock must already be inside @transaction.atomic.
"""

from uuid import UUID

from django.db.models import QuerySet

from api.models import BankSampah, Nasabah


def _eligible(bank: BankSampah, nasabah_id: UUID) -> QuerySet[Nasabah]:
    return Nasabah.objects.filter(
        id=nasabah_id,
        bank_sampah=bank,
        is_active=True,
        status=Nasabah.Status.APPROVED,
    )


def get_locked_nasabah(bank: BankSampah, nasabah_id: UUID) -> Nasabah | None:
    return _eligible(bank, nasabah_id).select_for_update().first()


def get_eligible_nasabah(bank: BankSampah, nasabah_id: UUID) -> Nasabah | None:
    """Same eligibility as `get_locked_nasabah`, without the row lock (drafts hold none)."""
    return _eligible(bank, nasabah_id).first()
