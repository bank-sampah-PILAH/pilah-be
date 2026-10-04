import mimetypes
from urllib.parse import urlencode

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import FileResponse, Http404, HttpRequest
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import BankSampah, User
from apps.authentication.api import user_state_hint
from apps.bank_sampah.serializers import (
    ApprovalDecisionSerializer,
    ApprovalLogSerializer,
    BankSampahApprovalListSerializer,
    BankSampahDirectorySerializer,
    BankSampahRegistrationSerializer,
    BankSampahSerializer,
    InviteAcceptSerializer,
    TeamMemberSerializer,
)
from apps.bank_sampah.services import ApprovalService, BankOnboardingService, TeamService
from shared_kernel.permissions import (
    IsActivePengelola,
    IsPengelola,
    IsPrimaryPengelola,
    IsSuperAdmin,
)
from shared_kernel.scoping import current_bank, current_user


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
