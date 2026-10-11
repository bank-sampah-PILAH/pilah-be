from django.test import SimpleTestCase
from django.urls import path
from drf_spectacular.generators import SchemaGenerator

from apps.ledger.views import ActivityHistoryView


class ActivitySchemaTests(SimpleTestCase):
    def test_paginated_schema_describes_discriminated_envelopes(self) -> None:
        schema = SchemaGenerator(patterns=[path("api/v1/aktivitas", ActivityHistoryView.as_view())]).get_schema(public=True)
        assert schema is not None
        components = schema["components"]["schemas"]
        self.assertIn("ActivityEnvelope", components)
        envelope = components["ActivityEnvelope"]
        self.assertEqual(envelope["discriminator"]["propertyName"], "tipe")
        self.assertEqual(set(envelope["discriminator"]["mapping"]), {"setoran", "pencairan"})
        response = schema["paths"]["/api/v1/aktivitas"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        page = components[response["$ref"].split("/")[-1]]
        self.assertEqual(page["properties"]["results"]["items"]["$ref"], "#/components/schemas/ActivityEnvelope")
        for ref in envelope["discriminator"]["mapping"].values():
            self.assertEqual(set(components[ref.split("/")[-1]]["properties"]), {"tipe", "data"})
