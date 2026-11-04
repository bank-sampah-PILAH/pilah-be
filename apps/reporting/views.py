from datetime import date
from typing import Any, TypedDict, cast

from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Transaksi
from apps.authentication.serializers import AuthUserSerializer
from apps.ledger.serializers import TransactionListSerializer
from apps.reporting.services import DashboardService
from shared_kernel.permissions import IsActivePengelola
from shared_kernel.scoping import current_bank, current_user


class ReportingPeriodData(TypedDict):
    start_date: date
    end_date: date


class OperationalTrendsData(ReportingPeriodData):
    granularity: str


class ReportingPeriodSerializer(serializers.Serializer[Any]):
    start_date = serializers.DateField(required=True)
    end_date = serializers.DateField(required=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        start_date: date = attrs["start_date"]
        end_date: date = attrs["end_date"]
        if start_date > end_date:
            raise serializers.ValidationError({"end_date": "Must be on or after start_date."})
        return attrs


class OperationalTrendsQuerySerializer(ReportingPeriodSerializer):
    granularity = serializers.ChoiceField(choices=("day", "week", "month"), required=True)


class DashboardOperationalTrendsView(APIView):
    permission_classes = [IsActivePengelola]
    serializer_class = OperationalTrendsQuerySerializer

    def get(self, request: Request) -> Response:
        serializer = OperationalTrendsQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        data = cast(OperationalTrendsData, serializer.validated_data)
        return Response(
            DashboardService.operational_trends(
                current_user(request), data["start_date"], data["end_date"], data["granularity"]
            )
        )


class DashboardWasteCategoriesView(APIView):
    permission_classes = [IsActivePengelola]
    serializer_class = ReportingPeriodSerializer

    def get(self, request: Request) -> Response:
        serializer = ReportingPeriodSerializer(data=request.query_params)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        data = cast(ReportingPeriodData, serializer.validated_data)
        return Response(
            DashboardService.waste_categories(
                current_user(request), data["start_date"], data["end_date"]
            )
        )


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
            .select_related("nasabah", "dicatat_oleh", "dibatalkan_oleh")
            .prefetch_related("items")
            .order_by("-tanggal")[:3]
        )
        return Response({"transactions": TransactionListSerializer(qs, many=True).data})
