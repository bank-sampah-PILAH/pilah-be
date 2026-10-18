"""PIL-305: satuan per jenis sampah, menggantikan "kg" yang dipatok di serializer."""

from typing import Any

from api.models import JenisSampah
from apps.waste_catalog.test_harga_api import HargaApiTestCase


class SatuanJenisSampahTests(HargaApiTestCase):
    def buat(self, **extra: Any) -> Any:
        payload: dict[str, Any] = {
            "kode": "PLS-001",
            "nama_sampah": "Plastik PET",
            "kategori": "plastik",
            "harga_per_kg": 3500,
        }
        payload.update(extra)
        return self.client.post("/api/v1/jenis-sampah", payload, format="json")

    def test_satuan_yang_dikirim_tersimpan_dan_dikembalikan(self) -> None:
        response = self.buat(satuan="pcs")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["satuan"], "pcs")
        self.assertEqual(JenisSampah.objects.get(id=response.data["id"]).satuan, "pcs")

    def test_satuan_di_luar_daftar_ditolak(self) -> None:
        response = self.buat(satuan="ton")

        self.assertEqual(response.status_code, 422, response.data)
        self.assertIn("satuan", response.data["errors"])
        self.assertFalse(JenisSampah.objects.filter(nomor="PLS-001").exists())

    def test_tanpa_satuan_tetap_kg_untuk_klien_lama(self) -> None:
        """Aplikasi yang sudah terpasang belum mengirim satuan; jangan dipaksa."""
        response = self.buat()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["satuan"], "kg")

    def test_satuan_dapat_diubah_lewat_put(self) -> None:
        jenis = self.buat(satuan="kg").data

        response = self.client.put(
            f"/api/v1/jenis-sampah/{jenis['id']}",
            {
                "kode": "PLS-001",
                "nama_sampah": "Plastik PET",
                "kategori": "plastik",
                "satuan": "ikat",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["satuan"], "ikat")

    def test_hapus_jenis_ditolak_dengan_saran_menonaktifkan(self) -> None:
        jenis = self.buat().data

        response = self.client.delete(f"/api/v1/jenis-sampah/{jenis['id']}")

        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("nonaktifkan", str(response.data).lower())
        self.assertTrue(JenisSampah.objects.filter(id=jenis["id"]).exists())

    def test_riwayat_harga_memakai_satuan_jenisnya_bukan_kg(self) -> None:
        jenis = self.buat(satuan="karung").data

        riwayat = self.client.get(f"/api/v1/jenis-sampah/{jenis['id']}/harga")

        self.assertEqual(riwayat.status_code, 200, riwayat.data)
        self.assertEqual({baris["satuan"] for baris in riwayat.data["results"]}, {"karung"})
