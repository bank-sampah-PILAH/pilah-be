from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import BankSampah, User
from apps.organization.serializers import (
    ApprovalDecisionSerializer,
    ApprovalLogSerializer,
    BankSampahApprovalListSerializer,
    BankSampahSerializer,
)
from apps.organization.services import ApprovalService
from shared_kernel.permissions import IsActivePengelola, IsSuperAdmin


def _user(request: Request) -> User:
    # ponytail: dup of api.views._user; the close phase extracts one shared
    # request helper once all views have moved.
    assert isinstance(request.user, User)
    return request.user


def _bank_sampah(request: Request) -> BankSampah:
    bank = _user(request).bank_sampah
    assert bank is not None
    return bank


class BankSampahMeView(APIView):
    permission_classes = [IsActivePengelola]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = BankSampahSerializer

    def get(self, request: Request) -> Response:
        return Response(BankSampahSerializer(_bank_sampah(request)).data)

    def put(self, request: Request) -> Response:
        serializer = BankSampahSerializer(_bank_sampah(request), data=request.data, partial=True)
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
            bank, _user(request), serializer.validated_data.get("catatan", "")
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
            bank, _user(request), serializer.validated_data.get("catatan", "")
        )
        return Response(
            {
                "bank_sampah": self.get_serializer(bank).data,
                "approval_log": ApprovalLogSerializer(log).data,
            }
        )
