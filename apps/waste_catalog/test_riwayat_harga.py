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

    def jadwalkan(self, jenis_id: str, harga: str, hari: int) -> None:
        response = self.client.post(
            f"/api/v1/jenis-sampah/{jenis_id}/harga",
            {
                "harga_per_kg": harga,
                "berlaku_mulai": (timezone.now() + timedelta(days=hari)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

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
