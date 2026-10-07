from datetime import datetime
from typing import Any
from unittest.mock import patch

from rest_framework.response import Response
from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, Pencairan, Transaksi, User


class ActivityHistoryTests(APITestCase):
    url = "/api/v1/aktivitas"

    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(nama="Melati", no_hp_pic="081200")
        self.manager = User.objects.create_user(
            email="manager@example.test",
            nama="Manager",
            bank_sampah=self.bank,
            role=User.Role.PENGELOLA,
            is_profile_complete=True,
        )
        self.user = User.objects.create_user(
            email="member@example.test",
            nama="Siti",
            role=User.Role.NASABAH,
            is_profile_complete=True,
        )
        self.member = Nasabah.objects.create(
            bank_sampah=self.bank,
            user=self.user,
            nomor="001",
            nama="Siti",
            alamat="Depok",
            no_hp="081201",
        )
        self.setoran = self.deposit(self.member, "2026-10-07T08:00:00+07:00")
        self.payout = Pencairan.objects.create(
            nasabah=self.member,
            bank_sampah=self.bank,
            dicatat_oleh=self.manager,
            tanggal=datetime.fromisoformat("2026-10-07T09:00:00+07:00"),
            nominal=3000,
            metode="tunai",
            saldo_sebelum=10000,
            saldo_sesudah=7000,
        )
        self.client.force_authenticate(self.manager)

    def deposit(self, member: Nasabah, date: str) -> Transaksi:
        return Transaksi.objects.create(
            nasabah=member,
            bank_sampah=member.bank_sampah,
            dicatat_oleh=self.manager,
            tanggal=datetime.fromisoformat(date),
            total_nilai=10000,
        )

    def get(self, **params: Any) -> Response:
        return self.client.get(self.url, {"periode": "semua", **params})

    def test_paginate_combined_feed_not_each_source(self) -> None:
        response = self.get(page_size=1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["results"][0]["tipe"], "pencairan")
        self.assertEqual(response.data["results"][0]["data"]["id"], str(self.payout.id))
        second = self.get(page_size=1, page=2)
        self.assertIsNone(second.data["next"])
        self.assertEqual(second.data["results"][0]["data"]["id"], str(self.setoran.id))

    def test_type_and_custom_range_filter_both_sources(self) -> None:
        self.deposit(self.member, "2026-09-01T12:00:00+07:00")
        response = self.get(
            periode="custom", dari_tanggal="2026-10-07", sampai_tanggal="2026-10-07"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        for kind in ("setoran", "pencairan"):
            filtered = self.get(tipe=kind)
            self.assertTrue(all(row["tipe"] == kind for row in filtered.data["results"]))

    def test_search_runs_before_pagination(self) -> None:
        other = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="002",
            nama="Budi",
            email="budi@example.test",
            alamat="Depok",
            no_hp="081202",
        )
        self.deposit(other, "2026-10-07T10:00:00+07:00")
        response = self.get(search="Siti", page_size=1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["results"][0]["data"]["nasabah_nama"], "Siti")

    def test_bank_isolation_and_role_gate(self) -> None:
        other_bank = BankSampah.objects.create(nama="Mawar", no_hp_pic="081203")
        foreign = Nasabah.objects.create(
            bank_sampah=other_bank, nomor="001", nama="Siti", alamat="Bogor", no_hp="081204"
        )
        self.deposit(foreign, "2026-10-07T12:00:00+07:00")
        Pencairan.objects.create(
            nasabah=foreign,
            bank_sampah=other_bank,
            dicatat_oleh=self.manager,
            tanggal=datetime.fromisoformat("2026-10-07T13:00:00+07:00"),
            nominal=1000,
            metode="tunai",
            saldo_sebelum=10000,
            saldo_sesudah=9000,
        )
        self.assertEqual(self.get().data["count"], 2)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.get().status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.get().status_code, 401)

    def test_invalid_filters_do_not_silently_return_all_data(self) -> None:
        self.assertEqual(self.get(tipe="unknown").status_code, 422)
        self.assertEqual(self.get(periode="unknown").status_code, 422)
        self.assertEqual(self.get(periode="custom").status_code, 422)
        self.assertEqual(
            self.get(
                periode="custom", dari_tanggal="2026-10-08", sampai_tanggal="2026-10-07"
            ).status_code,
            400,
        )

    def test_empty_result_and_out_of_range_page(self) -> None:
        self.assertEqual(self.get(search="absent").data["results"], [])
        self.assertEqual(self.get(page=100).status_code, 404)

    def test_calendar_periods_and_rolling_month_ranges(self) -> None:
        self.deposit(self.member, "2026-09-08T12:00:00+07:00")
        self.deposit(self.member, "2026-09-06T12:00:00+07:00")
        now = datetime.fromisoformat("2026-10-07T12:00:00+07:00")
        with patch("django.utils.timezone.now", return_value=now):
            for period, expected in (
                ("hari_ini", 2),
                ("minggu_ini", 2),
                ("bulan_ini", 2),
                ("bulan_lalu", 2),
                ("1_bulan", 3),
                ("3_bulan", 4),
                ("6_bulan", 4),
                ("12_bulan", 4),
            ):
                with self.subTest(period=period):
                    response = self.get(periode=period)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.data["count"], expected)

    def test_end_date_includes_last_local_minute(self) -> None:
        self.deposit(self.member, "2026-10-07T23:59:59+07:00")
        self.deposit(self.member, "2026-10-08T00:00:00+07:00")
        response = self.get(
            periode="custom", dari_tanggal="2026-10-07", sampai_tanggal="2026-10-07"
        )
        self.assertEqual(response.data["count"], 3)

    def test_rolling_month_clamps_to_last_day_of_short_month(self) -> None:
        self.deposit(self.member, "2026-02-28T23:59:00+07:00")
        self.deposit(self.member, "2026-02-27T23:59:00+07:00")
        with patch(
            "django.utils.timezone.now",
            return_value=datetime.fromisoformat("2026-03-31T12:00:00+07:00"),
        ):
            response = self.get(periode="1_bulan")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_nasabah_opt_in_feed_uses_membership_isolation(self) -> None:
        other_bank = BankSampah.objects.create(nama="Mawar", no_hp_pic="081203")
        foreign = Nasabah.objects.create(
            bank_sampah=other_bank,
            user=self.user,
            nomor="001",
            nama="Siti",
            alamat="Bogor",
            no_hp="081204",
        )
        self.deposit(foreign, "2026-10-07T12:00:00+07:00")
        self.client.force_authenticate(self.user)
        response = self.client.get(
            "/api/v1/nasabah/me/riwayat",
            {"keanggotaan_id": str(self.member.id), "periode": "semua", "tipe": "semua"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            {row["tipe"] for row in response.data["results"]}, {"setoran", "pencairan"}
        )
