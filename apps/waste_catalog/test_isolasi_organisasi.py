"""PIL-305: jenis sampah satu bank sampah tidak terjangkau bank lain (BR-02).

Setiap rute jenis sampah diuji, bukan hanya daftarnya: aksi detail
(`/status`, `/harga`) memakai jalur `get_object()` yang sama, dan justru di
situlah kebocoran lingkup biasanya lolos. Jawaban untuk milik bank lain adalah
404, bukan 403, supaya keberadaan datanya pun tidak terkonfirmasi.
"""

from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, HargaSampah, JenisSampah, User


class IsolasiJenisSampahAntarBankTests(APITestCase):
    def setUp(self) -> None:
        self.bank_lain, _ = self.buat_bank("Bank Sampah Melati", "melati@example.com")
        self.bank, self.user = self.buat_bank("Bank Sampah BTH", "sari@example.com")

        self.jenis_bank_lain = JenisSampah.objects.create(
            bank_sampah=self.bank_lain,
            nomor="PLS-001",
            nama_sampah="Plastik PET",
            kategori="plastik",
            satuan="karung",
        )
        HargaSampah.objects.create(
            jenis_sampah=self.jenis_bank_lain,
            bank_sampah=self.bank_lain,
            harga_per_kg=Decimal("4000"),
            berlaku_mulai=timezone.now(),
        )

        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def buat_bank(self, nama: str, email: str) -> tuple[BankSampah, User]:
        bank = BankSampah.objects.create(
            nama=nama,
            alamat="Depok",
            kota="Depok",
            no_hp_pic="+628123456789",
            status=BankSampah.Status.ACTIVE,
        )
        user = User.objects.create_user(
            email=email,
            nama=f"Pengurus {nama}",
            bank_sampah=bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        return bank, user

    @property
    def url_asing(self) -> str:
        return f"/api/v1/jenis-sampah/{self.jenis_bank_lain.id}"

    def test_daftar_tidak_memuat_jenis_bank_lain(self) -> None:
        response = self.client.get("/api/v1/jenis-sampah")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["results"], [])

    def test_detail_jenis_bank_lain_tidak_ditemukan(self) -> None:
        self.assertEqual(self.client.get(self.url_asing).status_code, 404)

    def test_ubah_jenis_bank_lain_tidak_ditemukan(self) -> None:
        response = self.client.put(
            self.url_asing,
            {"kode": "PLS-001", "nama_sampah": "Dibajak", "kategori": "plastik"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.jenis_bank_lain.refresh_from_db()
        self.assertEqual(self.jenis_bank_lain.nama_sampah, "Plastik PET")

    def test_ubah_satuan_jenis_bank_lain_tidak_ditemukan(self) -> None:
        response = self.client.patch(self.url_asing, {"satuan": "pcs"}, format="json")

        self.assertEqual(response.status_code, 404)
        self.jenis_bank_lain.refresh_from_db()
        self.assertEqual(self.jenis_bank_lain.satuan, "karung")

    def test_nonaktifkan_jenis_bank_lain_tidak_ditemukan(self) -> None:
        response = self.client.patch(
            f"{self.url_asing}/status", {"is_active": False}, format="json"
        )

        self.assertEqual(response.status_code, 404)
        self.jenis_bank_lain.refresh_from_db()
        self.assertTrue(self.jenis_bank_lain.is_active)

    def test_riwayat_harga_jenis_bank_lain_tidak_ditemukan(self) -> None:
        self.assertEqual(self.client.get(f"{self.url_asing}/harga").status_code, 404)

    def test_ubah_harga_jenis_bank_lain_tidak_ditemukan(self) -> None:
        response = self.client.post(
            f"{self.url_asing}/harga", {"harga_per_kg": "9999"}, format="json"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.jenis_bank_lain.riwayat_harga.count(), 1)

    def test_hapus_jenis_bank_lain_tidak_ditemukan_bukan_409(self) -> None:
        """404 mendahului penolakan 409: keberadaan data bank lain tidak dibocorkan."""
        self.assertEqual(self.client.delete(self.url_asing).status_code, 404)
