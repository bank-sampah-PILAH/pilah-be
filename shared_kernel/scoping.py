from typing import TypeVar

from django.db import models
from django.db.models import QuerySet

from api.models import BankSampah

M = TypeVar("M", bound=models.Model)


def for_bank(qs: QuerySet[M], bank: BankSampah) -> QuerySet[M]:
    """Scope a bank-owned queryset to one bank.

    Centralizes the bank_sampah= convention so views filter one way.
    """
    return qs.filter(bank_sampah=bank)
