from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Nasabah, Saldo
from apps.bank_sampah.serializers import ApprovalDecisionSerializer
from apps.nasabah.keanggotaan import email_terkunci, profil_akun, sinkronkan_dari_akun
from apps.nasabah.serializers import (
    NasabahApprovalLogSerializer,
    NasabahDetailSerializer,
    NasabahSerializer,
    SaldoSerializer,
    StatusSerializer,
)
from apps.nasabah.services import NasabahApprovalService
from shared_kernel.permissions import IsActivePengelola
from shared_kernel.scoping import current_bank, current_user


class NasabahViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]  # stubs are generic, runtime is not
    permission_classes = [IsActivePengelola]
    serializer_class = NasabahSerializer
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_queryset(self) -> QuerySet[Nasabah]:
        qs = Nasabah.objects.filter(bank_sampah=current_bank(self.request)).select_related("saldo")
        search = self.request.query_params.get("search", "")
        status_filter = self.request.query_params.get("status", "aktif")
        if self.action == "list" and len(search) >= 2:
            qs = qs.filter(
                Q(nama__icontains=search) | Q(no_hp__icontains=search) | Q(email__icontains=search)
            )
        if self.action == "list":
            if status_filter == "aktif":
                qs = qs.filter(is_active=True, status=Nasabah.Status.APPROVED)
            elif status_filter == "tidak_aktif":
                qs = qs.filter(is_active=False, status=Nasabah.Status.APPROVED)
            elif status_filter == "menunggu":
                qs = qs.filter(status=Nasabah.Status.PENDING)
            elif status_filter == "ditolak":
                qs = qs.filter(status=Nasabah.Status.REJECTED)
        return qs.order_by("nomor")

    def get_serializer_class(self) -> type[NasabahSerializer | NasabahDetailSerializer]:
        if self.action == "retrieve":
            return NasabahDetailSerializer
        return NasabahSerializer

    def create(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        nomor = serializer.validated_data["nomor"]
        no_hp = serializer.validated_data["no_hp"]
        bank = current_bank(request)
        if Nasabah.objects.filter(bank_sampah=bank, nomor=nomor).exists():
            return Response({"errors": {"kode": ["ID Nasabah sudah digunakan"]}}, status=422)
        if Nasabah.objects.filter(bank_sampah=bank, no_hp=no_hp).exists():
            return Response({"errors": {"no_hp": ["Nomor HP nasabah sudah digunakan"]}}, status=422)
        email = serializer.validated_data.get("email")
        existing_by_email = (
            Nasabah.objects.filter(bank_sampah=bank, email=email).first() if email else None
        )
        if existing_by_email:
            return Response(
                {"errors": {"email": ["Email sudah terdaftar sebagai nasabah di bank sampah ini"]}},
                status=422,
            )
        nasabah = serializer.save(
            bank_sampah=bank,
        )
        Saldo.objects.create(nasabah=nasabah)
        return Response(self.get_serializer(nasabah).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        if not instance.is_active:
            return Response({"error": "Nasabah nonaktif tidak bisa diedit"}, status=403)
        nomor = request.data.get("kode")  # type: ignore[union-attr]  # DRF types request.data as dict | list; these payloads are objects
        bank = current_bank(request)
        if (
            nomor
            and Nasabah.objects.filter(bank_sampah=bank, nomor=nomor)
            .exclude(id=instance.id)
            .exists()
        ):
            return Response({"errors": {"kode": ["ID Nasabah sudah digunakan"]}}, status=422)
        serializer = self.get_serializer(
            instance, data=request.data, partial=kwargs.pop("partial", False)
        )
        serializer.is_valid(raise_exception=True)
        if email_terkunci(instance, serializer.validated_data):
            return Response(
                {"error": "Email nasabah dengan akun tidak dapat diubah"},
                status=403,
            )
        no_hp = serializer.validated_data.get("no_hp")
        if (
            no_hp
            and Nasabah.objects.filter(bank_sampah=bank, no_hp=no_hp)
            .exclude(id=instance.id)
            .exists()
        ):
            return Response({"errors": {"no_hp": ["Nomor HP nasabah sudah digunakan"]}}, status=422)
        email = serializer.validated_data.get("email")
        existing_by_email = (
            Nasabah.objects.filter(bank_sampah=bank, email=email).exclude(id=instance.id).first()
            if email
            else None
        )
        if existing_by_email:
            return Response(
                {"errors": {"email": ["Email sudah terdaftar sebagai nasabah di bank sampah ini"]}},
                status=422,
            )
        self.perform_update(serializer)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="sinkron-profil")
    def sinkron_profil(self, request: Request, pk: str | None = None) -> Response:
        """Samakan catatan nasabah ini dengan profil yang diisikan nasabah
        sendiri pada akunnya. Pengurus tetap dapat menyuntingnya lagi."""
        nasabah = self.get_object()
        if not nasabah.is_active:
            return Response({"error": "Nasabah nonaktif tidak bisa diedit"}, status=403)
        akun = profil_akun(nasabah)
        if akun is None:
            return Response({"error": "Nasabah belum memiliki akun"}, status=400)
        no_hp = akun["no_hp"]
        no_hp_terpakai = Response(
            {"errors": {"no_hp": ["Nomor HP nasabah sudah digunakan"]}}, status=422
        )
        if (
            no_hp
            and Nasabah.objects.filter(bank_sampah=nasabah.bank_sampah, no_hp=no_hp)
            .exclude(id=nasabah.id)
            .exists()
        ):
            return no_hp_terpakai
        # Pemeriksaan di atas tidak menutup balapan: nomor yang sama dapat
        # dikomit orang lain sebelum `save()`, dan constraint yang menolaknya.
        try:
            with transaction.atomic():
                sinkronkan_dari_akun(nasabah)
        except IntegrityError:
            return no_hp_terpakai
        return Response(NasabahDetailSerializer(nasabah).data)

    @action(detail=True, methods=["patch"], url_path="status")
    def set_status(self, request: Request, pk: str | None = None) -> Response:
        nasabah = self.get_object()
        serializer = StatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        nasabah.is_active = serializer.validated_data["is_active"]
        nasabah.save(update_fields=["is_active", "updated_at"])
        state = "diaktifkan" if nasabah.is_active else "dinonaktifkan"
        return Response(
            {
                "id": str(nasabah.id),
                "is_active": nasabah.is_active,
                "message": f"Nasabah berhasil {state}",
            }
        )

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request: Request, pk: str | None = None) -> Response:
        nasabah = self.get_object()
        if nasabah.status != Nasabah.Status.PENDING:
            return Response(
                {"error": "Hanya pengajuan berstatus menunggu yang dapat diproses"}, status=400
            )
        serializer = ApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        log = NasabahApprovalService.approve(
            nasabah, current_user(request), serializer.validated_data.get("catatan", "")
        )
        return Response(
            {
                "nasabah": NasabahDetailSerializer(
                    nasabah, context=self.get_serializer_context()
                ).data,
                "approval_log": NasabahApprovalLogSerializer(log).data,
            }
        )

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request: Request, pk: str | None = None) -> Response:
        nasabah = self.get_object()
        if nasabah.status != Nasabah.Status.PENDING:
            return Response(
                {"error": "Hanya pengajuan berstatus menunggu yang dapat diproses"}, status=400
            )
        serializer = ApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        log = NasabahApprovalService.reject(
            nasabah, current_user(request), serializer.validated_data.get("catatan", "")
        )
        return Response(
            {
                "nasabah": NasabahDetailSerializer(
                    nasabah, context=self.get_serializer_context()
                ).data,
                "approval_log": NasabahApprovalLogSerializer(log).data,
            }
        )


class SaldoView(APIView):
    permission_classes = [IsActivePengelola]
    serializer_class = SaldoSerializer

    def get(self, request: Request, pk: str) -> Response:
        nasabah = Nasabah.objects.filter(id=pk, bank_sampah=current_bank(request)).first()
        if not nasabah:
            return Response({"error": "Resource tidak ditemukan"}, status=404)
        saldo, _ = Saldo.objects.get_or_create(nasabah=nasabah)
        return Response(SaldoSerializer(saldo).data)
