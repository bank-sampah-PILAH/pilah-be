from unittest.mock import patch

from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, User
from apps.nasabah.serializers import NasabahSerializer


def _nasabah_payload(**overrides: str) -> dict[str, str]:
    payload = {
        "kode": "NAS-0001",
        "nama": "Budi Santoso",
        "jenis_kelamin": "laki-laki",
        "tanggal_lahir": "1990-01-01",
        "no_hp": "081234567890",
        "alamat": "Jl. Anggrek No. 3",
        "email": "budi@example.com",
    }
    payload.update(overrides)
    return payload


class NasabahManagementEdgeCaseTests(APITestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(nama="Bank Nasabah", alamat="Depok", kota="Depok")
        self.pengelola = User.objects.create_user(
            email="pengurus@example.test",
            nama="Pengurus",
            bank_sampah=self.bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        self.client.force_authenticate(self.pengelola)

    def test_member_number_must_be_unique_within_the_bank(self) -> None:
        first = self.client.post("/api/v1/nasabah", _nasabah_payload(), format="json")
        self.assertEqual(first.status_code, 201, first.data)

        duplicate = self.client.post(
            "/api/v1/nasabah",
            _nasabah_payload(no_hp="081234567891", email="lain@example.com"),
            format="json",
        )

        self.assertEqual(duplicate.status_code, 422)
        self.assertEqual(duplicate.data["errors"]["kode"], ["ID Nasabah sudah digunakan"])

    def test_inactive_filter_lists_only_deactivated_approved_members(self) -> None:
        Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-0001",
            nama="Aktif",
            no_hp="+628111111111",
            email="a@example.test",
        )
        Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-0002",
            nama="Nonaktif",
            no_hp="+628222222222",
            email="b@example.test",
            is_active=False,
        )

        response = self.client.get("/api/v1/nasabah", {"status": "tidak_aktif"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["nama"] for row in response.data["results"]], ["Nonaktif"])

    def test_blank_gender_is_refused(self) -> None:
        response = self.client.post(
            "/api/v1/nasabah", _nasabah_payload(jenis_kelamin=""), format="json"
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.data["errors"]["jenis_kelamin"], ["Jenis kelamin wajib dipilih"])

    def test_membership_string_shows_number_and_name(self) -> None:
        nasabah = Nasabah.objects.create(
            bank_sampah=self.bank, nomor="NAS-0007", nama="Siti", no_hp="+628333333333"
        )

        self.assertEqual(str(nasabah), "NAS-0007 - Siti")


class NasabahSerializerGuardTests(APITestCase):
    def test_blank_email_and_member_number_are_refused_by_the_field_validators(self) -> None:
        # The CharField/EmailField reject blanks first over HTTP; the explicit
        # validators are the backstop for any input that reaches them as is.
        serializer = NasabahSerializer()

        with self.assertRaisesRegex(Exception, "Email wajib diisi"):
            serializer.validate_email("   ")
        with self.assertRaisesRegex(Exception, "ID Nasabah wajib diisi"):
            serializer.validate_kode("   ")


class NasabahSelfRegistrationEdgeCaseTests(APITestCase):
    def test_permission_error_from_the_port_is_reported_as_forbidden(self) -> None:
        # IsNasabah screens the role already; the 403 mapping is the second
        # line of defence, so drive it through the authentication port.
        user = User.objects.create_user(
            email="warga@example.test",
            nama="Warga",
            role=User.Role.NASABAH,
            is_profile_complete=True,
        )
        bank = BankSampah.objects.create(nama="Bank Aktif", alamat="x", kota="Depok")
        self.client.force_authenticate(user)

        with patch("apps.nasabah.views.register_nasabah", side_effect=PermissionError("ditolak")):
            response = self.client.post(
                "/api/v1/onboarding/nasabah", {"bank_sampah_id": str(bank.id)}, format="json"
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data, {"error": "ditolak"})
