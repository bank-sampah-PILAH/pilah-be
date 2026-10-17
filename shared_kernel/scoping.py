from typing import TypeVar

from django.db import models
from django.db.models import QuerySet
from rest_framework.request import Request

from api.models import BankSampah, User

M = TypeVar("M", bound=models.Model)


def for_bank(qs: QuerySet[M], bank: BankSampah) -> QuerySet[M]:
    """Scope a bank-owned queryset to one bank.

    Centralizes the bank_sampah= convention so views filter one way.
    """
    return qs.filter(bank_sampah=bank)


def current_user(request: Request) -> User:
    assert isinstance(request.user, User)  # ponytail: DRF authentication rejects AnonymousUser
    return request.user


def current_bank(request: Request) -> BankSampah:
    bank = current_user(request).bank_sampah
    assert bank is not None  # ponytail: IsActivePengelola guarantees bank membership
    return bank
