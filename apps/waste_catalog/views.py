from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from api.models import JenisSampah
from apps.nasabah.serializers import StatusSerializer
from apps.waste_catalog.api import buat_jenis_sampah, harga_berlaku
from apps.waste_catalog.serializers import (
    FilterJenisSampahSerializer,
    HargaBaruSerializer,
    JenisSampahSerializer,
)
from apps.waste_catalog.services import catat_harga
from shared_kernel.permissions import IsActivePengelola
from shared_kernel.scoping import current_bank, current_user


class JenisSampahViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]  # stubs are generic, runtime is not
    permission_classes = [IsActivePengelola]
    serializer_class = JenisSampahSerializer
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_queryset(self) -> QuerySet[JenisSampah]:
        qs = JenisSampah.objects.filter(bank_sampah=current_bank(self.request)).prefetch_related(
            "riwayat_harga"
        )
        if self.action == "list":
            qs = self._saring(qs)
        return qs.order_by("nomor")

    def _saring(self, qs: QuerySet[JenisSampah]) -> QuerySet[JenisSampah]:
        filter_ = FilterJenisSampahSerializer(data=self.request.query_params)
        filter_.is_valid(raise_exception=True)
        search = self.request.query_params.get("search", "")
        if len(search) >= 2:
            qs = qs.filter(nama_sampah__icontains=search)
        status_filter = filter_.validated_data["status"]
        if status_filter == "aktif":
            qs = qs.filter(is_active=True)
        elif status_filter == "tidak_aktif":
            qs = qs.filter(is_active=False)
        kategori = filter_.validated_data.get("kategori")
        if kategori:
            qs = qs.filter(kategori=kategori)
        return qs

    def create(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        nomor = serializer.validated_data["nomor"]
        bank = current_bank(request)
        if JenisSampah.objects.filter(bank_sampah=bank, nomor=nomor).exists():
            return Response({"errors": {"kode": ["Kode sampah sudah digunakan"]}}, status=422)
        data = dict(serializer.validated_data)
        harga = data.pop("harga_per_kg")
        jenis = buat_jenis_sampah(bank, harga_per_kg=harga, oleh=current_user(request), **data)
        return Response(self.get_serializer(jenis).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        nomor = request.data.get("kode")  # type: ignore[union-attr]  # DRF types request.data as dict | list; these payloads are objects
        if (
            nomor
            and JenisSampah.objects.filter(bank_sampah=current_bank(request), nomor=nomor)
            .exclude(id=instance.id)
            .exists()
        ):
            return Response({"errors": {"kode": ["Kode sampah sudah digunakan"]}}, status=422)
        return super().update(request, *args, **kwargs)

    @transaction.atomic
    def perform_update(self, serializer: BaseSerializer[JenisSampah]) -> None:
        # Aplikasi lama mengirim harga lewat PUT; harga yang berubah tetap
        # menjadi versi baru yang tercatat, bukan menimpa harga lama.
        sekarang = timezone.now()
        jenis = serializer.instance
        assert jenis is not None  # ponytail: update always has an instance
        harga_lama = harga_berlaku(jenis, sekarang)
        harga_baru = serializer.validated_data.pop("harga_per_kg", None)
        jenis = serializer.save()
        if harga_baru is not None and harga_baru != harga_lama:
            catat_harga(jenis, harga_baru, sekarang, current_user(self.request))

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

    @action(detail=True, methods=["post"], url_path="harga")
    def ubah_harga(self, request: Request, pk: str | None = None) -> Response:
        jenis = self.get_object()
        serializer = HargaBaruSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        catat_harga(
            jenis,
            serializer.validated_data["harga_per_kg"],
            serializer.validated_data.get("berlaku_mulai") or timezone.now(),
            current_user(request),
        )
        # Muat ulang: riwayat harga hasil prefetch get_object() belum memuat versi baru.
        jenis = self.get_object()
        return Response(self.get_serializer(jenis).data, status=status.HTTP_201_CREATED)
