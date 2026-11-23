import threading
import time
from decimal import Decimal
from typing import Any, cast
from unittest.mock import patch

import requests
from django.conf import settings
from django.core.cache import cache, caches
from django.core.cache.backends.locmem import LocMemCache
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from rest_framework.throttling import ScopedRateThrottle

from api.models import BankSampah, User
from apps.bank_sampah import geocoding
from apps.bank_sampah.geocoding import cari_tempat
from apps.bank_sampah.serializers import BankSampahSerializer
from apps.bank_sampah.views import ResolveKoordinatView

URL = "/api/v1/bank-sampah/resolve-koordinat"
CARI_TEMPAT_URL = "/api/v1/bank-sampah/cari-tempat"
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


def _bersihkan_cache() -> None:
    cache.clear()
    caches["auth_rate_limit"].clear()


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
        _bersihkan_cache()
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

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["latitude"], -6.3703237)
        self.assertEqual(response.data["longitude"], 106.8270541)
        self.assertEqual(response.data["sumber"], "geocode")
        self.assertEqual(
            response.data["alamat_hasil"],
            "Fakultas Ilmu Komputer UI, Depok",
        )
        self.assertIsNone(response.data["akurasi_m"])
        self.assertEqual(get.call_args.kwargs["params"]["q"], "Jl. Margonda Raya 5 Depok")
        self.assertTrue(get.call_args.kwargs["headers"]["User-Agent"])

    def test_empty_geocoder_result_is_not_found(self) -> None:
        with patch(GEOCODER, return_value=_GeocoderResponse([])):
            response = self._post({"sumber": "alamat", "alamat": "Jalan Entah"})

        self.assertEqual(response.status_code, 404)

    def test_unreachable_geocoder_is_service_unavailable(self) -> None:
        with patch(GEOCODER, side_effect=requests.RequestException("timeout")):
            response = self._post({"sumber": "alamat", "alamat": "Jalan Entah"})

        self.assertEqual(response.status_code, 503)

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
                self.assertEqual(response.status_code, 400)

    def test_link_pin_beats_viewport_centre(self) -> None:
        response = self._post({"sumber": "tautan", "tautan": LINK_PIN})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["latitude"], -6.3703237)
        self.assertEqual(response.data["longitude"], 106.8270541)
        self.assertEqual(response.data["sumber"], "tautan")
        self.assertIsNone(response.data["alamat_hasil"])
        # A real place pin carries no invented accuracy.
        self.assertIsNone(response.data["akurasi_m"])

    def test_link_with_only_viewport_centre_falls_back(self) -> None:
        response = self._post(
            {
                "sumber": "tautan",
                "tautan": "https://www.google.com/maps/@-6.3600000,106.8200000,15z",
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["latitude"], -6.36)
        # A viewport centre drifts from the shared pin, so it says so.
        self.assertEqual(response.data["akurasi_m"], 1000.0)

    def test_link_without_coordinates_is_rejected(self) -> None:
        response = self._post(
            {"sumber": "tautan", "tautan": "https://www.google.com/maps/search/bank+sampah"}
        )

        self.assertEqual(response.status_code, 400)

    def test_link_with_coordinate_query_parameter_is_parsed(self) -> None:
        response = self._post(
            {"sumber": "tautan", "tautan": "https://www.google.com/maps?q=-6.2,106.8"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["latitude"], -6.2)
        self.assertEqual(response.data["longitude"], 106.8)

    def test_link_with_place_coordinate_path_is_parsed(self) -> None:
        response = self._post(
            {"sumber": "tautan", "tautan": "https://www.google.com/maps/place/-6.2,106.8"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["latitude"], -6.2)

    def test_malformed_geocoder_payloads_are_not_found(self) -> None:
        payloads = [
            [{"lon": "106.8270541"}],
            [{"lat": "bukan-angka", "lon": "106.8270541"}],
            "bukan-daftar",
            [{"lat": "100", "lon": "106.8270541"}],
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                with patch(GEOCODER, return_value=_GeocoderResponse(payload)):
                    response = self._post({"sumber": "alamat", "alamat": "Jalan Entah"})
                self.assertEqual(response.status_code, 404)

    def test_short_link_redirects_are_followed_manually(self) -> None:
        tujuan = (
            "https://www.google.com/maps/place/Bank+Sampah/"
            "@-6.2000000,106.8000000,17z/data=!3d-6.2100000!4d106.8100000"
        )
        with patch(TAUTAN_GET, return_value=_RedirectResponse(302, tujuan)) as get:
            response = self._post({"sumber": "tautan", "tautan": "https://maps.app.goo.gl/abc123"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["latitude"], -6.21)
        self.assertEqual(response.data["longitude"], 106.81)
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        # The whole chain gets one short budget, far inside gunicorn's kill.
        self.assertLessEqual(get.call_args.kwargs["timeout"], 3)

    def test_short_link_to_foreign_host_is_rejected(self) -> None:
        with patch(TAUTAN_GET, return_value=_RedirectResponse(302, "https://evil.example/x")):
            response = self._post({"sumber": "tautan", "tautan": "https://maps.app.goo.gl/abc123"})

        self.assertEqual(response.status_code, 400)

    def test_short_link_hitting_consent_page_asks_for_the_long_link(self) -> None:
        with patch(
            TAUTAN_GET,
            return_value=_RedirectResponse(302, "https://consent.google.com/m?continue=x"),
        ):
            response = self._post({"sumber": "tautan", "tautan": "https://maps.app.goo.gl/abc123"})

        self.assertEqual(response.status_code, 400)
        detail = str(response.data["detail"])
        self.assertIn("panjang", detail)

    def test_short_link_upstream_failure_is_service_unavailable(self) -> None:
        with patch(TAUTAN_GET, side_effect=requests.RequestException("timeout")):
            response = self._post({"sumber": "tautan", "tautan": "https://maps.app.goo.gl/abc123"})

        self.assertEqual(response.status_code, 503)

    def test_short_link_that_does_not_redirect_is_parsed_as_is(self) -> None:
        with patch(TAUTAN_GET, return_value=_RedirectResponse(200)):
            response = self._post({"sumber": "tautan", "tautan": "https://maps.app.goo.gl/abc123"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("koordinat", str(response.data["detail"]))

    def test_short_link_redirect_without_location_is_rejected(self) -> None:
        with patch(TAUTAN_GET, return_value=_RedirectResponse(302)):
            response = self._post({"sumber": "tautan", "tautan": "https://maps.app.goo.gl/abc123"})

        self.assertEqual(response.status_code, 400)

    def test_short_link_redirect_loop_is_rejected(self) -> None:
        lompatan = [_RedirectResponse(302, "https://maps.app.goo.gl/abc123") for _ in range(5)]
        with patch(TAUTAN_GET, side_effect=lompatan):
            response = self._post({"sumber": "tautan", "tautan": "https://maps.app.goo.gl/abc123"})

        self.assertEqual(response.status_code, 400)

    def test_throttle_scope_is_registered(self) -> None:
        self.assertEqual(ResolveKoordinatView.throttle_scope, "resolve_koordinat")
        self.assertIn(ScopedRateThrottle, ResolveKoordinatView.throttle_classes)
        rates = cast("dict[str, str]", settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])
        self.assertIn("resolve_koordinat", rates)

    def test_anonymous_request_is_unauthorized(self) -> None:
        self.client.force_authenticate(None)

        response = self._post({"sumber": "alamat", "alamat": "Jl. Margonda Raya 5"})

        self.assertEqual(response.status_code, 401)


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

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["koordinat_sumber"], "gps")
        self.assertEqual(response.data["koordinat_akurasi_m"], "12.50")
        bank = BankSampah.objects.get(nama="Bank Sampah Metadata")
        self.assertEqual(bank.koordinat_sumber, "gps")
        self.assertEqual(bank.koordinat_akurasi_m, Decimal("12.50"))

    def test_unknown_coordinate_source_is_rejected(self) -> None:
        # The vocabulary is part of the contract; a typo must not reach the
        # table and quietly poison the re-check list later.
        response = self.client.post(
            "/api/v1/onboarding/bank-sampah",
            {
                "nama": "Bank Sampah Sumber Aneh",
                "alamat": "Jl. Melati No. 10, Depok",
                "no_hp_pic": "081234567890",
                "foto_kegiatan": SimpleUploadedFile(
                    "kegiatan.png", b"x" * 16, content_type="image/png"
                ),
                "latitude": "-6.362829",
                "longitude": "106.828655",
                "koordinat_sumber": "telepati",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("koordinat_sumber", response.data["errors"])

    def test_negative_accuracy_is_rejected(self) -> None:
        response = self.client.post(
            "/api/v1/onboarding/bank-sampah",
            {
                "nama": "Bank Sampah Akurasi Negatif",
                "alamat": "Jl. Melati No. 10, Depok",
                "kota": "Depok",
                "no_hp_pic": "081234567890",
                "foto_kegiatan": SimpleUploadedFile(
                    "kegiatan.png", b"x" * 16, content_type="image/png"
                ),
                "latitude": "-6.362829",
                "longitude": "106.828655",
                "koordinat_sumber": "gps",
                "koordinat_akurasi_m": "-1.00",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("koordinat_akurasi_m", response.data["errors"])

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


class CariTempatApiTests(APITestCase):
    def setUp(self) -> None:
        _bersihkan_cache()
        self.user = User.objects.create_user(
            email="nasabah@pencari.test", nama="Pencari", role=User.Role.NASABAH
        )
        self.client.force_authenticate(self.user)

    def test_place_search_returns_shaped_results(self) -> None:
        with patch(GEOCODER, return_value=_GeocoderResponse(NOMINATIM_RESULT)) as get:
            response = self.client.get(CARI_TEMPAT_URL, {"q": "kampus ui"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["hasil"],
            [
                {
                    "nama": "Fakultas Ilmu Komputer UI, Depok",
                    "latitude": -6.3703237,
                    "longitude": 106.8270541,
                }
            ],
        )
        self.assertEqual(get.call_args.kwargs["params"]["limit"], "5")

    def test_result_without_display_name_falls_back_to_coordinates(self) -> None:
        with patch(GEOCODER, return_value=_GeocoderResponse([{"lat": "-6.2", "lon": "106.8"}])):
            response = self.client.get(CARI_TEMPAT_URL, {"q": "tanpa nama"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["hasil"][0]["nama"], "-6.2, 106.8")

    def test_short_query_is_rejected_without_a_geocoder_call(self) -> None:
        with patch(GEOCODER) as get:
            response = self.client.get(CARI_TEMPAT_URL, {"q": "ui"})

        self.assertEqual(response.status_code, 400)
        get.assert_not_called()

    def test_unreachable_geocoder_is_service_unavailable(self) -> None:
        with patch(GEOCODER, side_effect=requests.RequestException("timeout")):
            response = self.client.get(CARI_TEMPAT_URL, {"q": "kampus ui"})

        self.assertEqual(response.status_code, 503)

    def test_repeated_queries_share_one_outbound_call(self) -> None:
        with patch(GEOCODER, return_value=_GeocoderResponse(NOMINATIM_RESULT)) as get:
            pertama = self.client.get(CARI_TEMPAT_URL, {"q": "Jl. Margonda Raya 5 Depok"})
            kedua = self.client.get(CARI_TEMPAT_URL, {"q": "  jl.  MARGONDA raya 5 depok "})

        self.assertEqual(pertama.status_code, 200)
        self.assertEqual(kedua.status_code, 200)
        self.assertEqual(kedua.data, pertama.data)
        self.assertEqual(get.call_count, 1)

    def test_outbound_calls_are_serialized_by_the_shared_limit(self) -> None:
        waktu: list[float] = []

        def fake_get(*args: Any, **kwargs: Any) -> _GeocoderResponse:
            waktu.append(time.monotonic())
            return _GeocoderResponse(NOMINATIM_RESULT)

        query = ["kota bandung", "kota surabaya"]
        # Threads and the sqlite-backed shared cache don't mix; the limit is
        # what this test is about, so give it an in-memory cache.
        with (
            patch(GEOCODER, side_effect=fake_get),
            patch.object(geocoding, "MIN_INTERVAL_DETIK", 0.15),
            patch.object(geocoding, "_panggilan_terakhir", 0.0),
            patch.object(geocoding, "_cache", LocMemCache("uji-geocode", {})),
        ):
            threads = [threading.Thread(target=cari_tempat, args=(kueri,)) for kueri in query]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(len(waktu), 2)
        # The second call waited out the provider's one-per-second slot
        # instead of racing the first one.
        self.assertGreaterEqual(waktu[1] - waktu[0], 0.15)
