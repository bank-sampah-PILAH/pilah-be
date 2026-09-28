"""Views without a bounded-context home yet (PIL-283+ additions).

ponytail: PR48 ports these into apps.* contexts as they stabilize; until
then they stay here so api.urls has one import point.
"""
import json
import requests
from decimal import Decimal
from io import BytesIO
from typing import Any, cast

from django.core import signing
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.http import Http404
from django.http import HttpRequest
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import serializers, status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from shared_kernel.permissions import (
    IsActiveNasabah,
    IsActivePengelola,
    IsActivePengelolaOrNasabah,
    IsJadwalViewer,
    IsNasabah,
    IsNasabahRole,
)
from api.models import BankSampah, JadwalKegiatan, Nasabah, Pencairan, User
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status, viewsets
from rest_framework.decorators import action

from api.services import (
    AuthService,
    AuthServiceError,
    OnboardingService,
    PencairanService,
    TransactionFilterService,
)
from apps.membership.serializers import NasabahSerializer

from api.serializers import (
    BankSampahDirectorySerializer,
    GoogleRegistrationSerializer,
    JadwalKegiatanSerializer,
    NasabahSelfRegistrationSerializer,
    NasabahSelfViewSerializer,
    PencairanCreateSerializer,
    PencairanDetailSerializer,
    PencairanEditSerializer,
    PencairanRevisiSerializer,
)


def _user(request: Request) -> User:
    assert isinstance(request.user, User)  # ponytail: DRF authentication rejects AnonymousUser
    return request.user



def _auth_service_error_response(error: AuthServiceError) -> Response:
    return Response({"error": str(error), "code": error.code}, status=error.status_code)



def _bank_sampah(request: Request) -> BankSampah:
    bank = _user(request).bank_sampah
    assert bank is not None  # ponytail: IsActivePengelola guarantees bank membership
    return bank

class GoogleRegistrationView(APIView):
    permission_classes = [AllowAny]
    serializer_class = GoogleRegistrationSerializer

    def post(self, request: Request) -> Response:
        serializer = GoogleRegistrationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=422)
        try:
            payload, created = AuthService.register_with_google(
                serializer.validated_data["registration_token"],
                serializer.validated_data["role"],
            )
        except AuthServiceError as exc:
            return _auth_service_error_response(exc)
        return Response(payload, status=201 if created else 200)




class RegisterNasabahView(APIView):
    permission_classes = [IsNasabah]
    serializer_class = NasabahSelfRegistrationSerializer

    def post(self, request: Request) -> Response:
        serializer = NasabahSelfRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            nasabah = OnboardingService.register_nasabah(_user(request), serializer.validated_data)
        except PermissionError as exc:
            return Response({"error": str(exc)}, status=403)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        data = NasabahSerializer(nasabah).data
        data["next_step"] = AuthService.user_state(_user(request))
        return Response(data, status=201)




class NasabahSelfView(APIView):
    """A nasabah's own membership rows (beranda-first onboarding, PIL-204):
    status, and the pengurus's reason when rejected, so the app can show
    it and let the user appeal by reapplying via `RegisterNasabahView`
    rather than being stalled on a blocking approval screen.
    """

    permission_classes = [IsNasabahRole]
    serializer_class = NasabahSelfViewSerializer

    def get(self, request: Request) -> Response:
        memberships = Nasabah.objects.filter(user=_user(request)).select_related("bank_sampah")
        return Response(NasabahSelfViewSerializer(memberships, many=True).data)




class BankSampahDirectoryView(APIView):
    """Lists bank sampah a calon nasabah can apply to join.

    Excludes `induk` organizations — they are administrative parents with no
    direct membership of their own; a nasabah joins one of their `unit`
    branches, or a standalone `mandiri` bank sampah, instead.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = BankSampahDirectorySerializer

    def get(self, request: Request) -> Response:
        banks = (
            BankSampah.objects.filter(status=BankSampah.Status.ACTIVE, is_active=True)
            .exclude(jenis_organisasi=BankSampah.OrganizationType.INDUK)
            .order_by("nama")
        )
        return Response(BankSampahDirectorySerializer(banks, many=True).data)




class JadwalKegiatanViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]  # stubs are generic, runtime is not
    permission_classes = [IsActivePengelola]
    serializer_class = JadwalKegiatanSerializer
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_permissions(self) -> list[Any]:
        permission_classes = (
            [IsJadwalViewer]
            if self.action in {"list", "retrieve", "calendar_dates"}
            else [IsActivePengelola]
        )
        return [permission() for permission in permission_classes]

    def get_queryset(self) -> QuerySet[JadwalKegiatan]:
        user = _user(self.request)
        queryset = JadwalKegiatan.objects.select_related("bank_sampah", "dibuat_oleh")
        if user.role == User.Role.NASABAH:
            queryset = (
                queryset.filter(
                    bank_sampah__status=BankSampah.Status.ACTIVE,
                    bank_sampah__is_active=True,
                    bank_sampah__nasabah__user=user,
                    bank_sampah__nasabah__is_active=True,
                    bank_sampah__nasabah__status=Nasabah.Status.APPROVED,
                    status=JadwalKegiatan.Status.DITERBITKAN,
                    selesai_pada__gte=timezone.now(),
                )
                .filter(
                    Q(cakupan_penerima=JadwalKegiatan.CakupanPenerima.SEMUA_NASABAH)
                    | Q(penerima__user=user, penerima__is_active=True)
                )
                .distinct()
            )
        else:
            overlapping_schedules = (
                JadwalKegiatan.objects.filter(
                    bank_sampah=OuterRef("bank_sampah"),
                    lokasi__iexact=OuterRef("lokasi"),
                    mulai_pada__lt=OuterRef("selesai_pada"),
                    selesai_pada__gt=OuterRef("mulai_pada"),
                )
                .exclude(pk=OuterRef("pk"))
                .exclude(status=JadwalKegiatan.Status.DIBATALKAN)
            )
            queryset = (
                queryset.filter(bank_sampah=_bank_sampah(self.request))
                .prefetch_related("penerima")
                .annotate(_peringatan_jadwal_bertumpuk=Exists(overlapping_schedules))
            )
        if self.action == "list":
            date_value = self.request.query_params.get("date")
            if isinstance(date_value, str) and date_value:
                date = parse_date(date_value)
                if date is None:
                    raise serializers.ValidationError(
                        {"date": "Gunakan tanggal dengan format YYYY-MM-DD"}
                    )
                queryset = queryset.filter(mulai_pada__date=date)
            queryset = queryset.order_by("mulai_pada", "pk")
        if self.action in {"update", "partial_update"}:
            queryset = queryset.select_for_update()
        return queryset

    @action(detail=False, methods=["get"], url_path="calendar-dates")
    def calendar_dates(self, request: Request) -> Response:
        start_value = request.query_params.get("start_date")
        end_value = request.query_params.get("end_date")
        start_date = parse_date(start_value or "")
        end_date = parse_date(end_value or "")
        if start_date is None or end_date is None:
            raise serializers.ValidationError(
                {"date_range": ("start_date dan end_date wajib menggunakan format YYYY-MM-DD")}
            )
        if end_date < start_date:
            raise serializers.ValidationError(
                {"end_date": "end_date harus sama dengan atau setelah start_date"}
            )
        if (end_date - start_date).days > 62:
            raise serializers.ValidationError({"date_range": "Rentang kalender maksimal 63 hari"})

        dates = (
            self.get_queryset()
            .filter(mulai_pada__date__range=(start_date, end_date))
            .order_by()
            .dates("mulai_pada", "day", order="ASC")
        )
        return Response({"dates": [date.isoformat() for date in dates]})

    def perform_create(self, serializer: serializers.BaseSerializer[Any]) -> None:
        serializer.save(bank_sampah=_bank_sampah(self.request), dibuat_oleh=_user(self.request))

    def perform_update(self, serializer: serializers.BaseSerializer[Any]) -> None:
        instance = serializer.save()
        if hasattr(instance, "_peringatan_jadwal_bertumpuk"):
            delattr(instance, "_peringatan_jadwal_bertumpuk")

    @transaction.atomic
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        instance.refresh_from_db(fields=["status"])
        if instance.status in {JadwalKegiatan.Status.DIBATALKAN, JadwalKegiatan.Status.SELESAI}:
            return Response(
                {"error": "Jadwal yang dibatalkan atau selesai tidak dapat diubah"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        if getattr(instance, "_prefetched_objects_cache", None):
            instance._prefetched_objects_cache = {}
        return Response(serializer.data)

    def _transition(
        self,
        jadwal: JadwalKegiatan,
        *,
        allowed_from: set[str],
        target: str,
    ) -> Response:
        updated = JadwalKegiatan.objects.filter(pk=jadwal.pk, status__in=allowed_from).update(
            status=target, updated_at=timezone.now()
        )
        if not updated:
            return Response(
                {"error": "Perubahan status jadwal tidak diizinkan"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=["post"], url_path="terbitkan")
    def terbitkan(self, request: Request, pk: str | None = None) -> Response:
        return self._transition(
            self.get_object(),
            allowed_from={JadwalKegiatan.Status.DRAFT},
            target=JadwalKegiatan.Status.DITERBITKAN,
        )

    @action(detail=True, methods=["post"], url_path="batalkan")
    def batalkan(self, request: Request, pk: str | None = None) -> Response:
        return self._transition(
            self.get_object(),
            allowed_from={JadwalKegiatan.Status.DRAFT, JadwalKegiatan.Status.DITERBITKAN},
            target=JadwalKegiatan.Status.DIBATALKAN,
        )

    @action(detail=True, methods=["post"], url_path="selesaikan")
    def selesaikan(self, request: Request, pk: str | None = None) -> Response:
        return self._transition(
            self.get_object(),
            allowed_from={JadwalKegiatan.Status.DITERBITKAN},
            target=JadwalKegiatan.Status.SELESAI,
        )




class PencairanViewSet(viewsets.GenericViewSet):  # type: ignore[type-arg]  # stubs are generic, runtime is not
    permission_classes = [IsActivePengelola]
    serializer_class = PencairanDetailSerializer

    def get_permissions(self) -> list[BasePermission]:
        # Recording stays pengurus-only; nasabah may read their own riwayat.
        if self.action in ("list", "retrieve"):
            return [IsActivePengelolaOrNasabah()]
        return [IsActivePengelola()]

    def get_queryset(self) -> QuerySet[Pencairan]:
        user = _user(self.request)
        if user.role == User.Role.NASABAH:
            qs = Pencairan.objects.filter(nasabah__user=user)
        else:
            qs = Pencairan.objects.filter(bank_sampah=_bank_sampah(self.request))
        qs = qs.select_related("nasabah", "bank_sampah", "dicatat_oleh")
        nasabah_id = self.request.query_params.get("nasabah_id")
        search = self.request.query_params.get("search", "")
        if nasabah_id:
            qs = qs.filter(nasabah_id=nasabah_id)
        if len(search) >= 2:
            qs = qs.filter(nasabah__nama__icontains=search)
        return PencairanService.dengan_info_revisi(qs)

    def list(self, request: Request) -> Response:
        # Unlike transaksi, no periode means the whole history (per-nasabah riwayat).
        try:
            qs = TransactionFilterService.apply_period(self.get_queryset(), request, default=None)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        # Pagination is configured globally (PAGE_SIZE), so a page always exists.
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(PencairanDetailSerializer(page, many=True).data)

    def create(self, request: Request) -> Response:
        serializer = PencairanCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pencairan = PencairanService.create_pencairan(_user(request), serializer.validated_data)
        return Response(PencairanDetailSerializer(pencairan).data, status=status.HTTP_201_CREATED)

    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        return Response(PencairanDetailSerializer(self.get_object()).data)

    def partial_update(self, request: Request, pk: str | None = None) -> Response:
        serializer = PencairanEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pencairan = PencairanService.edit_pencairan(
            _user(request), self.get_object(), serializer.validated_data
        )
        return Response(PencairanDetailSerializer(pencairan).data)

    @action(detail=True, methods=["get"], url_path="riwayat")
    def riwayat(self, request: Request, pk: str | None = None) -> Response:
        pencairan = self.get_object()
        revisi = pencairan.revisi.select_related("diubah_oleh").order_by("-versi")
        return Response(
            {
                "pencairan": PencairanDetailSerializer(pencairan).data,
                "revisi": PencairanRevisiSerializer(revisi, many=True).data,
            }
        )


