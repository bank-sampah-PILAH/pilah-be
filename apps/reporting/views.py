from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Transaksi
from apps.identity.serializers import AuthUserSerializer
from apps.ledger.serializers import TransactionListSerializer
from apps.reporting.services import DashboardService
from shared_kernel.permissions import IsActivePengelola
from shared_kernel.scoping import current_bank, current_user


class DashboardStatsView(APIView):
    permission_classes = [IsActivePengelola]
    serializer_class = AuthUserSerializer

    def get(self, request: Request) -> Response:
        return Response(DashboardService.stats(current_user(request)))


class DashboardRecentTransactionsView(APIView):
    permission_classes = [IsActivePengelola]
    serializer_class = TransactionListSerializer

    def get(self, request: Request) -> Response:
        qs = (
            Transaksi.objects.filter(bank_sampah=current_bank(request))
            .select_related("nasabah", "dicatat_oleh")
            .prefetch_related("items")
            .order_by("-tanggal")[:3]
        )
        return Response({"transactions": TransactionListSerializer(qs, many=True).data})
