import mimetypes
from typing import Any

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db.models import QuerySet
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from api.models import BankSampah, JenisSampah, Transaksi, User
from api.permissions import IsActivePengelola
from api.serializers import (
    JenisSampahSerializer,
    StatusSerializer,
    TransactionCreateSerializer,
    TransactionDetailSerializer,
    TransactionListSerializer,
)
from api.services import (
    TransactionFilterService,
    TransactionService,
)

# ponytail: compat shims — canonical homes are apps.*.
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
from apps.membership.views import NasabahViewSet, SaldoView  # noqa: F401
from apps.notify.api import send_setoran_receipt
from apps.notify.views import WATemplateView  # noqa: F401
from apps.organization.views import (  # noqa: F401
    BankSampahMeView,
    SuperAdminBankSampahViewSet,
)
from apps.reporting.views import (  # noqa: F401
    DashboardRecentTransactionsView,
    DashboardStatsView,
)


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


class JenisSampahViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]  # stubs are generic, runtime is not
    permission_classes = [IsActivePengelola]
    serializer_class = JenisSampahSerializer
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_queryset(self) -> QuerySet[JenisSampah]:
        qs = JenisSampah.objects.filter(bank_sampah=_bank_sampah(self.request))
        search = self.request.query_params.get("search", "")
        status_filter = self.request.query_params.get("status", "aktif")
        kategori = self.request.query_params.get("kategori")
        if self.action == "list" and len(search) >= 2:
            qs = qs.filter(nama_sampah__icontains=search)
        if self.action == "list":
            if status_filter == "aktif":
                qs = qs.filter(is_active=True)
            elif status_filter == "tidak_aktif":
                qs = qs.filter(is_active=False)
        if self.action == "list" and kategori:
            qs = qs.filter(kategori=kategori)
        return qs.order_by("nomor")

    def create(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        nomor = serializer.validated_data["nomor"]
        bank = _bank_sampah(request)
        if JenisSampah.objects.filter(bank_sampah=bank, nomor=nomor).exists():
            return Response({"errors": {"kode": ["Kode sampah sudah digunakan"]}}, status=422)
        jenis = serializer.save(
            bank_sampah=bank,
        )
        return Response(self.get_serializer(jenis).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        nomor = request.data.get("kode")  # type: ignore[union-attr]  # DRF types request.data as dict | list; these payloads are objects
        if (
            nomor
            and JenisSampah.objects.filter(bank_sampah=_bank_sampah(request), nomor=nomor)
            .exclude(id=instance.id)
            .exists()
        ):
            return Response({"errors": {"kode": ["Kode sampah sudah digunakan"]}}, status=422)
        return super().update(request, *args, **kwargs)

    @action(detail=True, methods=["patch"], url_path="status")
    def set_status(self, request: Request, pk: str | None = None) -> Response:
        jenis = self.get_object()
        serializer = StatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        jenis.is_active = serializer.validated_data["is_active"]
        jenis.save(update_fields=["is_active", "updated_at"])
        state = "diaktifkan" if jenis.is_active else "dinonaktifkan"
        return Response(
            {
                "id": str(jenis.id),
                "is_active": jenis.is_active,
                "message": f"Jenis sampah berhasil {state}",
            }
        )


class TransaksiViewSet(viewsets.GenericViewSet):  # type: ignore[type-arg]  # stubs are generic, runtime is not
    permission_classes = [IsActivePengelola]
    serializer_class = TransactionListSerializer

    def get_serializer_class(
        self,
    ) -> type[
        TransactionCreateSerializer | TransactionDetailSerializer | TransactionListSerializer
    ]:
        if self.action == "create":
            return TransactionCreateSerializer
        if self.action == "retrieve":
            return TransactionDetailSerializer
        return TransactionListSerializer

    def get_queryset(self) -> QuerySet[Transaksi]:
        qs = (
            Transaksi.objects.filter(bank_sampah=_bank_sampah(self.request))
            .select_related("nasabah", "bank_sampah", "dicatat_oleh")
            .prefetch_related("items")
        )
        search = self.request.query_params.get("search", "")
        nasabah_id = self.request.query_params.get("nasabah_id")
        if len(search) >= 2:
            qs = qs.filter(nasabah__nama__icontains=search)
        if nasabah_id:
            qs = qs.filter(nasabah_id=nasabah_id)
        return qs

    def list(self, request: Request) -> Response:
        qs = self.get_queryset()
        try:
            qs = TransactionFilterService.apply_period(qs, request)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        page = self.paginate_queryset(qs)
        serializer = TransactionListSerializer(page or qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request: Request) -> HttpResponse:
        qs = self.get_queryset()
        try:
            qs = TransactionFilterService.apply_period(qs, request)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        if not qs.exists():
            return Response({"error": "Tidak ada data pada periode ini"}, status=400)
        content, filename = TransactionService.export_excel(qs, request)
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def create(self, request: Request) -> Response:
        serializer = TransactionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transaksi = TransactionService.create_setoran(_user(request), serializer.validated_data)
        return Response(TransactionDetailSerializer(transaksi).data, status=status.HTTP_201_CREATED)

    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        transaksi = self.get_object()
        return Response(TransactionDetailSerializer(transaksi).data)

    @action(detail=True, methods=["post"], url_path="notify-wa")
    def notify_wa(self, request: Request, pk: str | None = None) -> Response:
        transaksi = self.get_object()
        result = send_setoran_receipt(transaksi)
        return Response(result, status=200 if result["success"] else 400)
