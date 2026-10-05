from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework import serializers
from rest_framework.test import APITestCase

from api.models import BankSampah, User
from apps.bank_sampah.serializers import (
    BankSampahApprovalListSerializer,
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
