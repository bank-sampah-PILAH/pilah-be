from collections.abc import Mapping
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework import serializers
from rest_framework.test import APITestCase

from api.models import BankSampah, JenisSampah, User
from apps.bank_sampah.serializers import (
    BankSampahApprovalListSerializer,
    BankSampahDirectorySerializer,
    BankSampahRegistrationSerializer,
    BankSampahSerializer,
)
from apps.bank_sampah.services import BankOnboardingService

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
            JenisSampah.objects.create(
                bank_sampah=self.bank,
                nomor=nomor,
                nama_sampah=nama_sampah,
                kategori=kategori,
                harga_per_kg=harga,
                is_active=aktif,
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
