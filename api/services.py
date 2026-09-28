"""Compatibility shim for the pre-refactor monolith module (PIL-48).

Tests patch `api.services.*` targets; the implementation now lives in the
bounded contexts (apps.identity / apps.ledger). Everything public is
re-exported here so patch targets and historical imports keep working.
"""

import requests
from google.oauth2 import id_token as google_id_token  # noqa: F401  (patch target)

from apps.catalog.api import (
    next_jenis_number,  # noqa: F401  (was NumberingService.next_jenis_number)
)
from apps.identity.services import (
    REGISTRATION_TOKEN_MAX_AGE,
    REGISTRATION_TOKEN_SALT,
    AuthService,
    AuthServiceError,
    OnboardingService,
    TeamService,
)
from apps.ledger.services import PencairanService, TransactionFilterService
from apps.membership.api import (
    next_nasabah_number,  # noqa: F401  (was NumberingService.next_nasabah_number)
)
from apps.membership.services import NasabahApprovalService
from apps.notify.services import WhatsAppService

__all__ = [
    "REGISTRATION_TOKEN_MAX_AGE",
    "REGISTRATION_TOKEN_SALT",
    "AuthService",
    "AuthServiceError",
    "next_nasabah_number",
    "next_jenis_number",
    "OnboardingService",
    "TeamService",
    "PencairanService",
    "TransactionFilterService",
    "NasabahApprovalService",
    "WhatsAppService",
    "google_id_token",
    "requests",
]
