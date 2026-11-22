from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from api.models import Nasabah, Saldo, User
from apps.ledger.serializers import PencairanDetailSerializer
from apps.ledger.services import PencairanService


def catat_pencairan(
    user: User,
    nasabah: Nasabah,
    nominal: str,
    *,
    tanggal: datetime | None = None,
    keterangan: str = "",
) -> dict[str, Any]:
    """Record a tunai pencairan the way draft confirmation does, for test fixtures."""
    with transaction.atomic():
        saldo = Saldo.objects.select_for_update().get(nasabah=nasabah)
        pencairan = PencairanService.realisasi(
            user=user,
            nasabah=nasabah,
            saldo=saldo,
            nominal=Decimal(nominal),
            metode="tunai",
            tanggal=tanggal or timezone.now(),
            keterangan=keterangan,
        )
    return dict(PencairanDetailSerializer(pencairan).data)
