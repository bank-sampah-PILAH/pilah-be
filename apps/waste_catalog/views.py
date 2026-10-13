from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from api.models import BankSampah, JenisSampah
from apps.nasabah.serializers import StatusSerializer
from apps.waste_catalog.api import buat_jenis_sampah, harga_berlaku, ringkas_harga
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


JENIS_PERBANDINGAN_MAKS = 10  # Bandingkan antar-bank itu banding kecil, bukan pasar.


class HargaPerbandinganQuerySerializer(serializers.Serializer):  # type: ignore[type-arg]  # stubs are generic, runtime is not
    """Validates the query of the price-comparison endpoint (PIL-309)."""

    jenis_sampah_id = serializers.UUIDField(required=True)
    bank_ids = serializers.CharField(required=True)

    def validate_bank_ids(self, value: str) -> list[str]:
        ids = [part.strip() for part in value.split(",") if part.strip()]
        if not ids:
            raise serializers.ValidationError("bank_ids wajib diisi")
        if len(ids) > JENIS_PERBANDINGAN_MAKS:
            raise serializers.ValidationError(
                f"Maksimal {JENIS_PERBANDINGAN_MAKS} bank per perbandingan"
            )
        for part in ids:
            try:
                UUID(part)
            except ValueError:
                raise serializers.ValidationError("bank_ids harus berupa UUID dipisah koma") from None
        return ids

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # The jenis must belong to one of the compared banks; comparing a
        # jenis that lives elsewhere would silently price an unknown item.
        if not JenisSampah.objects.filter(
            id=attrs["jenis_sampah_id"],
            bank_sampah_id__in=[UUID(part) for part in attrs["bank_ids"]],
        ).exists():
            raise serializers.ValidationError(
                "jenis_sampah_id tidak ditemukan pada bank yang dibandingkan"
            )
        return attrs


class HargaPerbandinganView(APIView):
    """Compare one waste type's current price across banks (PIL-309).

    The cross-bank anchor is `nomor` (kode): every bank keeps its own
    `JenisSampah` row and shares the item code. A bank without that kode,
    or with it inactive, is reported as `tanpa_jenis`/`jenis_nonaktif` rather
    than silently matched by name. Pending/induk/inactive banks are never
    priced out — the same joinable filter as the directory applies.

    The response is hand-built: 304's serializers only cover one bank's own
    rows, and this envelope mixes bank rows with the jenis echo. Errors are
    422 per the issue contract, not DRF's default 400.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        query = HargaPerbandinganQuerySerializer(data=request.query_params)
        try:
            query.is_valid(raise_exception=True)
        except serializers.ValidationError as exc:
            return Response({"errors": exc.detail}, status=422)
        bank_ids = query.validated_data["bank_ids"]
        jenis_id = query.validated_data["jenis_sampah_id"]

        bank_filter = (
            BankSampah.objects.filter(status=BankSampah.Status.ACTIVE, is_active=True)
            .exclude(jenis_organisasi=BankSampah.OrganizationType.INDUK)
        )
        asal = JenisSampah.objects.select_related("bank_sampah").get(id=jenis_id)
        daftar = list(bank_filter.filter(id__in=bank_ids).order_by("nama"))
        baris: list[dict[str, Any]] = []
        jenis_rows = {
            jenis.bank_sampah_id: jenis
            for jenis in JenisSampah.objects.filter(
                bank_sampah__in=daftar, nomor=asal.nomor, is_active=True
            ).prefetch_related("riwayat_harga")
        }
        baris = []
        for bank_id in bank_ids:
            bank = next((b for b in daftar if str(b.id) == bank_id), None)
            if bank is None:
                # Identity-only lookup so the row still names the bank it
                # refuses to price.
                terlarang = BankSampah.objects.filter(id=bank_id).first()
                baris.append(
                    _baris_kosong(
                        terlarang or BankSampah(nama="", kota=""),
                        "bukan_bank_bisa_gabung",
                    )
                    | {"bank_sampah_id": bank_id}
                )
                continue
            jenis = jenis_rows.get(bank.id)
            if jenis is None:
                # Distinguish: a missing kode row vs an inactive one.
                masih_ada = JenisSampah.objects.filter(
                    bank_sampah=bank, nomor=asal.nomor
                ).exists()
                baris.append(_baris_kosong(bank, "jenis_nonaktif" if masih_ada else "tanpa_jenis"))
                continue
            berlaku, _terjadwal = ringkas_harga(jenis.riwayat_harga.all(), timezone.now())
            if berlaku is None:
                baris.append(_baris_kosong(bank, "belum_ada_harga"))
                continue
            baris.append(
                {
                    "bank_sampah_id": str(bank.id),
                    "nama": bank.nama,
                    "kota": bank.kota,
                    "harga_per_kg": str(berlaku.harga_per_kg),
                    "berlaku_mulai": berlaku.berlaku_mulai.isoformat(),
                    "harga_tidak_tersedia": False,
                    "alasan": None,
                }
            )
        return Response(
            {
                "jenis_sampah": {
                    "id": str(asal.id),
                    "nomor": asal.nomor,
                    "nama_sampah": asal.nama_sampah,
                    "kategori": asal.kategori,
                    "satuan": "kg",
                },
                "perbandingan": baris,
            }
        )


def _baris_kosong(bank: BankSampah, alasan: str) -> dict[str, Any]:
    return {
        "bank_sampah_id": str(bank.id),
        "nama": bank.nama,
        "kota": bank.kota,
        "harga_per_kg": None,
        "berlaku_mulai": None,
        "harga_tidak_tersedia": True,
        "alasan": alasan,
    }
