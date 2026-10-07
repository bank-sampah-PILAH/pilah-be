import hashlib
import json
from typing import Any
from uuid import UUID

from django.db import IntegrityError
from django.db.models import Prefetch, QuerySet
from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from api.models import BankSampah, DraftPencairan, DraftPencairanItem, Pencairan, Transaksi, User
from apps.ledger.serializers import (
    DraftBatchSerializer,
    DraftKandidatQuerySerializer,
    DraftKandidatSerializer,
    DraftPencairanCreateSerializer,
    DraftPencairanListSerializer,
    DraftPencairanSerializer,
    DraftPencairanUpdateSerializer,
    PencairanCreateSerializer,
    PencairanDetailSerializer,
    PencairanEditSerializer,
    PencairanRevisiSerializer,
    TransactionCreateSerializer,
    TransactionDetailSerializer,
    TransactionListSerializer,
)
from apps.ledger.services import (
    DraftPencairanService,
    DraftTidakBisaDiubah,
    PencairanService,
    TransactionFilterService,
    TransactionService,
)
from apps.nasabah.api import kandidat_pencairan
from apps.notification.api import send_setoran_receipt
from apps.reporting.api import export_excel
from shared_kernel.permissions import (
    IsActivePengelola,
    IsActivePengelolaOrNasabah,
)
from shared_kernel.scoping import current_bank, current_user


def _user(request: Request) -> Any:
    assert isinstance(request.user, object)  # ponytail: DRF authentication rejects AnonymousUser
    return request.user


def _bank_sampah(request: Request) -> BankSampah:
    bank = request.user.bank_sampah  # type: ignore[union-attr]
    assert bank is not None  # ponytail: IsActivePengelola guarantees bank membership
    return bank


def _idempotency_key(request: Request) -> UUID | None:
    raw_key = request.headers.get("Idempotency-Key")
    if raw_key is None:
        return None
    try:
        key = UUID(raw_key)
    except ValueError:
        raise ParseError("Idempotency-Key harus berupa UUID v4") from None
    if key.version != 4 or str(key) != raw_key.lower():
        raise ParseError("Idempotency-Key harus berupa UUID v4")
    return key


def _transaction_payload_hash(payload: dict[str, Any]) -> str:
    canonical_payload = {
        "nasabah_id": str(payload["nasabah_id"]),
        "items": [
            {
                "jenis_sampah_id": str(item["jenis_sampah_id"]),
                "berat": format(item["berat"], "f"),
            }
            for item in payload["items"]
        ],
        "catatan": payload.get("catatan"),
    }
    canonical_json = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode()).hexdigest()


def _find_idempotent_transaction(bank: BankSampah, key: UUID) -> Transaksi | None:
    return Transaksi.objects.filter(bank_sampah=bank, idempotency_key=key).first()


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
            Transaksi.objects.filter(bank_sampah=current_bank(self.request))
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
        content, filename = export_excel(qs, request)
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def create(self, request: Request) -> Response:
        serializer = TransactionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            idempotency_key = _idempotency_key(request)
        except ParseError as exc:
            return Response({"error": exc.detail}, status=status.HTTP_400_BAD_REQUEST)
        payload = serializer.validated_data
        # "" — not None: the column is NOT NULL (S6553 fix); only rows with a
        # real key carry a digest, and replay compares digests only then.
        payload_hash = _transaction_payload_hash(payload) if idempotency_key else ""
        bank = _bank_sampah(request)

        def replay(existing: Transaksi) -> Response:
            if existing.idempotency_request_hash != payload_hash:
                return Response(
                    {"error": "Idempotency-Key sudah digunakan untuk data setoran berbeda"},
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(TransactionDetailSerializer(existing).data, status=status.HTTP_200_OK)

        if idempotency_key:
            existing = _find_idempotent_transaction(bank, idempotency_key)
            if existing:
                return replay(existing)

        try:
            transaksi = TransactionService.create_setoran(
                current_user(request),
                payload,
                idempotency_key=idempotency_key,
                idempotency_request_hash=payload_hash,
            )
        except IntegrityError:
            if idempotency_key is None:
                raise
            existing = _find_idempotent_transaction(bank, idempotency_key)
            if existing is None:
                raise
            return replay(existing)
        return Response(TransactionDetailSerializer(transaksi).data, status=status.HTTP_201_CREATED)

    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        transaksi = self.get_object()
        return Response(TransactionDetailSerializer(transaksi).data)

    @action(detail=True, methods=["post"], url_path="notify-wa")
    def notify_wa(self, request: Request, pk: str | None = None) -> Response:
        transaksi = self.get_object()
        result = send_setoran_receipt(transaksi)
        return Response(result, status=200 if result["success"] else 400)


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


class DraftPencairanViewSet(viewsets.GenericViewSet):  # type: ignore[type-arg]  # stubs are generic, runtime is not
    permission_classes = [IsActivePengelola]
    serializer_class = DraftPencairanSerializer

    def get_queryset(self) -> QuerySet[DraftPencairan]:
        return DraftPencairan.objects.filter(
            bank_sampah=current_bank(self.request)
        ).prefetch_related(
            Prefetch(
                "items",
                queryset=DraftPencairanItem.objects.select_related("nasabah", "nasabah__saldo"),
            )
        )

    def list(self, request: Request) -> Response:
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(DraftPencairanListSerializer(page, many=True).data)

    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        return Response(DraftPencairanSerializer(self.get_object()).data)

    def create(self, request: Request) -> Response:
        serializer = DraftPencairanCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        draft = DraftPencairanService.buat_draft(_user(request), serializer.validated_data)
        return Response(DraftPencairanSerializer(draft).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, pk: str | None = None) -> Response:
        draft = self.get_object()
        serializer = DraftPencairanUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            DraftPencairanService.ubah_draft(_user(request), draft, serializer.validated_data)
        except DraftTidakBisaDiubah as exc:
            return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(DraftPencairanSerializer(self.get_queryset().get(pk=draft.pk)).data)

    @action(detail=True, methods=["post"], url_path="batalkan")
    def batalkan(self, request: Request, pk: str | None = None) -> Response:
        draft = self.get_object()
        try:
            DraftPencairanService.batalkan_draft(_user(request), draft)
        except DraftTidakBisaDiubah as exc:
            return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(DraftPencairanSerializer(self.get_queryset().get(pk=draft.pk)).data)

    @action(detail=False, methods=["get"], url_path="kandidat")
    def kandidat(self, request: Request) -> Response:
        """Everyone a draft could pay out, unpaginated, so the picker can select across pages."""
        query = DraftKandidatQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        nasabah = kandidat_pencairan(current_bank(request), **query.validated_data)
        return Response(DraftKandidatSerializer(nasabah, many=True).data)

    @action(detail=False, methods=["post"], url_path="batch")
    def batch(self, request: Request) -> Response:
        serializer = DraftBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        draft, dilewati = DraftPencairanService.buat_batch(
            _user(request), serializer.validated_data
        )
        data = DraftPencairanSerializer(self.get_queryset().get(pk=draft.pk)).data
        return Response({**data, "dilewati": dilewati}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="konfirmasi")
    def konfirmasi(self, request: Request, pk: str | None = None) -> Response:
        draft = self.get_object()
        try:
            DraftPencairanService.konfirmasi_draft(_user(request), draft)
        except DraftTidakBisaDiubah as exc:
            return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(DraftPencairanSerializer(self.get_queryset().get(pk=draft.pk)).data)
