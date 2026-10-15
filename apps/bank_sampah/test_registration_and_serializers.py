from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework import serializers
from rest_framework.test import APITestCase

from api.models import BankSampah, HargaSampah, JenisSampah, User
from apps.bank_sampah.geo import haversine_km
from apps.bank_sampah.serializers import (
    BankSampahApprovalListSerializer,
    BankSampahDirectorySerializer,
    BankSampahRegistrationSerializer,
    BankSampahSerializer,
)
from apps.bank_sampah.services import BankOnboardingService
from apps.bank_sampah.views import normalisasi_kota

REGISTRATION = {
    "nama": "Bank Sampah Baru",
    "alamat": "Jl. Melati No. 10, Depok",
    "kota": "Depok",
    "no_hp_pic": "081234567890",
}


def _photo(name: str = "kegiatan.png", size: int = 16) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"x" * size, content_type="image/png")


class BankRegistrationApiTests(APITestCase):
    def setUp(self) -> None:
        self.pengelola = User.objects.create_user(
            email="calon@example.test", nama="Calon Pengelola", role=User.Role.PENGELOLA
        )
        self.client.force_authenticate(self.pengelola)
        self.url = "/api/v1/onboarding/bank-sampah"

    def _post(self, photo: SimpleUploadedFile) -> object:
        return self.client.post(
            self.url, {**REGISTRATION, "foto_kegiatan": photo}, format="multipart"
        )

    def test_activity_photo_must_be_jpg_jpeg_or_png(self) -> None:
        response = self._post(_photo("kegiatan.gif"))

        self.assertEqual(response.status_code, 422)  # type: ignore[attr-defined]
        self.assertEqual(
            response.data["errors"]["foto_kegiatan"],  # type: ignore[attr-defined]
            ["Foto kegiatan harus berformat JPG, JPEG, atau PNG"],
        )

    def test_activity_photo_is_capped_at_five_megabytes(self) -> None:
        response = self._post(_photo(size=5 * 1024 * 1024 + 1))

        self.assertEqual(response.status_code, 422)  # type: ignore[attr-defined]
        self.assertEqual(
            response.data["errors"]["foto_kegiatan"],  # type: ignore[attr-defined]
            ["Ukuran foto kegiatan maksimal 5 MB"],
        )

    def test_already_active_bank_cannot_register_again(self) -> None:
        bank = BankSampah.objects.create(nama="Bank Aktif", alamat="x", kota="Depok")
        self.pengelola.bank_sampah = bank
        self.pengelola.save()

        response = self._post(_photo())

        self.assertEqual(response.status_code, 400)  # type: ignore[attr-defined]
        self.assertEqual(response.data, {"error": "Bank sampah sudah aktif"})  # type: ignore[attr-defined]

    def test_permission_error_from_onboarding_is_reported_as_forbidden(self) -> None:
        # IsPengelola already screens the role, so this mapping is a second
        # line of defence; drive it through the service seam.
        with patch.object(
            BankOnboardingService, "register_bank_sampah", side_effect=PermissionError("ditolak")
        ):
            response = self._post(_photo())

        self.assertEqual(response.status_code, 403)  # type: ignore[attr-defined]
        self.assertEqual(response.data, {"error": "ditolak"})  # type: ignore[attr-defined]


class BankCoordinateApiTests(APITestCase):
    # Registration and the pengelola profile both carry coordinates now; the
    # range rules live on the serializers, the storage on the model.
    def setUp(self) -> None:
        self.pengelola = User.objects.create_user(
            email="petani@example.test", nama="Ibu Petani", role=User.Role.PENGELOLA
        )
        self.client.force_authenticate(self.pengelola)

    @staticmethod
    def _make_pengelola(email: str, bank: BankSampah) -> User:
        return User.objects.create_user(
            email=email,
            nama="Pengelola " + bank.nama,
            role=User.Role.PENGELOLA,
            bank_sampah=bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )

    def test_registration_accepts_coordinates(self) -> None:
        self.client.force_authenticate(self.pengelola)
        response = self.client.post(
            "/api/v1/onboarding/bank-sampah",
            {
                **REGISTRATION,
                "latitude": "-6.362829",
                "longitude": "106.828655",
                "foto_kegiatan": _photo(),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        bank = BankSampah.objects.get(nama="Bank Sampah Baru")
        self.assertEqual(bank.latitude, Decimal("-6.362829"))
        self.assertEqual(bank.longitude, Decimal("106.828655"))

    def test_registration_without_coordinates_stores_null(self) -> None:
        self.client.force_authenticate(self.pengelola)
        response = self.client.post(
            "/api/v1/onboarding/bank-sampah",
            {**REGISTRATION, "foto_kegiatan": _photo()},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        bank = BankSampah.objects.get(nama="Bank Sampah Baru")
        self.assertIsNone(bank.latitude)
        self.assertIsNone(bank.longitude)

    def test_registration_rejects_out_of_range_coordinates(self) -> None:
        cases = [("latitude", "91"), ("longitude", "181")]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.client.force_authenticate(self.pengelola)
                response = self.client.post(
                    "/api/v1/onboarding/bank-sampah",
                    {**REGISTRATION, field: value, "foto_kegiatan": _photo()},
                    format="multipart",
                )

                self.assertEqual(response.status_code, 422)
                self.assertIn("harus di antara", response.data["errors"][field][0])

    def test_me_put_updates_coordinates(self) -> None:
        bank = BankSampah.objects.create(nama="Bank Lestari", alamat="Depok", kota="Depok")
        pengelola = self._pengelola_of(bank)
        self.client.force_authenticate(pengelola)

        response = self.client.put(
            "/api/v1/bank-sampah/me",
            {"latitude": "-6.362829", "longitude": "106.828655"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        bank.refresh_from_db()
        self.assertEqual(bank.latitude, Decimal("-6.362829"))
        self.assertEqual(bank.longitude, Decimal("106.828655"))

    def test_me_put_rejects_out_of_range_longitude(self) -> None:
        bank = BankSampah.objects.create(nama="Bank BTH", alamat="Depok", kota="Depok")
        self.client.force_authenticate(self._pengelola_of(bank))

        response = self.client.put("/api/v1/bank-sampah/me", {"longitude": "181"}, format="json")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.data["errors"]["longitude"], ["Bujur harus di antara -180 dan 180"]
        )

    def test_me_put_can_clear_coordinates(self) -> None:
        bank = BankSampah.objects.create(
            nama="Bank Pindah",
            alamat="Depok",
            kota="Depok",
            latitude=Decimal("-6.200000"),
            longitude=Decimal("106.900000"),
        )
        self.client.force_authenticate(self._pengelola_of(bank))

        response = self.client.put(
            "/api/v1/bank-sampah/me", {"latitude": None, "longitude": None}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        bank.refresh_from_db()
        self.assertIsNone(bank.latitude)
        self.assertIsNone(bank.longitude)

    def test_me_is_only_for_this_bank_active_pengelola(self) -> None:
        # The new fields must not smuggle a bypass past IsActivePengelola.
        bank = BankSampah.objects.create(nama="Bank Ujung", alamat="Depok", kota="Depok")
        outsider = User.objects.create_user(
            email="orang@example.test", nama="Orang Lain", role=User.Role.PENGELOLA
        )
        self.client.force_authenticate(outsider)

        response = self.client.put(
            "/api/v1/bank-sampah/me",
            {"latitude": "-6.362829", "longitude": "106.828655"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        bank.refresh_from_db()
        self.assertIsNone(bank.latitude)

    @staticmethod
    def _pengelola_of(bank: BankSampah) -> User:
        return BankCoordinateApiTests._make_pengelola("suki@example.test", bank)


class BankDirectoryCoordinateTests(APITestCase):
    url = "/api/v1/bank-sampah"

    def setUp(self) -> None:
        self.user = User.objects.create_user(email="cari@example.test", nama="Pencari")
        self.client.force_authenticate(self.user)
        self.mandiri = BankSampah.objects.create(
            nama="Bank Garis",
            alamat="Jl. Garis No. 1",
            kota="Depok",
            latitude=Decimal("-6.362829"),
            longitude=Decimal("106.828655"),
        )
        BankSampah.objects.create(nama="Bank Kosong", alamat="Jl. Kosong No. 2", kota="Depok")

    def _results(self, **query: str) -> list[Mapping[str, Any]]:
        response = self.client.get(self.url, query or None)
        return response.data["results"]  # type: ignore[no-any-return]

    def _data(self, nama: str, **query: str) -> Mapping[str, Any]:
        return {item["nama"]: item for item in self._results(**query)}[nama]

    def test_directory_exposes_coordinates(self) -> None:
        item = self._data("Bank Garis")
        self.assertEqual(item["latitude"], "-6.362829")
        self.assertEqual(item["longitude"], "106.828655")

    def test_directory_keeps_banks_without_coordinates_visible_as_null(self) -> None:
        item = self._data("Bank Kosong")
        self.assertIsNone(item["latitude"])
        self.assertIsNone(item["longitude"])

    def test_directory_serialization_preserves_stored_precision(self) -> None:
        # The value the client reads must be the stored decimal, not a float.
        data = BankSampahDirectorySerializer(self.mandiri).data
        self.assertEqual(data["latitude"], "-6.362829")
        self.assertEqual(data["longitude"], "106.828655")


class BankDirectorySearchTests(APITestCase):
    """Directory keyword/kota filtering and pagination (PIL-308)."""

    url = "/api/v1/bank-sampah"

    def setUp(self) -> None:
        self.user = User.objects.create_user(email="cari@example.test", nama="Pencari")
        self.client.force_authenticate(self.user)
        self.garis = BankSampah.objects.create(
            nama="Bank Garis Dua",
            alamat="Jl. Garis No. 1",
            kota="Depok",
            latitude=Decimal("-6.362829"),
            longitude=Decimal("106.828655"),
        )
        self.kosong = BankSampah.objects.create(
            nama="Bank Kosong", alamat="Jl. Kosong No. 2", kota="Depok"
        )

    def _names(self, query: Mapping[str, str] | None = None) -> list[str]:
        return sorted(item["nama"] for item in self.client.get(self.url, query).data["results"])

    def test_q_searches_nama_alamat_and_kota(self) -> None:
        cases = [
            ("q", "Garis", ["Bank Garis Dua"]),  # nama
            ("q", "Jl. Kosong", ["Bank Kosong"]),  # alamat
            ("q", "Depok", ["Bank Garis Dua", "Bank Kosong"]),  # kota
        ]
        for param, word, expected in cases:
            with self.subTest(word=word):
                self.assertEqual(self._names({param: word}), expected)

    def test_short_or_missing_q_returns_all_bank_sampah(self) -> None:
        self.assertEqual(
            self._names({"q": "J"}),
            ["Bank Garis Dua", "Bank Kosong"],  # 1 char is noise, not a filter
        )
        self.assertEqual(self._names({}), ["Bank Garis Dua", "Bank Kosong"])

    def test_kota_filter_is_insensitive_to_case_and_spaces(self) -> None:
        for kota in ("depok", "  DEPOK  "):
            with self.subTest(kota=kota):
                self.assertEqual(self._names({"kota": kota}), ["Bank Garis Dua", "Bank Kosong"])
        self.assertEqual(self._names({"kota": "Bandung"}), [])

    def test_kota_and_q_combine(self) -> None:
        self.assertEqual(self._names({"kota": "Depok", "q": "Garis"}), ["Bank Garis Dua"])

    def test_kota_filter_collapses_administrative_prefix_variants(self) -> None:
        # PIL-329 option A: "Kota"/"Kab." prefixes on either side collapse.
        for kota in ("Depok", "Kota Depok", "KAB. DEPOK", "Kabupaten Depok", "kota  depok"):
            with self.subTest(kota=kota):
                self.assertEqual(self._names({"kota": kota}), ["Bank Garis Dua", "Bank Kosong"])

    def test_kota_prefix_strip_does_not_widen_the_match(self) -> None:
        # Stripping the prefix must not turn one city into another.
        self.assertEqual(self._names({"kota": "Kab. Bandung"}), [])

    def test_kota_filter_never_matches_a_bank_with_empty_kota(self) -> None:
        BankSampah.objects.create(nama="Bank Tanpa Kota", alamat="Jl. Itu", kota="")
        self.assertEqual(self._names({"kota": "Kota "}), [])
        self.assertEqual(self._names({"kota": "Depok"}), ["Bank Garis Dua", "Bank Kosong"])

    def test_q_still_matches_a_stored_kota_with_prefix(self) -> None:
        # `q` stays raw text search: only the `kota` param is normalized.
        self.assertEqual(self._names({"q": "Kabupaten Depok"}), [])

    def test_pagination_envelope_and_second_page(self) -> None:
        response = self.client.get(self.url, {"page_size": 1, "page": 1})
        self.assertEqual(response.data["count"], 2)
        self.assertIn("page=2", response.data["next"])
        self.assertIsNone(response.data["previous"])
        self.assertEqual([b["nama"] for b in response.data["results"]], ["Bank Garis Dua"])
        response = self.client.get(self.url, {"page_size": 1, "page": 2})
        self.assertIsNone(response.data["next"])
        # DRF omits `page=1` from the previous link.
        self.assertIn("page_size=1", response.data["previous"])
        self.assertNotIn("page=2", response.data["previous"])


class HaversineTests(SimpleTestCase):
    def test_known_pair_within_tolerance(self) -> None:
        # Depok ↔ Monas, Jakarta: ~15 km ground truth for this lat band.
        jarak = haversine_km(-6.362829, 106.828655, -6.175110, 106.827750)
        self.assertAlmostEqual(jarak, 20.9, delta=0.5)

    def test_same_point_is_zero(self) -> None:
        self.assertEqual(haversine_km(-6.362829, 106.828655, -6.362829, 106.828655), 0.0)


class BankDirectoryLocationSearchTests(APITestCase):
    """Coordinate + radius search on the directory list (PIL-314)."""

    url = "/api/v1/bank-sampah"

    def setUp(self) -> None:
        self.user = User.objects.create_user(email="cari@example.test", nama="Pencari")
        self.client.force_authenticate(self.user)
        # All in Depok, spread so distances differ: Dekat < Menengah < Jauh.
        self.dekat = BankSampah.objects.create(
            nama="Bank Dekat",
            alamat="Jl. A No. 1",
            kota="Depok",
            latitude=Decimal("-6.362829"),
            longitude=Decimal("106.828655"),
        )
        self.menengah = BankSampah.objects.create(
            nama="Bank Menengah",
            alamat="Jl. B No. 2",
            kota="Depok",
            latitude=Decimal("-6.372000"),
            longitude=Decimal("106.838000"),
        )
        self.jauh = BankSampah.objects.create(
            nama="Bank Jauh",
            alamat="Jl. C No. 3",
            kota="Depok",
            latitude=Decimal("-6.382000"),
            longitude=Decimal("106.848000"),
        )
        self.tanpa_koord = BankSampah.objects.create(
            nama="Bank Tanpa Koordinat", alamat="Jl. D No. 4", kota="Depok"
        )
        self.pusat = (-6.362829, 106.828655)  # = dekat's own coordinates.

    def _names(self, query: Mapping[str, Any]) -> list[str]:
        return [item["nama"] for item in self.client.get(self.url, query).data["results"]]

    def _trio(self, **overrides: Any) -> dict[str, Any]:
        query = {
            "latitude": str(self.pusat[0]),
            "longitude": str(self.pusat[1]),
            "radius_km": "5",
        }
        query.update({k: str(v) for k, v in overrides.items()})
        return query

    def test_radius_returns_only_in_circle_banks_with_jarak_km(self) -> None:
        # menengah sits ~1.45 km out; radius 1 keeps only dekat (0 km).
        data = self.client.get(self.url, self._trio(radius_km=1)).data
        self.assertEqual(data["count"], 1)
        hasil = data["results"][0]
        self.assertEqual(hasil["nama"], "Bank Dekat")
        self.assertIn("jarak_km", hasil)
        self.assertEqual(float(hasil["jarak_km"]), 0.0)

    def test_radius_hides_null_coordinate_banks(self) -> None:
        self.assertIn("Bank Tanpa Koordinat", self._names({"kota": "Depok"}))
        self.assertNotIn("Bank Tanpa Koordinat", self._names(self._trio(radius_km=100)))

    def test_boundary_bank_exactly_at_radius_is_included(self) -> None:
        # tanpa_koord sits at ~0 km on the same point if given coords; instead
        # use menengah and ask for exactly its distance from pusat.
        jarak = haversine_km(
            self.pusat[0],
            self.pusat[1],
            float(str(self.menengah.latitude)),
            float(str(self.menengah.longitude)),
        )
        nama = self._names(self._trio(radius_km=f"{jarak:.6f}"))
        self.assertIn("Bank Menengah", nama)

    def test_partial_location_trio_is_422(self) -> None:
        for partial in (
            {"latitude": "-6.36"},
            {"longitude": "106.82"},
            {"radius_km": "5"},
            {"latitude": "-6.36", "longitude": "106.82"},
        ):
            with self.subTest(params=sorted(partial)):
                response = self.client.get(self.url, partial)
                self.assertEqual(response.status_code, 422)

    def test_invalid_ranges_and_radius_bounds_are_422(self) -> None:
        for query in (
            {"latitude": "95", "longitude": "106", "radius_km": "5"},  # lat out of range
            {"latitude": "abc", "longitude": "106", "radius_km": "5"},
            {"latitude": "-6.36", "longitude": "200", "radius_km": "5"},  # lng out of range
            {"latitude": "-6.36", "longitude": "106", "radius_km": "0"},
            {"latitude": "-6.36", "longitude": "106", "radius_km": "-1"},
            {"latitude": "-6.36", "longitude": "106", "radius_km": "101"},  # over cap
            {"latitude": "-6.36", "longitude": "106", "radius_km": "nol"},
        ):
            with self.subTest(query=str(query)):
                response = self.client.get(self.url, query)
                self.assertEqual(response.status_code, 422)

    def test_sort_distance_orders_nearest_first_with_jarak_values(self) -> None:
        data = self.client.get(self.url, self._trio(radius_km=5, sort="distance")).data
        hasil = data["results"]
        self.assertEqual([b["nama"] for b in hasil], ["Bank Dekat", "Bank Menengah", "Bank Jauh"])
        jarak = [float(b["jarak_km"]) for b in hasil]
        self.assertEqual(jarak, sorted(jarak))
        self.assertTrue(jarak[0] < jarak[1] < jarak[2])

    def test_sort_distance_without_location_is_422(self) -> None:
        response = self.client.get(self.url, {"sort": "distance"})
        self.assertEqual(response.status_code, 422)

    def test_location_sort_defaults_to_nama_not_distance(self) -> None:
        # No sort param: nama ordering still applies despite distance mode.
        self.assertEqual(
            self._names(self._trio(radius_km=5)), ["Bank Dekat", "Bank Jauh", "Bank Menengah"]
        )

    def test_sort_and_pagination_page_two_is_ranks_three_four_of_full_set(self) -> None:
        # 5 banks at growing distances; page_size=2 → page 1 = ranks 1-2,
        # page 2 = ranks 3-4 of the FULL sorted set, never a per-page re-sort.
        for i in range(3, 6):
            BankSampah.objects.create(
                nama=f"Bank K{i}",
                alamat="Jl. K",
                kota="Depok",
                latitude=Decimal(f"-6.40{i}"),  # each ~111 m further south
                longitude=Decimal("106.828655"),
            )
        data = self.client.get(
            self.url, self._trio(radius_km=10, sort="distance", page_size=2, page=2)
        ).data
        self.assertEqual(data["count"], 6)  # dekat + menengah + jauh + 3 new (tanpa_koord hidden)
        ranks = [b["nama"] for b in data["results"]]
        # Page 1 would be [Dekat, Menengah]; page 2 must skip to ranks 3-4.
        self.assertEqual(ranks, ["Bank Jauh", "Bank K3"])
        jarak = [float(b["jarak_km"]) for b in data["results"]]
        self.assertTrue(jarak[0] < jarak[1])

    def test_q_and_kota_combine_with_radius(self) -> None:
        self.assertEqual(self._names(self._trio(radius_km=5, q="Menengah")), ["Bank Menengah"])
        self.assertEqual(
            self._names(self._trio(radius_km=5, kota="Depok", q="Dekat")), ["Bank Dekat"]
        )

    def test_non_joinable_banks_excluded_in_radius_mode(self) -> None:
        induk = BankSampah.objects.create(
            nama="Induk BTH",
            jenis_organisasi=BankSampah.OrganizationType.INDUK,
            latitude=Decimal("-6.362829"),
            longitude=Decimal("106.828655"),
            no_hp_pic="081",
        )
        pending = BankSampah.objects.create(
            nama="Bank Pending",
            status=BankSampah.Status.PENDING,
            latitude=Decimal("-6.362829"),
            longitude=Decimal("106.828655"),
            no_hp_pic="081",
        )
        nonaktif = BankSampah.objects.create(
            nama="Bank Nonaktif",
            is_active=False,
            latitude=Decimal("-6.362829"),
            longitude=Decimal("106.828655"),
            no_hp_pic="081",
        )
        nama_hadir = self._names(self._trio(radius_km=5, sort="distance"))
        for bank, why in [(induk, "induk"), (pending, "pending"), (nonaktif, "nonaktif")]:
            with self.subTest(why):
                self.assertNotIn(bank.nama, nama_hadir)


class BankDetailTests(APITestCase):
    url = "/api/v1/bank-sampah"

    def setUp(self) -> None:
        self.user = User.objects.create_user(email="cari@example.test", nama="Pencari")
        self.client.force_authenticate(self.user)
        self.bank = BankSampah.objects.create(
            nama="Bank Garis Dua",
            alamat="Jl. Garis No. 1",
            kota="Depok",
            latitude=Decimal("-6.362829"),
            longitude=Decimal("106.828655"),
        )
        for nomor, nama_sampah, kategori, harga, aktif in [
            ("K-1", "Kardus", "kertas", 1500, True),
            ("P-2", "Botol", "plastik", 2000, True),
            ("X-9", "Nonaktif", "dll", 500, False),
        ]:
            jenis = JenisSampah.objects.create(
                bank_sampah=self.bank,
                nomor=nomor,
                nama_sampah=nama_sampah,
                kategori=kategori,
                is_active=aktif,
            )
            if aktif:
                HargaSampah.objects.create(
                    jenis_sampah=jenis,
                    bank_sampah=self.bank,
                    harga_per_kg=harga,
                    berlaku_mulai=timezone.now() - timedelta(days=1),
                )

    def _detail(self, bank: BankSampah | None = None) -> Mapping[str, Any]:
        url = f"{self.url}/{(bank or self.bank).id}"
        return self.client.get(url).data  # type: ignore[no-any-return]

    def test_detail_returns_profile_status_coords_and_active_layanan(self) -> None:
        data = self._detail()
        self.assertEqual(data["nama"], "Bank Garis Dua")
        self.assertEqual(data["status"], "active")
        self.assertEqual(data["latitude"], "-6.362829")
        # `nomor`-ordered, and exactly the jenis sampah a member would be paid at.
        self.assertEqual([item["kode"] for item in data["layanan"]], ["K-1", "P-2"])
        lain = data["layanan"][1]
        self.assertEqual(lain["nama_sampah"], "Botol")
        self.assertEqual(lain["harga_per_kg"], "2000.00")
        self.assertEqual(lain["satuan"], "kg")
        self.assertNotIn("is_active", lain)

    def test_detail_hides_non_joinable_banks(self) -> None:
        induk = BankSampah.objects.create(
            nama="Induk BTH", jenis_organisasi=BankSampah.OrganizationType.INDUK, no_hp_pic="081"
        )
        pending = BankSampah.objects.create(
            nama="Bank Pending", status=BankSampah.Status.PENDING, no_hp_pic="081"
        )
        for bank, why in [(induk, "induk"), (pending, "pending")]:
            with self.subTest(why):
                response = self.client.get(f"{self.url}/{bank.id}")
                self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(f"{self.url}/not-a-uuid").status_code, 404)


class BankProfileApiTests(APITestCase):
    def test_bank_name_must_have_at_least_three_characters(self) -> None:
        bank = BankSampah.objects.create(nama="Bank BTH", alamat="Depok", kota="Depok")
        pengelola = User.objects.create_user(
            email="sari@example.test",
            nama="Ibu Sari",
            bank_sampah=bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        self.client.force_authenticate(pengelola)

        response = self.client.put(
            "/api/v1/bank-sampah/me",
            {"nama": " ab ", "alamat": "Depok", "kota": "Depok", "no_hp_pic": "081234567890"},
            format="json",
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.data["errors"]["nama"], ["Nama bank sampah wajib diisi"])


class BankSerializerTests(TestCase):
    def test_bank_without_pengelola_reports_none(self) -> None:
        bank = BankSampah.objects.create(nama="Bank Sepi", alamat="x", kota="Depok")

        self.assertIsNone(BankSampahSerializer(bank).data["pengelola"])

    def test_activity_photo_is_none_when_nothing_was_uploaded(self) -> None:
        bank = BankSampah.objects.create(nama="Bank Polos", alamat="x", kota="Depok")

        self.assertIsNone(BankSampahApprovalListSerializer(bank).data["foto_kegiatan"])

    def test_activity_photo_needs_a_request_to_build_a_signed_link(self) -> None:
        bank = BankSampah.objects.create(
            nama="Bank Foto", alamat="x", kota="Depok", foto_kegiatan="bank_sampah/kegiatan/a.png"
        )

        self.assertIsNone(BankSampahApprovalListSerializer(bank).data["foto_kegiatan"])

    @override_settings(GS_BUCKET_NAME="pilah-bucket")
    def test_activity_photo_uses_storage_url_when_a_bucket_is_configured(self) -> None:
        bank = BankSampah.objects.create(
            nama="Bank Cloud", alamat="x", kota="Depok", foto_kegiatan="bank_sampah/kegiatan/a.png"
        )

        url = BankSampahApprovalListSerializer(bank).data["foto_kegiatan"]

        self.assertTrue(url.endswith("bank_sampah/kegiatan/a.png"))


class RegistrationSerializerTests(SimpleTestCase):
    def test_a_missing_activity_photo_is_refused_with_the_proof_message(self) -> None:
        # FileField rejects empty uploads first; the explicit guard is the
        # fallback should a falsy value ever reach the field validator.
        with self.assertRaisesRegex(serializers.ValidationError, "bukti validasi"):
            BankSampahRegistrationSerializer().validate_foto_kegiatan(None)


class BankHierarchyModelTests(TestCase):
    def test_only_unit_banks_may_have_a_parent(self) -> None:
        induk = BankSampah.objects.create(
            nama="Induk",
            alamat="x",
            kota="Depok",
            jenis_organisasi=BankSampah.OrganizationType.INDUK,
        )
        mandiri = BankSampah(nama="Mandiri", alamat="x", kota="Depok", parent=induk)

        with self.assertRaises(ValidationError) as caught:
            mandiri.save()

        self.assertIn("parent", caught.exception.message_dict)


class BankDirectoryCoverageGapsTests(APITestCase):
    """Branch/condition completeness for the directory endpoints.

    Not new behavior: closes boundary and empty-state branches that earlier
    PIL-314/326/308 tests left uncovered so new-code coverage stays above 99%.
    """

    url = "/api/v1/bank-sampah"

    def setUp(self) -> None:
        self.user = User.objects.create_user(email="cari@example.test", nama="Pencari")
        self.client.force_authenticate(self.user)
        self.bank = BankSampah.objects.create(
            nama="Bank Satu",
            alamat="Jl. A No. 1",
            kota="Depok",
            latitude=Decimal("-6.362829"),
            longitude=Decimal("106.828655"),
        )

    def _trio(self, **overrides: Any) -> dict[str, Any]:
        query = {
            "latitude": "-6.362829",
            "longitude": "106.828655",
            "radius_km": "5",
            **overrides,
        }
        return {k: v for k, v in query.items() if v is not None}

    def test_radius_cap_of_one_hundred_km_is_accepted(self) -> None:
        # Radius at exactly the cap is valid; only strictly-above is 422.
        response = self.client.get(self.url, self._trio(radius_km="100"))
        self.assertEqual(response.status_code, 200)

    def test_coordinate_limits_are_inclusive(self) -> None:
        # ±90 / ±180 are accepted: the range check is a closed interval.
        for query in (
            self._trio(latitude="-90"),
            self._trio(latitude="90"),
            self._trio(longitude="-180"),
            self._trio(longitude="180"),
        ):
            with self.subTest(query=str(query)):
                response = self.client.get(self.url, query)
                self.assertEqual(response.status_code, 200)

    def test_distance_search_with_no_bank_in_radius_is_empty_envelope(self) -> None:
        # Nothing within 1 km: count 0, empty results, no crash.
        response = self.client.get(
            self.url,
            self._trio(latitude="-3.0", longitude="105.0", radius_km="1", sort="distance"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_keyword_search_with_no_match_is_empty_envelope(self) -> None:
        response = self.client.get(self.url, {"q": "kata-tak-ada", "page_size": "5"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])


class BankDetailCoverageGapsTests(APITestCase):
    """Detail-endpoint branch completeness (PIL-308/326/351).

    Unauthenticated access, zero-layanan banks, null coordinates, and an
    active jenis that has never had a price version.
    """

    url = "/api/v1/bank-sampah"

    def setUp(self) -> None:
        self.user = User.objects.create_user(email="cari@example.test", nama="Pencari")
        self.bank = BankSampah.objects.create(
            nama="Bank Sederhana", alamat="Jl. B No. 2", kota="Depok"
        )

    def _detail(self, bank: BankSampah | None = None) -> Any:
        url = f"{self.url}/{(bank or self.bank).id}"
        return self.client.get(url)

    def test_detail_unauthenticated_is_401(self) -> None:
        response = self._detail()
        self.assertEqual(response.status_code, 401)

    def test_detail_of_bank_without_layanan_or_coordinates(self) -> None:
        self.client.force_authenticate(self.user)
        data = self._detail().data
        self.assertEqual(data["layanan"], [])
        self.assertIsNone(data["latitude"])
        self.assertIsNone(data["longitude"])

    def test_active_layanan_without_any_price_version_has_null_harga(self) -> None:
        # An active jenis with no HargaSampah version at all: the row is
        # listed but prices as null rather than disappearing.
        self.client.force_authenticate(self.user)
        JenisSampah.objects.create(
            bank_sampah=self.bank,
            nomor="K-1",
            nama_sampah="Kardus",
            kategori=JenisSampah.Kategori.KERTAS,
            is_active=True,
        )
        data = self._detail().data
        self.assertEqual(len(data["layanan"]), 1)
        self.assertIsNone(data["layanan"][0]["harga_per_kg"])
        self.assertIsNone(data["layanan"][0]["harga_berlaku_mulai"])


class KotaNormalisasiTests(SimpleTestCase):
    """normalisasi_kota stack-loop behavior (PIL-329 option A)."""

    def test_double_prefix_collapses_through_a_second_loop_pass(self) -> None:
        # "Kabupaten Kota X": the first pass strips "kabupaten ", the second
        # loop pass strips "kota " from what is now the head of the string.
        self.assertEqual(normalisasi_kota("Kabupaten Kota Depok"), "depok")
        self.assertEqual(normalisasi_kota("Kotamadya Kab. Cimahi"), "cimahi")

    def test_plain_name_is_already_stable(self) -> None:
        self.assertEqual(normalisasi_kota("  Depok  "), "depok")
