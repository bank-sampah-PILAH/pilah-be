"""OpenAPI contract for the discriminated, paginated activity feed."""

from typing import Any

from drf_spectacular.utils import OpenApiParameter, PolymorphicProxySerializer

from apps.ledger.activity import PERIODS
from apps.ledger.serializers import (
    PencairanActivityEnvelopeSerializer,
    SetoranActivityEnvelopeSerializer,
)
from shared_kernel.pagination import StandardPagination


class ActivityPagination(StandardPagination):
    def get_paginated_response_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = super().get_paginated_response_schema(schema)
        properties = {
            "jumlah_transaksi": {"type": "integer", "minimum": 0},
            "total_berat": {"type": "string", "example": "3.500"},
            "total_setoran": {"type": "integer", "minimum": 0},
            "total_pencairan": {"type": "integer", "minimum": 0},
            "saldo": {
                "type": "integer",
                "description": "Filtered deposits minus withdrawals, in Rupiah.",
            },
        }
        result["properties"]["summary"] = {
            "type": "object",
            "properties": properties,
            "required": list(properties),
        }
        result["required"].append("summary")
        return result


ACTIVITY_RESPONSE = PolymorphicProxySerializer(
    component_name="ActivityEnvelope",
    serializers={
        "setoran": SetoranActivityEnvelopeSerializer,
        "pencairan": PencairanActivityEnvelopeSerializer,
    },
    resource_type_field_name="tipe",
    many=True,
)
ACTIVITY_PARAMETERS = [
    OpenApiParameter("periode", str, enum=sorted(PERIODS), default="semua"),
    OpenApiParameter("tipe", str, enum=["semua", "setoran", "pencairan"], default="semua"),
    OpenApiParameter("search", str, description="Nama nasabah; filtered before pagination."),
    OpenApiParameter(
        "dari_tanggal", str, description="Inclusive local date (YYYY-MM-DD), required for custom."
    ),
    OpenApiParameter(
        "sampai_tanggal", str, description="Inclusive local date (YYYY-MM-DD), required for custom."
    ),
]
