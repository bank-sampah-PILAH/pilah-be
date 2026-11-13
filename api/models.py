# ponytail: canonical homes are apps.*.models. This module stays as the Django
# app's model registry (aggregator) so AUTH_USER_MODEL and migrations are
# untouched; all logic lives in apps/*.
from apps.announcement.models import Pengumuman, PengumumanDibaca  # noqa: F401
from apps.authentication.models import User, UserManager, UserRoleChangeLog  # noqa: F401
from apps.bank_sampah.models import BankSampah, BankSampahApprovalLog  # noqa: F401
from apps.jadwal.models import JadwalKegiatan  # noqa: F401
from apps.ledger.models import (  # noqa: F401
    DetailTransaksi,
    DraftPencairan,
    DraftPencairanItem,
    Pencairan,
    PencairanRevisi,
    Saldo,
    Transaksi,
    TransaksiQuerySet,
    TransaksiRevisi,
)
from apps.nasabah.models import Nasabah, NasabahApprovalLog  # noqa: F401
from apps.notification.models import DeviceToken, PushDelivery, PushNotification  # noqa: F401
from apps.waste_catalog.models import HargaSampah, JenisSampah  # noqa: F401
from shared_kernel.models import TimestampedModel  # noqa: F401

__all__ = [
    "BankSampah",
    "BankSampahApprovalLog",
    "DetailTransaksi",
    "DeviceToken",
    "HargaSampah",
    "DraftPencairan",
    "DraftPencairanItem",
    "JenisSampah",
    "JadwalKegiatan",
    "Nasabah",
    "NasabahApprovalLog",
    "Pengumuman",
    "PengumumanDibaca",
    "PushDelivery",
    "PushNotification",
    "Pencairan",
    "PencairanRevisi",
    "TransaksiRevisi",
    "Saldo",
    "TimestampedModel",
    "Transaksi",
    "TransaksiQuerySet",
    "User",
    "UserManager",
    "UserRoleChangeLog",
]
