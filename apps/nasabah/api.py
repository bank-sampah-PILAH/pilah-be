"""Public port of the membership context.

Read/write access to Nasabah rows from other contexts goes through here so
the locking and eligibility rules live in one place. Callers needing the
row lock must already be inside @transaction.atomic.
"""

from decimal import Decimal
from uuid import UUID

from django.db.models import F, Q, QuerySet, Value
from django.db.models.functions import Coalesce

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
    "saldo": "saldo_nilai",
    "-saldo": "-saldo_nilai",
}


def kandidat_pencairan(
    bank: BankSampah,
    *,
    search: str = "",
    saldo_min: Decimal = Decimal(0),
    ordering: str = "nama",
    termasuk_kosong: bool = False,
) -> QuerySet[Nasabah]:
    """Nasabah a pengurus can still pay out: active, approved, with at least Rp 1.

    One place for the "memenuhi syarat" rule so the picker and the batch builder agree.
    `termasuk_kosong` is only for showing: the picker lists nasabah without saldo too, so the
    pengurus sees why they cannot be chosen. A draft still never takes them.
    """
    # A nasabah who never transacted has no Saldo row yet: that reads as Rp 0.
    qs = (
        Nasabah.objects.filter(bank_sampah=bank, is_active=True, status=Nasabah.Status.APPROVED)
        .select_related("saldo")
        .annotate(saldo_nilai=Coalesce(F("saldo__total_saldo"), Value(Decimal(0))))
        .filter(saldo_nilai__gte=saldo_min if termasuk_kosong else max(saldo_min, Decimal(1)))
    )
    if len(search) >= 2:
        qs = qs.filter(
            Q(nama__icontains=search) | Q(nomor__icontains=search) | Q(no_hp__icontains=search)
        )
    return qs.order_by(_KANDIDAT_URUTAN[ordering], "nomor")
