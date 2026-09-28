# ponytail: canonical homes are apps.*.models. This module stays as the Django
# app's model registry (aggregator) so AUTH_USER_MODEL and migrations are
# untouched; all logic lives in apps/*.
from apps.authentication.models import User, UserManager  # noqa: F401
from apps.bank_sampah.models import BankSampah, BankSampahApprovalLog  # noqa: F401
from apps.ledger.models import (  # noqa: F401
    DetailTransaksi,
    JadwalKegiatan,
    Pencairan,
    PencairanRevisi,
    Transaksi,
)
from apps.nasabah.models import Nasabah, NasabahApprovalLog, Saldo  # noqa: F401
from apps.waste_catalog.models import JenisSampah  # noqa: F401
from shared_kernel.models import TimestampedModel  # noqa: F401

__all__ = [
    "BankSampah",
    "BankSampahApprovalLog",
    "DetailTransaksi",
    "JenisSampah",
    "JadwalKegiatan",
    "Nasabah",
    "NasabahApprovalLog",
    "Pencairan",
    "PencairanRevisi",
    "Saldo",
    "TimestampedModel",
    "Transaksi",
    "User",
    "UserManager",
]
