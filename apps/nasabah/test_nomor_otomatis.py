"""UAT 2026-11: kode keanggotaan ternomori otomatis, dan akun pendaftaran
yang belum lengkap boleh dihapus agar perannya dapat dipilih ulang."""

from rest_framework.response import Response
from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, User
from apps.nasabah.models import Nasabah as NasabahModel


class NomorOtomatisNasabahTests(APITestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(nama="Bank Nomor", alamat="Depok", kota="Depok")
        self.pengelola = User.objects.create_user(
            email="pengurus-nomor@example.test",
            nama="Pengurus Nomor",
            bank_sampah=self.bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        self.client.force_authenticate(self.pengelola)

    def _post_nasabah(self, kode: str | None = None) -> Response:
        body = {
            "nama": "Nasabah Nomor",
            "email": "nasabah-nomor@example.test",
            "jenis_kelamin": "laki-laki",
            "tanggal_lahir": "1990-01-01",
            "no_hp": "081234567890",
            "alamat": "Jl. Contoh Alamat Panjang",
        }
        if kode is not None:
            body["kode"] = kode
        return self.client.post("/api/v1/nasabah", body, format="json")

    def test_buat_nasabah_tanpa_kode_mendapat_nomor_otomatis(self) -> None:
        response = self._post_nasabah()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["kode"], "NAS-001")

    def test_nomor_berikut_menambah_dari_nomor_terbesar(self) -> None:
        self.assertEqual(NasabahModel.nomor_berikut(self.bank.id), "NAS-001")
        Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-007",
            nama="Sudah Ada",
            no_hp="081234567891",
            alamat="Jl. Ada",
        )
        self.assertEqual(NasabahModel.nomor_berikut(self.bank.id), "NAS-008")

    def test_isi_kode_manual_masih_diterima(self) -> None:
        response = self._post_nasabah(kode="NAS-042")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["kode"], "NAS-042")

    def test_dua_tanpa_kode_berturut_mendapat_nomor_berbeda(self) -> None:
        first = self._post_nasabah()
        self.assertEqual(first.status_code, 201, first.data)
        body = {
            "nama": "Nasabah Kedua",
            "email": "nasabah-kedua@example.test",
            "jenis_kelamin": "perempuan",
            "tanggal_lahir": "1991-02-02",
            "no_hp": "081234567899",
            "alamat": "Jl. Kedua No. 2",
        }
        second = self.client.post("/api/v1/nasabah", body, format="json")
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(first.data["kode"], "NAS-001")
        self.assertEqual(second.data["kode"], "NAS-002")


class HapusPendaftaranBelumLengkapTests(APITestCase):
    """DELETE /onboarding/discard-registration: akun yang belum lengkap boleh
    dihapus supaya pendaftaran ulang dapat memilih peran lagi (UAT 2026-11)."""

    def setUp(self) -> None:
        self.akun = User.objects.create_user(
            email="belum-lengkap@example.test",
            nama="Belum Lengkap",
            role=User.Role.PENGELOLA,
        )
        self.client.force_authenticate(self.akun)

    def test_email_polos_tanpa_data_bisa_dihapus(self) -> None:
        email = self.akun.email
        response = self.client.delete("/api/v1/onboarding/discard-registration")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(User.objects.filter(email=email).exists())

    def test_akun_lengkap_tolak_dihapus(self) -> None:
        self.akun.is_profile_complete = True
        self.akun.save()
        response = self.client.delete("/api/v1/onboarding/discard-registration")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(User.objects.filter(email=self.akun.email).exists())

    def test_akun_dengan_keanggotaan_tolak_dihapus(self) -> None:
        bank = BankSampah.objects.create(nama="Bank Terkait", alamat="Depok", kota="Depok")
        # Keanggotaan hanya boleh mengikat akun berperan nasabah (models.clean).
        self.akun.role = User.Role.NASABAH
        self.akun.save()
        Nasabah.objects.create(
            user=self.akun,
            bank_sampah=bank,
            nomor="NAS-100",
            nama=self.akun.nama,
            alamat="Jl. Terkait",
            no_hp="081234567892",
            email=self.akun.email,
        )
        response = self.client.delete("/api/v1/onboarding/discard-registration")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(User.objects.filter(email=self.akun.email).exists())
