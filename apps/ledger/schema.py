"""OpenAPI contract for the discriminated, paginated activity feed."""

from drf_spectacular.utils import OpenApiParameter, PolymorphicProxySerializer

from apps.ledger.activity import PERIODS
from apps.ledger.serializers import (
    PencairanActivityEnvelopeSerializer,
    SetoranActivityEnvelopeSerializer,
)

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
