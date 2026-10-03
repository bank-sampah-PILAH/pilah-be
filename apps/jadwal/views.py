"""Jadwal kegiatan endpoints, moved out of ledger (PR #64 review item 2).

A schedule may serve activities beyond setoran and pencairan, so it is not
tied to the ledger context.
"""

from typing import Any

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from api.models import BankSampah, JadwalKegiatan, Nasabah, User
from apps.jadwal.serializers import JadwalKegiatanSerializer
from shared_kernel.permissions import IsActivePengelola, IsJadwalViewer


def _user(request: Request) -> User:
    assert isinstance(request.user, User)  # ponytail: DRF authentication rejects AnonymousUser
    return request.user


def _bank_sampah(request: Request) -> BankSampah:
    bank = _user(request).bank_sampah
    assert bank is not None  # ponytail: IsActivePengelola guarantees bank membership
    return bank


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
