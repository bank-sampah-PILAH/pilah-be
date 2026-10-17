"""PIL-331: riwayat versi harga per jenis sampah untuk pengurus."""

from datetime import timedelta
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from api.models import BankSampah, HargaSampah, JenisSampah, User
from apps.waste_catalog.test_harga_api import HargaApiTestCase


class RiwayatHargaTests(HargaApiTestCase):
    def riwayat(self, jenis_id: str) -> Any:
        return self.client.get(f"/api/v1/jenis-sampah/{jenis_id}/harga")

    def ubah_harga(self, jenis_id: str, payload: dict[str, str]) -> None:
        response = self.client.post(
            f"/api/v1/jenis-sampah/{jenis_id}/harga", payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

    def jadwalkan(self, jenis_id: str, harga: str, hari: int) -> None:
        berlaku_mulai = (timezone.now() + timedelta(days=hari)).isoformat()
        self.ubah_harga(jenis_id, {"harga_per_kg": harga, "berlaku_mulai": berlaku_mulai})

    def test_lists_every_version_newest_first_with_price_unit_start_and_author(self) -> None:
        jenis = self.buat_jenis(harga=3500)
        self.jadwalkan(jenis["id"], "5000", hari=3)

        response = self.riwayat(jenis["id"])

        self.assertEqual(response.status_code, 200, response.data)
        versi = HargaSampah.objects.filter(jenis_sampah_id=jenis["id"]).order_by("-berlaku_mulai")
        baris = response.data["results"]
        self.assertEqual([b["harga_per_kg"] for b in baris], ["5000.00", "3500.00"])
        self.assertEqual(
            [parse_datetime(b["berlaku_mulai"]) for b in baris],
            [v.berlaku_mulai for v in versi],
        )
        self.assertEqual({b["satuan"] for b in baris}, {"kg"})
        self.assertEqual({b["dibuat_oleh"] for b in baris}, {"Ibu Sari"})

    def test_marks_each_version_scheduled_current_previous_or_replaced(self) -> None:
        # Mengoreksi harga terjadwal adalah versi baru dengan berlaku_mulai yang
        # sama; versi yang dikoreksi tidak akan pernah berlaku, jadi ditandai
        # "digantikan", bukan "terjadwal".
        jenis = self.buat_jenis(harga=3500)
        self.ubah_harga(jenis["id"], {"harga_per_kg": "4000"})
        lusa = (timezone.now() + timedelta(days=2)).isoformat()
        self.ubah_harga(jenis["id"], {"harga_per_kg": "5000", "berlaku_mulai": lusa})
        self.ubah_harga(jenis["id"], {"harga_per_kg": "5500", "berlaku_mulai": lusa})

        baris = self.riwayat(jenis["id"]).data["results"]

        self.assertEqual(
            [(b["harga_per_kg"], b["status"]) for b in baris],
            [
                ("5500.00", "terjadwal"),
                ("5000.00", "digantikan"),
                ("4000.00", "berlaku"),
                ("3500.00", "sebelumnya"),
            ],
        )

    def test_only_the_owning_banks_pengurus_can_read_the_history(self) -> None:
        # OWASP A01: harga bank lain tidak bocor lewat id jenis sampah yang ditebak.
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
        self.assertEqual(self.riwayat(jenis["id"]).status_code, 404)
        self.auth_as(nasabah)
        self.assertEqual(self.riwayat(jenis["id"]).status_code, 403)

    def test_jenis_without_any_version_has_an_empty_history(self) -> None:
        jenis = JenisSampah.objects.create(
            bank_sampah=self.bank, nomor="LGM-001", nama_sampah="Besi"
        )

        response = self.riwayat(str(jenis.id))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["results"], [])

    def test_version_without_an_author_shows_no_name(self) -> None:
        # Versi hasil backfill migrasi 0021 tidak punya pembuat.
        jenis = JenisSampah.objects.create(
            bank_sampah=self.bank, nomor="LGM-001", nama_sampah="Besi"
        )
        HargaSampah.objects.create(
            jenis_sampah=jenis,
            bank_sampah=self.bank,
            harga_per_kg=2000,
            berlaku_mulai=timezone.now(),
        )

        baris = self.riwayat(str(jenis.id)).data["results"]

        self.assertEqual([(b["dibuat_oleh"], b["status"]) for b in baris], [(None, "berlaku")])
