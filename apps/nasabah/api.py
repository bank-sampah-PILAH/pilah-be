"""Public port of the membership context.

Read/write access to Nasabah rows from other contexts goes through here so
the locking and eligibility rules live in one place. Callers needing the
row lock must already be inside @transaction.atomic.
"""

from uuid import UUID

from api.models import BankSampah, Nasabah


def get_locked_nasabah(bank: BankSampah, nasabah_id: UUID) -> Nasabah | None:
    return (
        Nasabah.objects.select_for_update()
        .filter(
            id=nasabah_id,
            bank_sampah=bank,
            is_active=True,
            status=Nasabah.Status.APPROVED,
        )
        .first()
    )


def next_nasabah_number(bank_sampah: BankSampah) -> str:
    count = Nasabah.objects.filter(bank_sampah=bank_sampah).count() + 1
    return f"NAS-{count:04d}"
