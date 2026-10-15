import mimetypes
import re
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db.models import Q, QuerySet
from django.http import FileResponse, Http404, HttpRequest
from django.views.decorators.http import require_GET
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import BankSampah, User
from apps.authentication.api import user_state_hint
from apps.bank_sampah.geo import haversine_km
from apps.bank_sampah.serializers import (
    ApprovalDecisionSerializer,
    ApprovalLogSerializer,
    BankSampahApprovalListSerializer,
    BankSampahDetailSerializer,
    BankSampahDirectorySerializer,
    BankSampahRegistrationSerializer,
    BankSampahSerializer,
    InviteAcceptSerializer,
    TeamMemberSerializer,
)
from apps.bank_sampah.services import ApprovalService, BankOnboardingService, TeamService
from shared_kernel.pagination import StandardPagination
from shared_kernel.permissions import (
    IsActivePengelola,
    IsPengelola,
    IsPrimaryPengelola,
    IsSuperAdmin,
)
from shared_kernel.scoping import current_bank, current_user

_PRAFIKS_KOTA = ("kotamadya ", "kabupaten ", "kab. ", "kota ", "kab ")


def normalisasi_kota(teks: str) -> str:
    """Wujud kanonik sebuah nama wilayah untuk pencocokan teks (PIL-329, opsi A).

    Lowercase, spasi dirapikan, dan awalan jalur administratif ("Kota",
    "Kotamadya", "Kab.", "Kabupaten") dilucuti berulang, jadi "Kota Depok",
    "KAB. DEPOK", dan "Depok" bertemu pada satu bentuk. Sisi tersimpan tetap
    dibandingkan dengan `icontains`, jadi varian yang tersimpan ("Kota Depok")
    tetap kena oleh bentuk yang dilucuti.
    """
    bentuk = re.sub(r"\s+", " ", teks.strip().lower())
    sebelum = None
    while sebelum != bentuk:
        sebelum = bentuk
        for prafiks in _PRAFIKS_KOTA:
            if bentuk.startswith(prafiks):
                bentuk = bentuk[len(prafiks) :]
                break
    return bentuk.strip()


@require_GET  # S3752: media is read-only; other methods are caller error.
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


class BankSampahMeView(APIView):
    permission_classes = [IsActivePengelola]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = BankSampahSerializer

    def get(self, request: Request) -> Response:
        return Response(BankSampahSerializer(current_bank(request)).data)

    def put(self, request: Request) -> Response:
        serializer = BankSampahSerializer(current_bank(request), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class SuperAdminBankSampahViewSet(viewsets.GenericViewSet):  # type: ignore[type-arg]  # stubs are generic, runtime is not
    permission_classes = [IsSuperAdmin]
    serializer_class = BankSampahApprovalListSerializer
    queryset = BankSampah.objects.all().order_by("created_at")

    def list(self, request: Request) -> Response:
        status_filter = request.query_params.get("status", BankSampah.Status.PENDING)
        qs = self.get_queryset()
        if status_filter in [
            BankSampah.Status.PENDING,
            BankSampah.Status.ACTIVE,
            BankSampah.Status.REJECTED,
        ]:
            qs = qs.filter(status=status_filter)
        serializer = self.get_serializer(qs, many=True)
        return Response({"count": qs.count(), "results": serializer.data})

    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request: Request, pk: str | None = None) -> Response:
        bank = self.get_object()
        serializer = ApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        log = ApprovalService.approve(
            bank, current_user(request), serializer.validated_data.get("catatan", "")
        )
        return Response(
            {
                "bank_sampah": self.get_serializer(bank).data,
                "approval_log": ApprovalLogSerializer(log).data,
            }
        )

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request: Request, pk: str | None = None) -> Response:
        bank = self.get_object()
        serializer = ApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        log = ApprovalService.reject(
            bank, current_user(request), serializer.validated_data.get("catatan", "")
        )
        return Response(
            {
                "bank_sampah": self.get_serializer(bank).data,
                "approval_log": ApprovalLogSerializer(log).data,
            }
        )


class RegisterBankSampahView(APIView):
    permission_classes = [IsPengelola]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = BankSampahRegistrationSerializer

    def post(self, request: Request) -> Response:
        serializer = BankSampahRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            bank = BankOnboardingService.register_bank_sampah(
                current_user(request), serializer.validated_data
            )
        except PermissionError as exc:
            return Response({"error": str(exc)}, status=403)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        data = BankSampahSerializer(bank).data
        data["next_step"] = user_state_hint(current_user(request))
        return Response(data, status=201)


class AcceptInviteView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = InviteAcceptSerializer

    def post(self, request: Request) -> Response:
        serializer = InviteAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            bank, outcome = BankOnboardingService.accept_invite(
                current_user(request), serializer.validated_data["token"]
            )
        except PermissionError as exc:
            return Response({"error": str(exc)}, status=403)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        data = BankSampahSerializer(bank).data
        data["next_step"] = user_state_hint(current_user(request))
        data["outcome"] = outcome
        data["bank_sampah_id"] = str(bank.id)
        data["bank_sampah_nama"] = bank.nama
        if outcome == "already_member":
            data["message"] = "Anda sudah terdaftar pada bank sampah ini"
        else:
            data["message"] = f"Berhasil bergabung ke Bank Sampah {bank.nama}"
        return Response(data)


class TeamView(APIView):
    permission_classes = [IsActivePengelola]
    serializer_class = TeamMemberSerializer

    def get(self, request: Request) -> Response:
        members = User.objects.filter(
            bank_sampah=current_bank(request), role=User.Role.PENGELOLA, is_active=True
        ).order_by("-is_primary_pengelola", "nama")
        return Response(
            {"members": TeamMemberSerializer(members, many=True, context={"request": request}).data}
        )


class GenerateInviteView(APIView):
    permission_classes = [IsPrimaryPengelola]
    serializer_class = InviteAcceptSerializer

    def post(self, request: Request) -> Response:
        bank = current_bank(request)
        token = TeamService.generate_invite(bank)
        invite_path = f"/invite?{urlencode({'token': token})}"
        base_url = request.build_absolute_uri("/")[:-1]
        public_base = getattr(settings, "PILAH_PUBLIC_APP_URL", "") or base_url
        return Response(
            {
                "token": token,
                "invite_url": f"{public_base}{invite_path}",
                "expires_at": bank.invite_token_expires,
            },
            status=201,
        )


def _joinable_banks() -> QuerySet[BankSampah]:
    """Banks calon nasabah may join, shared by the directory list and detail."""
    return (
        BankSampah.objects.filter(status=BankSampah.Status.ACTIVE, is_active=True)
        .exclude(jenis_organisasi=BankSampah.OrganizationType.INDUK)
        .order_by("nama")
    )


JARAK_MAKSIMAL_KM = 100  # Radius cap: the directory is join-distance, not intercity freight.


class BankSampahLokasiQuerySerializer(serializers.Serializer):  # type: ignore[type-arg]  # stubs are generic, runtime is not
    """Validates the coordinate trio of the directory list (PIL-314).

    All-or-nothing: half a coordinate pair pinpoints nothing, so any
    incomplete combination is rejected rather than silently reduced to a
    keyword search.
    """

    latitude = serializers.FloatField(required=False)
    longitude = serializers.FloatField(required=False)
    radius_km = serializers.FloatField(required=False)
    sort = serializers.CharField(required=False)

    _WILAYAH = {"latitude": (-90, 90), "longitude": (-180, 180)}

    def validate_latitude(self, value: float) -> float:
        if not -90 <= value <= 90:
            raise serializers.ValidationError("Lintang harus di antara -90 dan 90")
        return value

    def validate_longitude(self, value: float) -> float:
        if not -180 <= value <= 180:
            raise serializers.ValidationError("Bujur harus di antara -180 dan 180")
        return value

    def validate_radius_km(self, value: float) -> float:
        if value <= 0 or value > JARAK_MAKSIMAL_KM:
            raise serializers.ValidationError(
                f"Radius harus lebih dari 0 dan maksimal {JARAK_MAKSIMAL_KM} km"
            )
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        hadir = [k for k in ("latitude", "longitude", "radius_km") if k in attrs]
        if hadir and len(hadir) != 3:
            raise serializers.ValidationError(
                "latitude, longitude, dan radius_km dikirim bersamaan atau tidak sama sekali"
            )
        if attrs.get("sort") == "distance" and "radius_km" not in attrs:
            raise serializers.ValidationError("sort=distance membutuhkan koordinat lengkap")
        return attrs


class BankSampahDirectoryView(ListAPIView[BankSampah]):
    """Lists bank sampah a calon nasabah can apply to join.

    Excludes `induk` organizations — they are administrative parents with no
    direct membership of their own; a nasabah joins one of their `unit`
    branches, or a standalone `mandiri` bank sampah, instead.

    `q` searches nama/alamat/kota (PIL-308); `kota` matches the normalized
    region text (PIL-329 option A): prefix variants "Kota"/"Kab." collapse,
    so a stored "Kota Depok" answers both "depok" and "Kota Depok".

    The coordinate trio (latitude/longitude/radius_km) turns the list into a
    distance search (PIL-314): only banks with stored coordinates qualify,
    rows leave the radius circle are dropped, and every row gains a
    `jarak_km` string. Sorting and pagination then happen in Python — the
    full filtered set is sorted once (jarak asc with nama as tie-break, or
    plain nama), and standard page slicing follows, so page 2 is always ranks
    3+ of the full ordering, never a fresh sort of the current page.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = BankSampahDirectorySerializer  # type: ignore[assignment]  # DRF stubs type serializer_class too narrowly
    pagination_class = StandardPagination

    def get_queryset(self) -> QuerySet[BankSampah]:
        qs = _joinable_banks()
        q = (self.request.query_params.get("q") or "").strip()
        # Threshold mirrors JenisSampahViewSet: a single character is noise.
        if len(q) >= 2:
            qs = qs.filter(Q(nama__icontains=q) | Q(alamat__icontains=q) | Q(kota__icontains=q))
        kota = (self.request.query_params.get("kota") or "").strip()
        if kota:
            qs = qs.filter(kota__icontains=normalisasi_kota(kota))
        return qs

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        lokasi = BankSampahLokasiQuerySerializer(data=request.query_params)
        # Issue contract wants 422 for bad filter input, not DRF's default 400.
        try:
            lokasi.is_valid(raise_exception=True)
        except serializers.ValidationError as exc:
            return Response({"errors": exc.detail}, status=422)
        params = lokasi.validated_data
        if params.get("sort") == "distance" or "radius_km" in params:
            return self._list_dengan_jarak(params)
        return super().list(request, *args, **kwargs)

    def _list_dengan_jarak(self, params: dict[str, Any]) -> Response:
        """Distance mode (PIL-314): radius filter, optional distance sort.

        The whole filtered set is scored and sorted once, then paginated, so
        page 2 is always ranks page_size+1.. of the full ordering — never a
        re-sort of just the current page.
        """
        lat, lng = params["latitude"], params["longitude"]
        kunci = (
            (lambda item: (item[1], item[0].nama))
            if params.get("sort") == "distance"
            else (lambda item: item[0].nama)  # location mode without sort stays nama-ordered
        )
        kandidat = sorted(
            (
                (
                    bank,
                    haversine_km(lat, lng, float(str(bank.latitude)), float(str(bank.longitude))),
                )
                for bank in self.get_queryset().filter(
                    latitude__isnull=False, longitude__isnull=False
                )
            ),
            key=kunci,
        )
        if "radius_km" in params:
            kandidat = [(bank, jarak) for bank, jarak in kandidat if jarak <= params["radius_km"]]
        konteks = self.get_serializer_context()
        rows = [
            {
                **BankSampahDirectorySerializer(bank, context=konteks).data,
                "jarak_km": f"{jarak:.2f}",
            }
            for bank, jarak in kandidat
        ]
        paginator = StandardPagination()
        page = paginator.paginate_queryset(rows, self.request, view=self)
        return paginator.get_paginated_response(page)


class BankSampahDetailView(RetrieveAPIView[BankSampah]):
    """Detail of one joinable bank: profile, status, layanan, and coordinates.

    The lookup goes through the same joinable filter as the directory, so a
    pending/rejected/induk bank returns 404 instead of leaking its data.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = BankSampahDetailSerializer  # type: ignore[assignment]  # DRF stubs type serializer_class too narrowly

    def get_queryset(self) -> QuerySet[BankSampah]:
        return _joinable_banks()
