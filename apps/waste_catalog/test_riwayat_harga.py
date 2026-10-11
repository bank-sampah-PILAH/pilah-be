"""PIL-331: riwayat versi harga per jenis sampah untuk pengurus."""

from datetime import timedelta
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from api.models import HargaSampah
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
