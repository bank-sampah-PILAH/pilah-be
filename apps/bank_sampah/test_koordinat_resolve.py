from decimal import Decimal
from typing import Any
from unittest.mock import patch

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from rest_framework.throttling import ScopedRateThrottle

from api.models import BankSampah, User
from apps.bank_sampah.serializers import BankSampahSerializer
from apps.bank_sampah.views import ResolveKoordinatView

URL = "/api/v1/bank-sampah/resolve-koordinat"
GEOCODER = "apps.bank_sampah.geocoding.requests.get"
TAUTAN_GET = "apps.bank_sampah.tautan.requests.get"

NOMINATIM_RESULT = [
    {
        "lat": "-6.3703237",
        "lon": "106.8270541",
        "display_name": "Fakultas Ilmu Komputer UI, Depok",
    }
]

LINK_PIN = (
    "https://www.google.com/maps/place/Fakultas+Ilmu+Komputer+UI/"
    "@-6.3600000,106.8200000,17z/data=!3m1!4b1!4m6!3m5!1s0x0:0x0"
    "!8m2!3d-6.3703237!4d106.8270541"
)


class _GeocoderResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.payload


class _RedirectResponse:
    def __init__(self, status_code: int = 302, location: str | None = None) -> None:
        self.status_code = status_code
        self.headers = {"Location": location} if location else {}
        self.is_redirect = status_code in (301, 302, 303, 307, 308)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class ResolveKoordinatApiTests(APITestCase):
    def setUp(self) -> None:
        cache.clear()
        self.user = User.objects.create_user(
            email="pengelola@example.test", nama="Pengelola", role=User.Role.PENGELOLA
        )
        self.client.force_authenticate(self.user)

    def _post(self, payload: dict[str, Any]) -> Any:
        return self.client.post(URL, payload, format="json")

    def test_alamat_is_geocoded(self) -> None:
        with patch(GEOCODER, return_value=_GeocoderResponse(NOMINATIM_RESULT)) as get:
            response = self._post(
                {"sumber": "alamat", "alamat": "Jl. Margonda Raya 5", "kota": "Depok"}
            )

        self.assertEqual(response.status_code, 200)  # type: ignore[attr-defined]
        self.assertEqual(response.data["latitude"], -6.3703237)  # type: ignore[attr-defined]
        self.assertEqual(response.data["longitude"], 106.8270541)  # type: ignore[attr-defined]
        self.assertEqual(response.data["sumber"], "geocode")  # type: ignore[attr-defined]
        self.assertEqual(
            response.data["alamat_hasil"],
            "Fakultas Ilmu Komputer UI, Depok",  # type: ignore[attr-defined]
        )
        self.assertIsNone(response.data["akurasi_m"])  # type: ignore[attr-defined]
        self.assertEqual(get.call_args.kwargs["params"]["q"], "Jl. Margonda Raya 5 Depok")
        self.assertTrue(get.call_args.kwargs["headers"]["User-Agent"])

    def test_empty_geocoder_result_is_not_found(self) -> None:
        with patch(GEOCODER, return_value=_GeocoderResponse([])):
            response = self._post({"sumber": "alamat", "alamat": "Jalan Entah"})

        self.assertEqual(response.status_code, 404)  # type: ignore[attr-defined]

    def test_unreachable_geocoder_is_service_unavailable(self) -> None:
        with patch(GEOCODER, side_effect=requests.RequestException("timeout")):
            response = self._post({"sumber": "alamat", "alamat": "Jalan Entah"})

        self.assertEqual(response.status_code, 503)  # type: ignore[attr-defined]

    def test_malformed_bodies_are_rejected(self) -> None:
        bodies = [
            {"alamat": "Jl. Margonda Raya 5"},
            {"sumber": "kantor", "alamat": "Jl. Margonda Raya 5"},
            {"sumber": "alamat"},
            {"sumber": "tautan"},
        ]
        for body in bodies:
            with self.subTest(body=body):
                response = self._post(body)
                self.assertEqual(response.status_code, 400)  # type: ignore[attr-defined]

    def test_link_pin_beats_viewport_centre(self) -> None:
        response = self._post({"sumber": "tautan", "tautan": LINK_PIN})

        self.assertEqual(response.status_code, 200)  # type: ignore[attr-defined]
        self.assertEqual(response.data["latitude"], -6.3703237)  # type: ignore[attr-defined]
        self.assertEqual(response.data["longitude"], 106.8270541)  # type: ignore[attr-defined]
        self.assertEqual(response.data["sumber"], "tautan")  # type: ignore[attr-defined]
        self.assertIsNone(response.data["alamat_hasil"])  # type: ignore[attr-defined]

    def test_link_with_only_viewport_centre_falls_back(self) -> None:
        response = self._post(
            {
                "sumber": "tautan",
                "tautan": "https://www.google.com/maps/@-6.3600000,106.8200000,15z",
            }
        )

        self.assertEqual(response.status_code, 200)  # type: ignore[attr-defined]
        self.assertEqual(response.data["latitude"], -6.36)  # type: ignore[attr-defined]

    def test_link_without_coordinates_is_rejected(self) -> None:
        response = self._post(
            {"sumber": "tautan", "tautan": "https://www.google.com/maps/search/bank+sampah"}
        )

        self.assertEqual(response.status_code, 400)  # type: ignore[attr-defined]

    def test_short_link_redirects_are_followed_manually(self) -> None:
        tujuan = (
            "https://www.google.com/maps/place/Bank+Sampah/"
            "@-6.2000000,106.8000000,17z/data=!3d-6.2100000!4d106.8100000"
        )
        with patch(TAUTAN_GET, return_value=_RedirectResponse(302, tujuan)) as get:
            response = self._post({"sumber": "tautan", "tautan": "https://maps.app.goo.gl/abc123"})

        self.assertEqual(response.status_code, 200)  # type: ignore[attr-defined]
        self.assertEqual(response.data["latitude"], -6.21)  # type: ignore[attr-defined]
        self.assertEqual(response.data["longitude"], 106.81)  # type: ignore[attr-defined]
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_short_link_to_foreign_host_is_rejected(self) -> None:
        with patch(TAUTAN_GET, return_value=_RedirectResponse(302, "https://evil.example/x")):
            response = self._post({"sumber": "tautan", "tautan": "https://maps.app.goo.gl/abc123"})

        self.assertEqual(response.status_code, 400)  # type: ignore[attr-defined]

    def test_short_link_hitting_consent_page_asks_for_the_long_link(self) -> None:
        with patch(
            TAUTAN_GET,
            return_value=_RedirectResponse(302, "https://consent.google.com/m?continue=x"),
        ):
            response = self._post({"sumber": "tautan", "tautan": "https://maps.app.goo.gl/abc123"})

        self.assertEqual(response.status_code, 400)  # type: ignore[attr-defined]
        self.assertIn("panjang", response.data["detail"])  # type: ignore[attr-defined]

    def test_throttle_scope_is_registered(self) -> None:
        self.assertEqual(ResolveKoordinatView.throttle_scope, "resolve_koordinat")
        self.assertIn(ScopedRateThrottle, ResolveKoordinatView.throttle_classes)
        self.assertIn("resolve_koordinat", settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])

    def test_anonymous_request_is_unauthorized(self) -> None:
        self.client.force_authenticate(None)

        response = self._post({"sumber": "alamat", "alamat": "Jl. Margonda Raya 5"})

        self.assertEqual(response.status_code, 401)  # type: ignore[attr-defined]


class BankKoordinatMetadataTests(APITestCase):
    def setUp(self) -> None:
        self.pengelola = User.objects.create_user(
            email="calon@example.test", nama="Calon Pengelola", role=User.Role.PENGELOLA
        )
        self.client.force_authenticate(self.pengelola)

    def test_registration_stores_and_returns_coordinate_provenance(self) -> None:
        response = self.client.post(
            "/api/v1/onboarding/bank-sampah",
            {
                "nama": "Bank Sampah Metadata",
                "alamat": "Jl. Melati No. 10, Depok",
                "kota": "Depok",
                "no_hp_pic": "081234567890",
                "foto_kegiatan": SimpleUploadedFile(
                    "kegiatan.png", b"x" * 16, content_type="image/png"
                ),
                "latitude": "-6.362829",
                "longitude": "106.828655",
                "koordinat_sumber": "gps",
                "koordinat_akurasi_m": "12.50",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)  # type: ignore[attr-defined]
        self.assertEqual(response.data["koordinat_sumber"], "gps")  # type: ignore[attr-defined]
        self.assertEqual(response.data["koordinat_akurasi_m"], "12.50")  # type: ignore[attr-defined]
        bank = BankSampah.objects.get(nama="Bank Sampah Metadata")
        self.assertEqual(bank.koordinat_sumber, "gps")
        self.assertEqual(bank.koordinat_akurasi_m, Decimal("12.50"))

    def test_fields_are_exposed_where_coordinates_are(self) -> None:
        bank = BankSampah.objects.create(
            nama="Bank Sampah Terbaca",
            alamat="Jl. Melati No. 10, Depok",
            kota="Depok",
            no_hp_pic="081234567890",
            koordinat_sumber="tautan",
        )

        # Provenance stays off the public directory; the owner serializer
        # returns it alongside latitude/longitude.
        data = BankSampahSerializer(bank).data
        self.assertEqual(data["koordinat_sumber"], "tautan")
        self.assertIsNone(data["koordinat_akurasi_m"])
