from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import BankSampah, Transaksi, User
from apps.identity.serializers import AuthUserSerializer
from apps.ledger.serializers import TransactionListSerializer
from apps.reporting.services import DashboardService
from shared_kernel.permissions import IsActivePengelola


def _user(request: Request) -> User:
    # ponytail: dup of api.views._user; the close phase extracts one shared
    # request helper once all views have moved.
    assert isinstance(request.user, User)
    return request.user


def _bank_sampah(request: Request) -> BankSampah:
    bank = _user(request).bank_sampah
    assert bank is not None
    return bank


class DashboardStatsView(APIView):
    permission_classes = [IsActivePengelola]
    serializer_class = AuthUserSerializer

    def get(self, request: Request) -> Response:
        return Response(DashboardService.stats(_user(request)))


class DashboardRecentTransactionsView(APIView):
    permission_classes = [IsActivePengelola]
    serializer_class = TransactionListSerializer

    def get(self, request: Request) -> Response:
        qs = (
            Transaksi.objects.filter(bank_sampah=_bank_sampah(request))
            .select_related("nasabah", "dicatat_oleh")
            .prefetch_related("items")
            .order_by("-tanggal")[:3]
        )
        return Response({"transactions": TransactionListSerializer(qs, many=True).data})
