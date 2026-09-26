import mimetypes

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import FileResponse, Http404, HttpRequest
from rest_framework.request import Request

from api.models import BankSampah, User

# ponytail: compat shims — canonical homes are apps.*.
from apps.catalog.views import JenisSampahViewSet  # noqa: F401
from apps.identity.views import (  # noqa: F401
    AcceptInviteView,
    AuthMeView,
    CompleteProfileView,
    GenerateInviteView,
    GoogleAuthView,
    GoogleOAuthCallbackView,
    GoogleOAuthStartView,
    LogoutView,
    RefreshTokenView,
    RegisterBankSampahView,
    TeamView,
)
from apps.ledger.views import TransaksiViewSet  # noqa: F401
from apps.membership.views import NasabahViewSet, SaldoView  # noqa: F401
from apps.notify.views import WATemplateView  # noqa: F401
from apps.organization.views import (  # noqa: F401
    BankSampahMeView,
    SuperAdminBankSampahViewSet,
)
from apps.reporting.views import (  # noqa: F401
    DashboardRecentTransactionsView,
    DashboardStatsView,
)

__all__ = [
    "AcceptInviteView",
    "AuthMeView",
    "BankSampahMeView",
    "CompleteProfileView",
    "DashboardRecentTransactionsView",
    "DashboardStatsView",
    "GenerateInviteView",
    "GoogleAuthView",
    "GoogleOAuthCallbackView",
    "GoogleOAuthStartView",
    "JenisSampahViewSet",
    "LogoutView",
    "NasabahViewSet",
    "RefreshTokenView",
    "RegisterBankSampahView",
    "SaldoView",
    "SuperAdminBankSampahViewSet",
    "TeamView",
    "TransaksiViewSet",
    "WATemplateView",
]


def bank_sampah_activity_media(request: HttpRequest, token: str) -> FileResponse:
    try:
        name = TimestampSigner(salt="bank-sampah-kegiatan").unsign(
            token, max_age=settings.MEDIA_SIGNED_URL_MAX_AGE
        )
    except (BadSignature, SignatureExpired):
        raise Http404 from None

    if not name.startswith("bank_sampah/kegiatan/"):
        raise Http404
    try:
        media_file = default_storage.open(name, "rb")
    except FileNotFoundError:
        raise Http404 from None
    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return FileResponse(media_file, content_type=content_type)


def _user(request: Request) -> User:
    assert isinstance(request.user, User)  # ponytail: DRF authentication rejects AnonymousUser
    return request.user


def _bank_sampah(request: Request) -> BankSampah:
    bank = _user(request).bank_sampah
    assert bank is not None  # ponytail: IsActivePengelola guarantees bank membership
    return bank
