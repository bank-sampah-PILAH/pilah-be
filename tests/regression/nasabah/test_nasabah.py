"""Nasabah contracts: CRUD, filters, validation, isolation, edge inputs."""

from typing import Any

from api.models import BankSampah, Nasabah, Saldo
from tests.regression.helpers import RegressionTestCase, nasabah_payload


class NasabahRegressionTests(RegressionTestCase):
    def test_create_positive_contract(self) -> None:
        created = self.client.post("/api/v1/nasabah", nasabah_payload(), format="json")
        self.assertEqual(created.status_code, 201)
        for key in ("id", "kode", "nama", "no_hp", "alamat", "total_saldo"):
            self.assertIn(key, created.data)

    def test_create_rejects_empty_payload(self) -> None:
        self.assertGreaterEqual(self.client.post("/api/v1/nasabah", {}).status_code, 400)

    def test_create_rejects_bad_fields(self) -> None:
        cases: list[dict[str, Any]] = [
            {"nama": "AB"},  # shorter than 3 chars
            {"nama": "   "},  # whitespace-only
            {"nama": "x" * 101},  # longer than 100 chars
            {"kode": "   "},  # whitespace-only kode
            {"alamat": "pendek"},  # shorter than 10 chars
            {"jenis_kelamin": "other"},  # outside choices
            {"tanggal_lahir": "2999-01-01"},  # future birth date
        ]
        for override in cases:
            with self.subTest(override=override):
                response = self.client.post(
                    "/api/v1/nasabah", nasabah_payload(**override), format="json"
                )
                self.assertGreaterEqual(response.status_code, 400)

    def test_create_accepts_unicode_name(self) -> None:
        created = self.client.post(
            "/api/v1/nasabah", nasabah_payload(nama="Déwi Lestari 🌾"), format="json"
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["nama"], "Déwi Lestari 🌾")

    def test_create_normalizes_email(self) -> None:
        created = self.client.post(
            "/api/v1/nasabah", nasabah_payload(email="  BUDI@Example.COM "), format="json"
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["email"], "budi@example.com")

    def test_create_rejects_duplicate_phone(self) -> None:
        self.client.post("/api/v1/nasabah", nasabah_payload(), format="json")
        dup = self.client.post(
            "/api/v1/nasabah",
            nasabah_payload(
                kode="NAS-0002",
                nama="Siti Aminah",
                jenis_kelamin="perempuan",
                tanggal_lahir="1992-02-02",
                no_hp="081234567890",
                alamat="Jl. Mawar No. 12",
            ),
            format="json",
        )
        self.assertEqual(dup.status_code, 422)

    def test_list_is_paginated(self) -> None:
        response = self.client.get("/api/v1/nasabah")
        self.assertEqual(response.status_code, 200)
        self.assertIn("count", response.data)
        self.assertIn("results", response.data)

    def test_list_absurd_page_404s(self) -> None:
        self.assertEqual(self.client.get("/api/v1/nasabah?page=99999").status_code, 404)

    def test_search_and_status_filters(self) -> None:
        self.client.post("/api/v1/nasabah", nasabah_payload(), format="json")
        self.client.post(
            "/api/v1/nasabah", nasabah_payload(kode="NAS-0002", nama="Siti Aminah"), format="json"
        )
        found = self.client.get("/api/v1/nasabah?search=bud")
        self.assertEqual(found.data["count"], 1)
        # Single-char searches are ignored.
        all_rows = self.client.get("/api/v1/nasabah?search=x")
        self.assertEqual(all_rows.data["count"], 2)
        for status_filter, expected in (("menunggu", 0), ("ditolak", 0), ("aktif", 2)):
            with self.subTest(status_filter=status_filter):
                response = self.client.get(f"/api/v1/nasabah?status={status_filter}")
                self.assertEqual(response.data["count"], expected)

    def test_malformed_uuid_returns_404(self) -> None:
        for path in ("/api/v1/nasabah/not-a-uuid", "/api/v1/nasabah/not-a-uuid/saldo"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_update_flows(self) -> None:
        created = self.client.post("/api/v1/nasabah", nasabah_payload(), format="json")
        self.client.post("/api/v1/nasabah", nasabah_payload(kode="NAS-0002"), format="json")
        nid = created.data["id"]

        full = self.client.put(f"/api/v1/nasabah/{nid}", nasabah_payload(), format="json")
        self.assertEqual(full.status_code, 200)

        dup = self.client.put(
            f"/api/v1/nasabah/{nid}", nasabah_payload(kode="NAS-0002"), format="json"
        )
        self.assertEqual(dup.status_code, 422)

        partial = self.client.patch(f"/api/v1/nasabah/{nid}", {"nama": "Budi Baru"}, format="json")
        self.assertEqual(partial.status_code, 200)
        self.assertEqual(partial.data["nama"], "Budi Baru")

        detail = self.client.get(f"/api/v1/nasabah/{nid}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("ringkasan_transaksi", detail.data)

        self.client.patch(f"/api/v1/nasabah/{nid}/status", {"is_active": False}, format="json")
        frozen = self.client.put(f"/api/v1/nasabah/{nid}", nasabah_payload(), format="json")
        self.assertEqual(frozen.status_code, 403)

    def test_other_bank_detail_invisible(self) -> None:
        other_bank = BankSampah.objects.create(
            nama="Lain", alamat="Jl. Lain No. 10", kota="Depok", no_hp_pic="+628999999999"
        )
        other_nasabah = Nasabah.objects.create(
            bank_sampah=other_bank,
            nomor="NAS-9",
            nama="Orang Lain",
            no_hp="+628999999998",
            alamat="Jl. Lain No. 11",
        )
        Saldo.objects.create(nasabah=other_nasabah)
        self.assertEqual(self.client.get(f"/api/v1/nasabah/{other_nasabah.id}").status_code, 404)
