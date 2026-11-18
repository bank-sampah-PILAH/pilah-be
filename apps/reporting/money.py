"""Database counterpart of shared_kernel.kalkulasi.bulatkan_rupiah (ROUND_DOWN)."""

from django.db.models import Case, Sum, When
from django.db.models.functions import Ceil, Floor


def sum_full_rupiah(field: str) -> Sum:
    """Truncate each value toward zero before summing, including legacy negatives."""
    return Sum(Case(When(**{f"{field}__lt": 0}, then=Ceil(field)), default=Floor(field)))
