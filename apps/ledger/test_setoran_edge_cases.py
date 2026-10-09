import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from django.db import IntegrityError
from rest_framework.test import APITestCase

from api.models import BankSampah, JenisSampah, Nasabah, Transaksi, User
from apps.ledger.services import TransactionService
from apps.ledger.views import TransaksiViewSet
from apps.waste_catalog.api import buat_jenis_sampah


class SetoranEdgeCaseTests(APITestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(
            nama="Bank Ledger", alamat="Depok", kota="Depok", no_hp_pic="+628123456789"
        )
        self.pengelola = User.objects.create_user(
            email="ledger@example.test",
            nama="Pengelola",
            bank_sampah=self.bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        self.nasabah = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-0001",
            nama="Budi",
            no_hp="+628111111111",
            alamat="Jl. A",
        )
        self.jenis = buat_jenis_sampah(
            bank_sampah=self.bank, nomor="PET", nama_sampah="Botol PET", harga_per_kg=Decimal(3000)
        )
        self.client.force_authenticate(self.pengelola)
        self.payload = {
            "nasabah_id": str(self.nasabah.id),
            "items": [{"jenis_sampah_id": str(self.jenis.id), "berat": "2.000"}],
        }

    def _post(self, **headers: Any) -> object:
        return self.client.post("/api/v1/transaksi", self.payload, format="json", **headers)

    def test_waste_type_without_a_price_cannot_be_deposited(self) -> None:
        # Sejak PIL-304 harga tidak bisa 0 (dicek database); "belum ada harga"
        # berarti jenis belum punya versi harga yang berlaku.
        tanpa_harga = JenisSampah.objects.create(
            bank_sampah=self.bank, nomor="KRT", nama_sampah="Kardus"
        )
        self.payload["items"] = [{"jenis_sampah_id": str(tanpa_harga.id), "berat": "2.000"}]

        response = self._post()

        self.assertEqual(response.status_code, 422)  # type: ignore[attr-defined]
        self.assertIn("Harga jenis sampah belum diatur", str(response.data))  # type: ignore[attr-defined]
        self.assertFalse(Transaksi.objects.exists())

    def test_idempotency_key_must_be_a_version_four_uuid(self) -> None:
        response = self._post(HTTP_IDEMPOTENCY_KEY=str(uuid.uuid1()))

        self.assertEqual(response.status_code, 400)  # type: ignore[attr-defined]
        self.assertFalse(Transaksi.objects.exists())

    def test_database_conflict_without_idempotency_key_is_not_swallowed(self) -> None:
        with (
            patch.object(TransactionService, "create_setoran", side_effect=IntegrityError("x")),
            self.assertRaises(IntegrityError),
        ):
            self._post()

    def test_database_conflict_with_unknown_idempotency_key_is_not_swallowed(self) -> None:
        with (
            patch.object(TransactionService, "create_setoran", side_effect=IntegrityError("x")),
            self.assertRaises(IntegrityError),
        ):
            self._post(HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))

    def test_export_rejects_a_custom_range_that_ends_before_it_starts(self) -> None:
        response = self.client.get(
            "/api/v1/transaksi/export",
            {"periode": "custom", "dari_tanggal": "2026-02-02", "sampai_tanggal": "2026-02-01"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Tanggal akhir", response.data["error"])

    def test_list_returns_a_plain_array_when_pagination_is_disabled(self) -> None:
        self._post()

        with patch.object(TransaksiViewSet, "pagination_class", None):
            response = self.client.get("/api/v1/transaksi")

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 1)
