"""PIL-309: comparing one waste type's current price across banks."""

from datetime import timedelta
from typing import Any
from uuid import uuid4

from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, HargaSampah, JenisSampah, User

URL = "/api/v1/bank-sampah/harga-perbandingan"


class HargaPerbandinganTests(APITestCase):
    def setUp(self) -> None:
        self.pencari = User.objects.create_user(email="pencari@example.test", nama="Pencari")
        self.auth_as(self.pencari)
        self.bank_a = self.buat_bank("Bank A", kota="Depok")
        self.bank_b = self.buat_bank("Bank B", kota="Bogor")
        # Kode (nomor) is the shared cross-bank key: same kode at both banks.
        self.jenis_a = self.buat_jenis(self.bank_a, harga=3000)
        self.jenis_b = self.buat_jenis(self.bank_b, harga=2500)
        self.jenis_asal = self.jenis_a

    def auth_as(self, user: User) -> None:
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def buat_bank(self, nama: str, kota: str, **fields: Any) -> BankSampah:
        return BankSampah.objects.create(
            nama=nama,
            alamat="Jl. Tes",
            kota=kota,
            no_hp_pic="+628123456789",
            **{"status": BankSampah.Status.ACTIVE, **fields},
        )

    def buat_jenis(
        self, bank: BankSampah, harga: int = 3500, kode: str = "PLS-001", aktif: bool = True
    ) -> JenisSampah:
        jenis = JenisSampah.objects.create(
            bank_sampah=bank,
            nomor=kode,
            nama_sampah="Plastik PET",
            kategori=JenisSampah.Kategori.PLASTIK,
            is_active=aktif,
        )
        HargaSampah.objects.create(
            jenis_sampah=jenis,
            bank_sampah=bank,
            harga_per_kg=harga,
            berlaku_mulai=timezone.now() - timedelta(days=1),
        )
        return jenis

    def _fetch(self, jenis: JenisSampah | None = None, banks: str | None = None) -> Any:
        return self.client.get(
            URL,
            {
                "jenis_sampah_id": str((jenis or self.jenis_asal).id),
                "bank_ids": banks or f"{self.bank_a.id},{self.bank_b.id}",
            },
        )

    def test_active_price_per_bank_in_requested_order(self) -> None:
        data = self._fetch().data
        self.assertEqual(data["jenis_sampah"]["nomor"], "PLS-001")
        self.assertEqual(data["jenis_sampah"]["satuan"], "kg")
        self.assertEqual(
            [
                (row["nama"], row["harga_per_kg"], row["harga_tidak_tersedia"])
                for row in data["perbandingan"]
            ],
            [("Bank A", "3000.00", False), ("Bank B", "2500.00", False)],
        )
        for row in data["perbandingan"]:
            self.assertIsNone(row["alasan"])
            self.assertIsNotNone(row["berlaku_mulai"])

    def test_bank_without_the_kode_reports_tanpa_jenis(self) -> None:
        # Drop the row that shares the kode: bank B now has no PLS-001 at all.
        HargaSampah.objects.filter(jenis_sampah=self.jenis_b).delete()
        JenisSampah.objects.filter(id=self.jenis_b.id).delete()
        row = self._fetch().data["perbandingan"][1]
        self.assertTrue(row["harga_tidak_tersedia"])
        self.assertEqual(row["alasan"], "tanpa_jenis")
        self.assertIsNone(row["harga_per_kg"])

    def test_inactive_jenis_reports_jenis_nonaktif(self) -> None:
        JenisSampah.objects.filter(id=self.jenis_b.id).update(is_active=False)
        row = self._fetch().data["perbandingan"][1]
        self.assertEqual(row["alasan"], "jenis_nonaktif")

    def test_only_a_future_price_reports_belum_ada_harga(self) -> None:
        # Replace the version that is already in effect with a future one.
        HargaSampah.objects.filter(jenis_sampah=self.jenis_b).delete()
        HargaSampah.objects.create(
            jenis_sampah=self.jenis_b,
            bank_sampah=self.bank_b,
            harga_per_kg=9999,
            berlaku_mulai=timezone.now() + timedelta(days=7),
        )
        row = self._fetch().data["perbandingan"][1]
        self.assertEqual(row["alasan"], "belum_ada_harga")

    def test_overlapping_versions_resolve_to_the_latest(self) -> None:
        HargaSampah.objects.create(
            jenis_sampah=self.jenis_b,
            bank_sampah=self.bank_b,
            harga_per_kg=2750,
            berlaku_mulai=timezone.now() - timedelta(hours=1),
        )
        row = self._fetch().data["perbandingan"][1]
        # The newest version (2750, created later on the same berlaku_mulai
        # rule; here strictly later berlaku_mulai) wins.
        self.assertEqual(row["harga_per_kg"], "2750.00")

    def test_missing_or_unknown_jenis_is_422(self) -> None:
        for params in (
            {},
            {"jenis_sampah_id": "not-a-uuid", "bank_ids": str(self.bank_a.id)},
            {"jenis_sampah_id": str(uuid4()), "bank_ids": str(self.bank_a.id)},
        ):
            with self.subTest(params=str(params)):
                self.assertEqual(
                    self.client.get(URL, params).status_code
                    if params
                    else self.client.get(URL).status_code,
                    422,
                )

    def test_empty_or_oversized_bank_ids_is_422(self) -> None:
        for bank_ids in ("", " ", ",,"):
            with self.subTest(bank_ids=bank_ids):
                response = self.client.get(
                    URL, {"jenis_sampah_id": str(self.jenis_asal.id), "bank_ids": bank_ids}
                )
                self.assertEqual(response.status_code, 422)
        banyak = ",".join(str(uuid4()) for _ in range(11))
        response = self.client.get(
            URL, {"jenis_sampah_id": str(self.jenis_asal.id), "bank_ids": banyak}
        )
        self.assertEqual(response.status_code, 422)

    def test_non_joinable_bank_nevers_leak_a_price(self) -> None:
        pending = self.buat_bank("Bank Pending", kota="Depok", status=BankSampah.Status.PENDING)
        induk = self.buat_bank(
            "Induk XYZ", kota="Depok", jenis_organisasi=BankSampah.OrganizationType.INDUK
        )
        nonaktif = self.buat_bank("Bank Tutup", kota="Depok", is_active=False)
        response = self._fetch(
            banks=",".join(str(b.id) for b in (self.bank_a, pending, induk, nonaktif))
        )
        baris = {row["nama"]: row for row in response.data["perbandingan"]}
        for nama in ("Bank Pending", "Induk XYZ", "Bank Tutup"):
            self.assertEqual(baris[nama]["alasan"], "bukan_bank_bisa_gabung")
            self.assertIsNone(baris[nama]["harga_per_kg"])
        self.assertEqual(baris["Bank A"]["harga_per_kg"], "3000.00")

    def test_jenis_outside_the_requested_banks_is_422(self) -> None:
        bank_c = self.buat_bank("Bank C", kota="Bekasi")
        jenis_c = self.buat_jenis(bank_c, harga=1111)
        response = self._fetch(jenis=jenis_c, banks=str(self.bank_a.id))
        self.assertEqual(response.status_code, 422)

    def test_unauthenticated_is_401(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION="")
        self.assertEqual(self._fetch().status_code, 401)
