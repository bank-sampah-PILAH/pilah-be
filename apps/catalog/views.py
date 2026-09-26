from typing import Any

from django.db.models import QuerySet
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from api.models import JenisSampah
from apps.catalog.serializers import JenisSampahSerializer
from apps.membership.serializers import StatusSerializer
from shared_kernel.permissions import IsActivePengelola
from shared_kernel.scoping import current_bank


class JenisSampahViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]  # stubs are generic, runtime is not
    permission_classes = [IsActivePengelola]
    serializer_class = JenisSampahSerializer
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_queryset(self) -> QuerySet[JenisSampah]:
        qs = JenisSampah.objects.filter(bank_sampah=current_bank(self.request))
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
        bank = current_bank(request)
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
            and JenisSampah.objects.filter(bank_sampah=current_bank(request), nomor=nomor)
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
