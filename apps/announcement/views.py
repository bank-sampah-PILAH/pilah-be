"""Pengumuman HTTP layer: pengurus authoring/manage (PIL-243, PIL-332) and
nasabah list/detail/read state (PIL-244).

Thin adapter — permissions, scoping, and marshalling. Workflow rules live in
apps/announcement/services.py; payload validation in serializers.py.
"""

from typing import Any
from uuid import UUID

from django.db.models import Case, CharField, Exists, OuterRef, QuerySet, Subquery, Value, When
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from api.models import BankSampah, Pengumuman, PengumumanDibaca, User
from apps.announcement.exceptions import TransisiStatusTidakValid
from apps.announcement.serializers import (
    PengumumanNasabahListSerializer,
    PengumumanSerializer,
    TerbitkanSerializer,
)
from apps.announcement.services import PengumumanService
from apps.nasabah.api import aktif_keanggotaan
from shared_kernel.pagination import StandardPagination
from shared_kernel.permissions import IsActiveNasabah, IsActivePengelola

_STATUS_EFEKTIF_VALUES = {"draft", "terjadwal", "terbit", "kedaluwarsa", "ditarik"}


def _user(request: Request) -> User:
    assert isinstance(request.user, User)  # ponytail: DRF authentication rejects AnonymousUser
    return request.user


def _bank_sampah(request: Request) -> BankSampah:
    bank = _user(request).bank_sampah
    assert bank is not None  # ponytail: IsActivePengelola guarantees bank membership
    return bank


def _pk(kwargs: dict[str, str]) -> UUID:
    return UUID(kwargs["pk"])


def _annotate_status_efektif(queryset: QuerySet[Pengumuman]) -> QuerySet[Pengumuman]:
    now = timezone.now()
    return queryset.annotate(
        _status_efektif=Case(
            When(status=Pengumuman.Status.DITARIK, then=Value("ditarik")),
            When(terbit_pada__gt=now, then=Value("terjadwal")),
            When(status=Pengumuman.Status.DRAFT, then=Value("draft")),
            When(
                masa_berlaku_hingga__isnull=False,
                masa_berlaku_hingga__lte=now,
                then=Value("kedaluwarsa"),
            ),
            default=Value("terbit"),
            output_field=CharField(),
        )
    )


class PengumumanViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]  # stubs are generic, runtime is not
    permission_classes = [IsActivePengelola]
    serializer_class = PengumumanSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self) -> QuerySet[Pengumuman]:
        queryset = Pengumuman.objects.filter(bank_sampah=_bank_sampah(self.request))
        if self.action == "list":
            queryset = _annotate_status_efektif(queryset)
            requested = self.request.query_params.get("status")
            if requested is not None:
                if requested not in _STATUS_EFEKTIF_VALUES:
                    raise serializers.ValidationError({"status": "Status tidak dikenal"})
                queryset = queryset.filter(**{"_status_efektif": requested})
        return queryset

    def perform_create(self, serializer: serializers.BaseSerializer[Any]) -> None:
        # The owner bank always comes from the pengurus, never from input.
        serializer.save(bank_sampah=_bank_sampah(self.request), dibuat_oleh=_user(self.request))

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            return super().update(request, *args, **kwargs)
        except TransisiStatusTidakValid as exc:
            return Response({"error": exc.message}, status=status.HTTP_400_BAD_REQUEST)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.update(request, *args, partial=True, **kwargs)

    def perform_update(self, serializer: serializers.BaseSerializer[Any]) -> None:
        instance = serializer.instance
        assert instance is not None
        PengumumanService.pasti_bisa_diubah(instance)
        attrs = serializer.validated_data
        # Canceling a schedule: PATCH terbit_pada null on a terjadwal
        # announcement flips the persisted status back to draft (PIL-332).
        if (
            instance.status_efektif() == "terjadwal"
            and "terbit_pada" in attrs
            and attrs["terbit_pada"] is None
        ):
            serializer.save(status=Pengumuman.Status.DRAFT, terbit_pada=None)
        else:
            serializer.save()

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            PengumumanService.pasti_bisa_diubah(self.get_object(), hanya_draft=True)
        except TransisiStatusTidakValid as exc:
            return Response({"error": exc.message}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="terbitkan")
    def terbitkan(self, request: Request, pk: str | None = None) -> Response:
        payload = TerbitkanSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            pengumuman = PengumumanService.terbitkan(
                _pk(self.kwargs),
                _bank_sampah(request).id,
                oleh=_user(request),
                terbit_pada=payload.validated_data.get("terbit_pada"),
                masa_berlaku_hingga=payload.validated_data.get("masa_berlaku_hingga"),
            )
        except TransisiStatusTidakValid as exc:
            return Response({"error": exc.message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(pengumuman).data)

    @action(detail=True, methods=["post"], url_path="tarik")
    def tarik(self, request: Request, pk: str | None = None) -> Response:
        try:
            pengumuman = PengumumanService.tarik(
                _pk(self.kwargs), _bank_sampah(request).id, oleh=_user(request)
            )
        except TransisiStatusTidakValid as exc:
            return Response({"error": exc.message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(pengumuman).data)


def _dibaca_annotations(user: User) -> dict[str, Subquery]:
    read_rows = PengumumanDibaca.objects.filter(pengumuman=OuterRef("pk"), user=user)
    return {
        "_dibaca": Exists(read_rows),
        "_dibaca_pada": Subquery(read_rows.values("dibaca_pada")[:1]),
    }


def _aktif_untuk(request: Request) -> QuerySet[Pengumuman]:
    """The nasabah's active announcements for their active membership's bank."""
    member = aktif_keanggotaan(request)
    return Pengumuman.aktif().filter(bank_sampah=member.bank_sampah)


class NasabahPengumumanListView(generics.ListAPIView[Pengumuman]):
    permission_classes = [IsActiveNasabah]
    serializer_class = PengumumanNasabahListSerializer
    pagination_class = StandardPagination

    def get_queryset(self) -> QuerySet[Pengumuman]:
        return _aktif_untuk(self.request).annotate(**_dibaca_annotations(_user(self.request)))


class NasabahPengumumanDetailView(generics.RetrieveAPIView[Pengumuman]):
    permission_classes = [IsActiveNasabah]
    serializer_class = PengumumanNasabahListSerializer

    def get_object(self) -> Pengumuman:
        # Other-bank, expired, and withdrawn announcements are all simply
        # absent from the scoped aktif queryset — one 404 path for all.
        return get_object_or_404(
            _aktif_untuk(self.request).annotate(**_dibaca_annotations(_user(self.request))),
            pk=self.kwargs["pk"],
        )


class NasabahPengumumanBacaView(generics.GenericAPIView[Pengumuman]):
    permission_classes = [IsActiveNasabah]

    def post(self, request: Request, pk: UUID) -> Response:
        pengumuman = get_object_or_404(_aktif_untuk(request), pk=pk)
        row, _created = PengumumanDibaca.objects.get_or_create(
            pengumuman=pengumuman, user=_user(request)
        )
        return Response({"id": str(pengumuman.id), "dibaca": True, "dibaca_pada": row.dibaca_pada})
