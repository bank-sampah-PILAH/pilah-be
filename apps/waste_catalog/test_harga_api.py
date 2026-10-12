"""PIL-304: API harga jenis sampah ber-versi untuk pengurus."""

from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, HargaSampah, User

WIB = ZoneInfo("Asia/Jakarta")


class HargaApiTestCase(APITestCase):
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
        self.auth_as(self.user)

    def auth_as(self, user: User) -> None:
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def buat_jenis(self, harga: int = 3500, kode: str = "PLS-001") -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/jenis-sampah",
            {
                "kode": kode,
                "nama_sampah": "Plastik PET",
                "kategori": "plastik",
                "harga_per_kg": harga,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return dict(response.data)


class BuatJenisSampahTests(HargaApiTestCase):
    def test_initial_price_is_recorded_as_a_version_starting_now_with_its_author(self) -> None:
        sebelum = timezone.now()

        jenis = self.buat_jenis(harga=3500)

        versi = HargaSampah.objects.get(jenis_sampah_id=jenis["id"])
        self.assertEqual(versi.harga_per_kg, 3500)
        self.assertEqual(versi.bank_sampah, self.bank)
        self.assertEqual(versi.dibuat_oleh, self.user)
        self.assertGreaterEqual(versi.berlaku_mulai, sebelum - timedelta(seconds=1))
        self.assertLessEqual(versi.berlaku_mulai, timezone.now())

    def test_a_new_jenis_needs_a_price(self) -> None:
        response = self.client.post(
            "/api/v1/jenis-sampah",
            {"kode": "PLS-001", "nama_sampah": "Plastik PET", "kategori": "plastik"},
            format="json",
        )

        self.assertEqual(response.status_code, 422, response.data)
        self.assertIn("harga_per_kg", response.data["errors"])
        self.assertFalse(HargaSampah.objects.exists())


class DaftarJenisSampahTests(HargaApiTestCase):
    def test_list_query_count_does_not_grow_with_the_number_of_jenis(self) -> None:
        # Aplikasi memuat daftar harga dengan page_size=100; harga berlaku dan
        # terjadwal tidak boleh membuat satu query per jenis.
        def hitung_query() -> int:
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get("/api/v1/jenis-sampah", {"page_size": 100})
            self.assertEqual(response.status_code, 200)
            return len(queries)

        self.buat_jenis(kode="PLS-001")
        satu_jenis = hitung_query()
        for nomor in range(2, 6):
            jenis = self.buat_jenis(kode=f"PLS-00{nomor}")
            self.client.post(
                f"/api/v1/jenis-sampah/{jenis['id']}/harga",
                {
                    "harga_per_kg": "5000",
                    "berlaku_mulai": (timezone.now() + timedelta(days=2)).isoformat(),
                },
                format="json",
            )

        self.assertEqual(hitung_query(), satu_jenis)


class EditJenisSampahTests(HargaApiTestCase):
    def edit(self, jenis_id: str, harga: str) -> Any:
        return self.client.put(
            f"/api/v1/jenis-sampah/{jenis_id}",
            {
                "kode": "PLS-001",
                "nama_sampah": "Plastik PET Bening",
                "kategori": "plastik",
                "harga_per_kg": harga,
            },
            format="json",
        )

    def test_edit_from_older_app_builds_records_a_changed_price_as_a_version(self) -> None:
        # Aplikasi lama masih mengirim harga lewat PUT. Harga yang berubah
        # dicatat sebagai versi baru yang berlaku sekarang, harga yang sama
        # tidak menambah versi.
        jenis = self.buat_jenis(harga=3500)

        sama = self.edit(jenis["id"], "3500")
        berubah = self.edit(jenis["id"], "4000")

        self.assertEqual(sama.status_code, 200, sama.data)
        self.assertEqual(berubah.status_code, 200, berubah.data)
        self.assertEqual(berubah.data["harga_per_kg"], "4000.00")
        versi = HargaSampah.objects.filter(jenis_sampah_id=jenis["id"]).order_by("id")
        self.assertEqual([v.harga_per_kg for v in versi], [3500, 4000])
        self.assertEqual(versi.last().dibuat_oleh, self.user)  # type: ignore[union-attr]


class UbahHargaTests(HargaApiTestCase):
    def ubah_harga(self, jenis_id: str, payload: dict[str, Any]) -> Any:
        return self.client.post(f"/api/v1/jenis-sampah/{jenis_id}/harga", payload, format="json")

    def test_price_without_berlaku_mulai_takes_effect_now(self) -> None:
        jenis = self.buat_jenis(harga=3500)

        response = self.ubah_harga(jenis["id"], {"harga_per_kg": "4000"})

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["harga_per_kg"], "4000.00")
        detail = self.client.get(f"/api/v1/jenis-sampah/{jenis['id']}")
        self.assertEqual(detail.data["harga_per_kg"], "4000.00")
        terbaru = HargaSampah.objects.filter(jenis_sampah_id=jenis["id"]).latest("id")
        self.assertEqual(terbaru.dibuat_oleh, self.user)

    def test_future_price_is_scheduled_and_the_current_price_stays(self) -> None:
        jenis = self.buat_jenis(harga=3500)
        awal = HargaSampah.objects.get(jenis_sampah_id=jenis["id"]).berlaku_mulai
        # Tengah malam waktu setempat (WIB) yang dikirim aplikasi, lengkap dengan offset.
        tiga_hari_lagi = (timezone.now() + timedelta(days=3)).astimezone(WIB)
        tengah_malam = tiga_hari_lagi.replace(hour=0, minute=0, second=0, microsecond=0)

        response = self.ubah_harga(
            jenis["id"], {"harga_per_kg": "5000", "berlaku_mulai": tengah_malam.isoformat()}
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["harga_per_kg"], "3500.00")
        self.assertEqual(parse_datetime(response.data["harga_berlaku_mulai"]), awal)
        terjadwal = response.data["harga_terjadwal"]
        self.assertEqual(terjadwal["harga_per_kg"], "5000.00")
        self.assertEqual(parse_datetime(terjadwal["berlaku_mulai"]), tengah_malam)

    def test_rejects_backdated_far_future_or_offsetless_berlaku_mulai(self) -> None:
        # BR-03: perubahan harga tidak berlaku surut. Waktu tanpa offset tidak
        # dapat dipastikan zona waktunya, jadi ditolak alih-alih ditebak.
        jenis = self.buat_jenis(harga=3500)
        sekarang = timezone.now().astimezone(WIB)
        cases = {
            "kemarin": (sekarang - timedelta(days=1)).isoformat(),
            "lebih dari setahun lagi": (sekarang + timedelta(days=367)).isoformat(),
            "tanpa offset": (sekarang + timedelta(days=2)).replace(tzinfo=None).isoformat(),
        }
        for nama, berlaku_mulai in cases.items():
            with self.subTest(nama):
                response = self.ubah_harga(
                    jenis["id"], {"harga_per_kg": "5000", "berlaku_mulai": berlaku_mulai}
                )
                self.assertEqual(response.status_code, 422, response.data)
                self.assertIn("berlaku_mulai", response.data["errors"])
        self.assertEqual(HargaSampah.objects.filter(jenis_sampah_id=jenis["id"]).count(), 1)

    def test_only_the_owning_banks_pengurus_can_change_a_price(self) -> None:
        jenis = self.buat_jenis(harga=3500)
        bank_lain = BankSampah.objects.create(
            nama="Bank Sampah Kenanga",
            alamat="Bogor",
            kota="Bogor",
            no_hp_pic="+628123456782",
            status=BankSampah.Status.ACTIVE,
        )
        pengurus_lain = User.objects.create_user(
            email="lain@example.com",
            nama="Pengurus Lain",
            bank_sampah=bank_lain,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        nasabah = User.objects.create_user(
            email="nasabah@example.com",
            nama="Ayu",
            role=User.Role.NASABAH,
            is_profile_complete=True,
        )

        self.auth_as(pengurus_lain)
        self.assertEqual(self.ubah_harga(jenis["id"], {"harga_per_kg": "1"}).status_code, 404)
        self.auth_as(nasabah)
        self.assertEqual(self.ubah_harga(jenis["id"], {"harga_per_kg": "1"}).status_code, 403)
        self.assertEqual(HargaSampah.objects.filter(jenis_sampah_id=jenis["id"]).count(), 1)
