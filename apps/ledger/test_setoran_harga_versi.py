"""PIL-304: setoran memakai versi harga yang berlaku saat transaksi (UC-12, BR-03)."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, DetailTransaksi, HargaSampah, JenisSampah, Nasabah, Saldo, User


class SetoranHargaVersiTests(APITestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(
            nama="Bank Sampah BTH",
            alamat="Depok",
            kota="Depok",
            no_hp_pic="+628123456789",
            status=BankSampah.Status.ACTIVE,
        )
        self.user = User.objects.create_user(
            email="sari@example.com",
            nama="Ibu Sari",
            bank_sampah=self.bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        self.nasabah = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-0001",
            nama="Ahmad Ridwan",
            no_hp="+628123456789",
            alamat="Jl. Mawar No. 12",
        )
        Saldo.objects.create(nasabah=self.nasabah)
        self.jenis = JenisSampah.objects.create(
            bank_sampah=self.bank,
            nomor="PLS-001",
            nama_sampah="Plastik PET",
            kategori="plastik",
        )
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def _versi(self, harga: str, mulai: timedelta) -> None:
        HargaSampah.objects.create(
            jenis_sampah=self.jenis,
            bank_sampah=self.bank,
            harga_per_kg=Decimal(harga),
            berlaku_mulai=timezone.now() + mulai,
        )

    def _setor(self, berat: str = "2.000") -> DetailTransaksi:
        response = self.client.post(
            "/api/v1/transaksi",
            {
                "nasabah_id": str(self.nasabah.id),
                "items": [{"jenis_sampah_id": str(self.jenis.id), "berat": berat}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return DetailTransaksi.objects.get(transaksi_id=response.data["id"])

    def test_setoran_uses_the_version_in_effect_and_ignores_scheduled_ones(self) -> None:
        self._versi("4000", -timedelta(days=1))
        self._versi("9000", timedelta(days=1))

        item = self._setor("2.000")

        self.assertEqual(item.harga_snapshot, 4000)
        self.assertEqual(item.subtotal, 8000)

    def test_a_price_change_leaves_recorded_setoran_untouched(self) -> None:
        # SDS 7.1.2: harga disalin ke transaksi, jadi laporan lama tetap sama.
        self._versi("4000", -timedelta(days=1))
        lama = self._setor("2.000")

        diubah = self.client.post(
            f"/api/v1/jenis-sampah/{self.jenis.id}/harga", {"harga_per_kg": "6000"}, format="json"
        )
        self.assertEqual(diubah.status_code, 201, diubah.data)
        baru = self._setor("2.000")

        lama.refresh_from_db()
        self.assertEqual((lama.harga_snapshot, lama.subtotal), (4000, 8000))
        self.assertEqual(lama.transaksi.total_nilai, 8000)
        self.assertEqual((baru.harga_snapshot, baru.subtotal), (6000, 12000))
