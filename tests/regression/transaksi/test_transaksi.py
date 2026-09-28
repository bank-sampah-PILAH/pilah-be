"""Transaksi contracts: create, filters, periodes, export, notifications."""

import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from django.utils import timezone

from api.models import BankSampah, JenisSampah, Nasabah, Saldo, Transaksi, User
from tests.regression.helpers import RegressionTestCase, gateway_env, twilio_env


class TransaksiRegressionTests(RegressionTestCase):
    def test_create_positive_contract(self) -> None:
        nasabah = self.make_nasabah()
        jenis_id = self.make_jenis()
        created = self.client.post(
            "/api/v1/transaksi",
            {
                "nasabah_id": str(nasabah.id),
                "items": [{"jenis_sampah_id": jenis_id, "berat": "2.500"}],
                "catatan": "Setoran rutin",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        for key in ("id", "total_nilai", "saldo_setelah_transaksi", "items"):
            self.assertIn(key, created.data)

    def test_create_rejects_bad_payloads(self) -> None:
        nasabah = self.make_nasabah()
        jenis_id = self.make_jenis()

        cases = [
            {},
            {"nasabah_id": str(nasabah.id), "items": []},
            {
                "nasabah_id": str(nasabah.id),
                "items": [{"jenis_sampah_id": jenis_id, "berat": "0"}],
            },
            {
                "nasabah_id": str(nasabah.id),
                "items": [{"jenis_sampah_id": jenis_id, "berat": "-2"}],
            },
            {
                "nasabah_id": str(nasabah.id),
                "items": [{"jenis_sampah_id": str(uuid.uuid4()), "berat": "1"}],
            },
            {
                "nasabah_id": str(uuid.uuid4()),
                "items": [{"jenis_sampah_id": jenis_id, "berat": "1"}],
            },
        ]
        for i, payload in enumerate(cases):
            with self.subTest(case=i):
                response = self.client.post("/api/v1/transaksi", payload, format="json")
                self.assertGreaterEqual(response.status_code, 400)

    def test_unknown_periode_is_ignored(self) -> None:
        # Unknown periode values fall through unfiltered (200), only a
        # dateless custom range is rejected.
        self.assertEqual(self.client.get("/api/v1/transaksi?periode=bogus").status_code, 200)
        self.assertGreaterEqual(
            self.client.get("/api/v1/transaksi?periode=custom").status_code, 400
        )

    def test_named_periodes_filter(self) -> None:
        self.make_transaksi()
        for periode in ("hari_ini", "minggu_ini", "bulan_ini", "bulan_lalu"):
            with self.subTest(periode=periode):
                response = self.client.get(f"/api/v1/transaksi?periode={periode}")
                self.assertEqual(response.status_code, 200)

    def test_custom_periode_needs_dates_and_format(self) -> None:
        self.assertGreaterEqual(
            self.client.get("/api/v1/transaksi?periode=custom").status_code, 400
        )
        bad_date = self.client.get(
            "/api/v1/transaksi?periode=custom&dari_tanggal=bogus&sampai_tanggal=2026-01-01"
        )
        self.assertGreaterEqual(bad_date.status_code, 400)

    def test_search_nasabah_and_custom_periode(self) -> None:
        self.make_transaksi()
        nasabah = Nasabah.objects.get(nomor="NAS-0001")
        found = self.client.get("/api/v1/transaksi?search=ahmad")
        self.assertEqual(found.data["count"], 1)
        by_nasabah = self.client.get(f"/api/v1/transaksi?nasabah_id={nasabah.id}")
        self.assertEqual(by_nasabah.data["count"], 1)
        today = timezone.localdate().isoformat()
        ranged = self.client.get(
            f"/api/v1/transaksi?periode=custom&dari_tanggal={today}&sampai_tanggal={today}"
        )
        self.assertEqual(ranged.status_code, 200)
        self.assertEqual(ranged.data["count"], 1)
        reversed_range = self.client.get(
            "/api/v1/transaksi?periode=custom&dari_tanggal=2026-02-01&sampai_tanggal=2026-01-01"
        )
        self.assertEqual(reversed_range.status_code, 400)

    def test_export_requires_data(self) -> None:
        self.assertGreaterEqual(self.client.get("/api/v1/transaksi/export").status_code, 400)

    def test_export_with_data(self) -> None:
        self.make_transaksi()
        response = self.client.get("/api/v1/transaksi/export?periode=bulan_ini")
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheet", response["Content-Type"])

    def test_export_labels_each_periode(self) -> None:
        self.make_transaksi()
        nasabah = Nasabah.objects.get(nomor="NAS-0001")
        last_month = timezone.localdate().replace(day=1) - timedelta(days=1)
        Transaksi.objects.create(
            bank_sampah=self.bank,
            nasabah=nasabah,
            dicatat_oleh=self.user,
            tanggal=timezone.make_aware(datetime.combine(last_month, time.min)),
            total_nilai=Decimal("1000.00"),
        )
        start = last_month.replace(day=1).isoformat()
        for params, expected in (
            ("?periode=hari_ini", 200),
            ("?periode=minggu_ini", 200),
            ("?periode=bulan_ini", 200),
            ("?periode=bulan_lalu", 200),
            (f"?periode=custom&dari_tanggal={start}&sampai_tanggal={last_month.isoformat()}", 200),
            ("?periode=custom&dari_tanggal=2020-01-01&sampai_tanggal=2020-01-02", 400),
        ):
            with self.subTest(params=params):
                response = self.client.get(f"/api/v1/transaksi/export{params}")
                self.assertEqual(response.status_code, expected)

    def test_other_bank_object_invisible(self) -> None:
        self.make_nasabah()
        other_bank = BankSampah.objects.create(
            nama="Lain", alamat="Jl. Lain No. 10", kota="Depok", no_hp_pic="+628999999999"
        )
        other_user = User.objects.create_user(
            email="lain@example.com",
            nama="Lain",
            bank_sampah=other_bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        self.auth_as(other_user)
        other_nasabah = Nasabah.objects.create(
            bank_sampah=other_bank,
            nomor="NAS-9",
            nama="Orang Lain",
            no_hp="+628999999998",
            alamat="Jl. Lain No. 11",
        )
        Saldo.objects.create(nasabah=other_nasabah)
        other_jenis = JenisSampah.objects.create(
            bank_sampah=other_bank,
            nomor="X-1",
            nama_sampah="Kaca",
            kategori="kaca",
            harga_per_kg=1000,
        )
        created = self.client.post(
            "/api/v1/transaksi",
            {
                "nasabah_id": str(other_nasabah.id),
                "items": [{"jenis_sampah_id": str(other_jenis.id), "berat": "1"}],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.auth_as(self.user)
        self.assertEqual(
            self.client.get(f"/api/v1/transaksi/{created.data['id']}").status_code, 404
        )

    def test_list_embeds_saldo_helpers(self) -> None:
        self.make_transaksi()
        response = self.client.get("/api/v1/transaksi")
        self.assertEqual(response.status_code, 200)
        first = response.data["results"][0]
        for key in ("nasabah_inisial", "jenis_sampah_utama", "total_berat_kg"):
            self.assertIn(key, first)

    # --- WhatsApp notifications across providers ---

    def test_notify_twilio_success_and_failure(self) -> None:
        tid = self.make_transaksi()
        ok = Mock(status_code=201)
        ok.json = Mock(return_value={"sid": "SM1"})
        with twilio_env():
            with patch("api.services.requests.post", return_value=ok):
                response = self.client.post(f"/api/v1/transaksi/{tid}/notify-wa", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])

        fail = Mock(status_code=500)
        fail.json = Mock(return_value={"message": "down"})
        fail.text = "down"
        with twilio_env():
            with patch("api.services.requests.post", return_value=fail):
                response = self.client.post(f"/api/v1/transaksi/{tid}/notify-wa", {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_notify_twilio_incomplete_config(self) -> None:
        tid = self.make_transaksi()
        with twilio_env(TWILIO_AUTH_TOKEN="", TWILIO_WHATSAPP_FROM=""):
            response = self.client.post(f"/api/v1/transaksi/{tid}/notify-wa", {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])

    def test_notify_twilio_missing_sender(self) -> None:
        tid = self.make_transaksi()
        with twilio_env(TWILIO_WHATSAPP_FROM=""):
            response = self.client.post(f"/api/v1/transaksi/{tid}/notify-wa", {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_notify_gateway_success_failure_and_error(self) -> None:
        tid = self.make_transaksi()
        ok = Mock(status_code=200)
        with gateway_env():
            with patch("api.services.requests.post", return_value=ok):
                response = self.client.post(f"/api/v1/transaksi/{tid}/notify-wa", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["provider"], "gateway")

        fail = Mock(status_code=502, text="bad gateway")
        with gateway_env():
            with patch("api.services.requests.post", return_value=fail):
                response = self.client.post(f"/api/v1/transaksi/{tid}/notify-wa", {}, format="json")
        self.assertEqual(response.status_code, 400)

        with gateway_env():
            with patch(
                "api.services.requests.post",
                side_effect=requests.RequestException("down"),
            ):
                response = self.client.post(f"/api/v1/transaksi/{tid}/notify-wa", {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_notify_without_any_config(self) -> None:
        tid = self.make_transaksi()
        with twilio_env(TWILIO_ACCOUNT_SID="", TWILIO_AUTH_TOKEN=""):
            response = self.client.post(f"/api/v1/transaksi/{tid}/notify-wa", {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])

    def test_notify_nasabah_without_phone_fails(self) -> None:
        nasabah = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-9",
            nama="Tanpa HP",
            no_hp="",
            alamat="Jl. Panjang Sekali No. 9",
        )
        Saldo.objects.create(nasabah=nasabah)
        jenis_id = self.make_jenis()
        created = self.client.post(
            "/api/v1/transaksi",
            {
                "nasabah_id": str(nasabah.id),
                "items": [{"jenis_sampah_id": jenis_id, "berat": "1"}],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        with twilio_env():
            response = self.client.post(
                f"/api/v1/transaksi/{created.data['id']}/notify-wa", {}, format="json"
            )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
