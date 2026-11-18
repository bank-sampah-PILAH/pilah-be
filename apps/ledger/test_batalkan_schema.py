"""OpenAPI contract for voiding a setoran (PIL-428).

Review on #145 (Rifqi, P2): the schema described the 200 response with the
request's shape, {alasan}, while the endpoint answers with the setoran detail.
"""

from typing import Any

from django.test import SimpleTestCase
from django.urls import path
from drf_spectacular.generators import SchemaGenerator

from apps.ledger.views import TransaksiViewSet


class BatalkanSchemaTests(SimpleTestCase):
    def _operation(self) -> tuple[dict[str, Any], dict[str, Any]]:
        schema = SchemaGenerator(  # type: ignore[no-untyped-call]  # drf-spectacular has no typed generator API
            patterns=[
                path(
                    "api/v1/transaksi/<uuid:pk>/batalkan",
                    TransaksiViewSet.as_view({"post": "batalkan"}),
                )
            ]
        ).get_schema(public=True)
        assert schema is not None
        return schema["paths"]["/api/v1/transaksi/{id}/batalkan"]["post"], schema

    def test_the_request_is_the_alasan_and_the_200_is_the_setoran_detail(self) -> None:
        operation, _ = self._operation()

        request = operation["requestBody"]["content"]["application/json"]["schema"]
        response = operation["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertEqual(request["$ref"], "#/components/schemas/TransactionBatal")
        self.assertEqual(response["$ref"], "#/components/schemas/TransactionDetail")

    def test_the_refusals_are_documented(self) -> None:
        operation, _ = self._operation()

        for code in ("404", "409", "422"):
            with self.subTest(code=code):
                self.assertIn(code, operation["responses"])
                self.assertTrue(operation["responses"][code]["description"])
