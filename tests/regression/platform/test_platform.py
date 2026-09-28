"""Platform contracts: public routes, signed media, validators, model units."""

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.signing import TimestampSigner
from django.test import TestCase
from rest_framework import serializers

from api.models import BankSampah, User
from api.services import NumberingService
from api.validators import get_initials, normalize_indonesian_phone
from tests.regression.helpers import RegressionTestCase


class PlatformRouteTests(RegressionTestCase):
    def test_healthz_ok(self) -> None:
        self.client.credentials()
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_schema_and_docs_reachable(self) -> None:
        self.client.credentials()
        self.assertEqual(self.client.get("/api/schema/").status_code, 200)
        self.assertEqual(self.client.get("/api/docs/").status_code, 200)

    def test_activity_media_bad_and_missing_tokens_404(self) -> None:
        self.client.credentials()
        self.assertEqual(self.client.get("/media/activity/bogus-token").status_code, 404)
        signed = TimestampSigner(salt="bank-sampah-kegiatan").sign("bank_sampah/kegiatan/x.jpg")
        self.assertEqual(self.client.get(f"/media/activity/{signed}").status_code, 404)

    def test_activity_media_serves_existing_file(self) -> None:
        path = "bank_sampah/kegiatan/probe.jpg"
        default_storage.save(path, ContentFile(b"fakejpg"))
        try:
            self.client.credentials()
            signed = TimestampSigner(salt="bank-sampah-kegiatan").sign(path)
            response = self.client.get(f"/media/activity/{signed}")
            self.assertEqual(response.status_code, 200)
            wrong_prefix = TimestampSigner(salt="bank-sampah-kegiatan").sign("other/x.jpg")
            self.assertEqual(self.client.get(f"/media/activity/{wrong_prefix}").status_code, 404)
        finally:
            default_storage.delete(path)


class PlatformUnitTests(TestCase):
    def test_phone_normalization_variants(self) -> None:
        self.assertEqual(normalize_indonesian_phone("081234567890"), "+6281234567890")
        self.assertEqual(normalize_indonesian_phone("6281234567890"), "+6281234567890")
        self.assertEqual(normalize_indonesian_phone("+6281234567890"), "+6281234567890")
        self.assertEqual(normalize_indonesian_phone("0812-3456-7890"), "+6281234567890")

    def test_phone_normalization_rejects(self) -> None:
        for bad in ("", "123", "07111111111", "08123"):
            with self.subTest(bad=bad):
                with self.assertRaises(serializers.ValidationError):
                    normalize_indonesian_phone(bad)

    def test_get_initials(self) -> None:
        self.assertEqual(get_initials("Budi Santoso"), "BS")
        self.assertEqual(get_initials("A"), "A")
        self.assertEqual(get_initials(""), "NA")
        self.assertEqual(get_initials("  Budi   Santoso  Wijaya "), "BS")

    def test_numbering_service_sequences(self) -> None:
        bank = BankSampah.objects.create(
            nama="Bank", alamat="Jl. Panjang Sekali No. 1", kota="Depok", no_hp_pic="+628100000001"
        )
        self.assertEqual(NumberingService.next_nasabah_number(bank), "NAS-0001")
        self.assertEqual(NumberingService.next_jenis_number(bank), "JS-0001")

    def test_user_manager_requires_email(self) -> None:
        with self.assertRaises(ValueError):
            User.objects.create_user(email="")

    def test_create_superuser_defaults(self) -> None:
        admin = User.objects.create_superuser(email="root@example.com", nama="Root")
        self.assertEqual(admin.role, User.Role.SUPERADMIN)
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_model_str_and_hierarchy(self) -> None:
        bank = BankSampah.objects.create(
            nama="Bank Sampah BTH",
            alamat="Depok",
            kota="Depok",
            no_hp_pic="+628123456789",
        )
        user = User.objects.create_user(email="sari@example.com", nama="Ibu Sari")
        self.assertEqual(str(bank), "Bank Sampah BTH")
        self.assertEqual(str(user), "sari@example.com")
        BankSampah.objects.create(
            nama="Induk",
            alamat="Jl. Panjang Sekali No. 1",
            kota="Depok",
            no_hp_pic="+628100000001",
            jenis_organisasi=BankSampah.OrganizationType.INDUK,
        )
        with self.assertRaises(ValidationError):
            BankSampah(
                nama="Unit Buruk",
                alamat="Jl. Panjang Sekali No. 2",
                kota="Depok",
                no_hp_pic="+628100000002",
                jenis_organisasi=BankSampah.OrganizationType.UNIT,
            ).save()
