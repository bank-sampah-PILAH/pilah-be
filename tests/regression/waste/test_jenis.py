"""Waste-catalog contracts: jenis sampah CRUD, filters, validation, isolation."""

from typing import Any

from api.models import BankSampah, JenisSampah
from tests.regression.helpers import RegressionTestCase


def _jenis_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kode": "PLS-001",
        "nama_sampah": "Plastik PET",
        "kategori": "plastik",
        "deskripsi": "Botol bening",
        "harga_per_kg": 3500,
    }
    payload.update(overrides)
    return payload


class JenisRegressionTests(RegressionTestCase):
    def test_create_rejects_bad_fields(self) -> None:
        cases: list[dict[str, Any]] = [
            {"nama_sampah": ""},
            {"harga_per_kg": -100},
            {"harga_per_kg": 0},
            {"harga_per_kg": 1000000000},
            {"deskripsi": "x" * 201},
            {"nama_sampah": "A"},
            {"kode": "   "},
            {"kategori": "not-a-category"},
        ]
        for override in cases:
            with self.subTest(override=str(override)[:30]):
                response = self.client.post(
                    "/api/v1/jenis-sampah", _jenis_payload(**override), format="json"
                )
                self.assertGreaterEqual(response.status_code, 400)

    def test_fields_stripped_on_create(self) -> None:
        created = self.client.post(
            "/api/v1/jenis-sampah",
            _jenis_payload(kode="  PLS-001 ", nama_sampah="  Plastik PET "),
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["kode"], "PLS-001")

    def test_other_bank_object_invisible(self) -> None:
        other_bank = BankSampah.objects.create(
            nama="Lain", alamat="Jl. Lain No. 10", kota="Depok", no_hp_pic="+628999999999"
        )
        other_jenis = JenisSampah.objects.create(
            bank_sampah=other_bank,
            nomor="X-1",
            nama_sampah="Kaca",
            kategori="kaca",
            harga_per_kg=1000,
        )
        self.assertEqual(self.client.get(f"/api/v1/jenis-sampah/{other_jenis.id}").status_code, 404)

    def test_update_status_and_filters(self) -> None:
        jenis_id = self.make_jenis()
        updated = self.client.put(
            "/api/v1/jenis-sampah/" + jenis_id,
            {
                "kode": "PLS-001",
                "nama_sampah": "Plastik Campur",
                "kategori": "plastik",
                "harga_per_kg": 4000,
            },
            format="json",
        )
        self.assertEqual(updated.status_code, 200)

        self.make_jenis("KRT-001")
        dup = self.client.put(
            "/api/v1/jenis-sampah/" + jenis_id,
            {
                "kode": "KRT-001",
                "nama_sampah": "Plastik Campur",
                "kategori": "plastik",
                "harga_per_kg": 4000,
            },
            format="json",
        )
        self.assertEqual(dup.status_code, 422)

        toggled = self.client.patch(
            f"/api/v1/jenis-sampah/{jenis_id}/status", {"is_active": False}, format="json"
        )
        self.assertEqual(toggled.status_code, 200)
        self.assertFalse(toggled.data["is_active"])
        self.assertIn("message", toggled.data)

        off = self.client.get("/api/v1/jenis-sampah?status=tidak_aktif")
        self.assertEqual(off.data["count"], 1)
        # Default status filter is aktif, so the deactivated row is excluded.
        by_cat = self.client.get("/api/v1/jenis-sampah?kategori=plastik")
        self.assertEqual(by_cat.data["count"], 1)
        by_cat_off = self.client.get("/api/v1/jenis-sampah?kategori=plastik&status=tidak_aktif")
        self.assertEqual(by_cat_off.data["count"], 1)
        by_search = self.client.get("/api/v1/jenis-sampah?search=pet")
        self.assertGreaterEqual(by_search.data["count"], 1)
