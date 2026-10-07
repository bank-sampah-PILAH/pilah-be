"""Public port of the membership context.

Read/write access to Nasabah rows from other contexts goes through here so
the locking and eligibility rules live in one place. Callers needing the
row lock must already be inside @transaction.atomic.
"""

from decimal import Decimal
from uuid import UUID

from django.db.models import Q, QuerySet

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


_KANDIDAT_URUTAN = {
    "nama": "nama",
    "-nama": "-nama",
    "saldo": "saldo__total_saldo",
    "-saldo": "-saldo__total_saldo",
}


def kandidat_pencairan(
    bank: BankSampah, *, search: str = "", saldo_min: Decimal = Decimal(0), ordering: str = "nama"
) -> QuerySet[Nasabah]:
    """Nasabah a pengurus can still pay out: active, approved, with at least Rp 1.

    One place for the "memenuhi syarat" rule so the picker and the batch builder agree.
    """
    qs = Nasabah.objects.filter(
        bank_sampah=bank,
        is_active=True,
        status=Nasabah.Status.APPROVED,
        saldo__total_saldo__gte=max(saldo_min, Decimal(1)),
    ).select_related("saldo")
    if len(search) >= 2:
        qs = qs.filter(
            Q(nama__icontains=search) | Q(nomor__icontains=search) | Q(no_hp__icontains=search)
        )
    return qs.order_by(_KANDIDAT_URUTAN[ordering], "nomor")
