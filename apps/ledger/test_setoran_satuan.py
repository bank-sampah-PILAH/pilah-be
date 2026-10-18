"""PIL-305: setoran membekukan satuan jenis sampah, seperti harganya (BR-03)."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, DetailTransaksi, HargaSampah, JenisSampah, Nasabah, Saldo, User


class SetoranSatuanSnapshotTests(APITestCase):
    """Satuan ikut tersalin ke detail transaksi dan tidak ikut berubah sesudahnya.

    Tanpa ini, mengubah satuan sebuah jenis akan menulis ulang satuan pada
    setiap struk lama: kelas kesalahan yang sama dengan harga pada BR-03.
    """

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
        HargaSampah.objects.create(
            jenis_sampah=self.jenis,
            bank_sampah=self.bank,
            harga_per_kg=Decimal("4000"),
            berlaku_mulai=timezone.now() - timedelta(days=1),
        )
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

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

    def test_satuan_tersalin_ke_detail_saat_setoran_dicatat(self) -> None:
        self.jenis.satuan = "karung"
        self.jenis.save(update_fields=["satuan"])

        item = self._setor("2.000")

        self.assertEqual(item.satuan_snapshot, "karung")

    def test_satuan_setoran_lama_tidak_ikut_berubah_saat_jenis_disunting(self) -> None:
        item = self._setor("2.000")
        self.assertEqual(item.satuan_snapshot, "kg")

        self.jenis.satuan = "pcs"
        self.jenis.save(update_fields=["satuan"])

        item.refresh_from_db()
        self.assertEqual(item.satuan_snapshot, "kg")
