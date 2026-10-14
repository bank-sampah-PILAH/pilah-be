"""Dashboard contracts: stats, recent transactions, reporting, WA template."""

from datetime import datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from api.models import BankSampah, DetailTransaksi, HargaSampah, JenisSampah, Nasabah, Pencairan, Transaksi, User
from tests.regression.helpers import RegressionTestCase


class DashboardRegressionTests(RegressionTestCase):
    def _make_setoran(self, *, nasabah_kode: str, jenis_kode: str, berat: str = "2.500") -> str:
        nasabah = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor=nasabah_kode,
            nama="Dashboard test nasabah",
            alamat="Jl. Test",
            no_hp=f"+628123456{nasabah_kode[-3:]}",
            email=f"{nasabah_kode.lower()}@example.com",
        )
        jenis_sampah_id = self.make_jenis(jenis_kode)
        response = self.client.post(
            "/api/v1/transaksi",
            {
                "nasabah_id": str(nasabah.id),
                "items": [{"jenis_sampah_id": jenis_sampah_id, "berat": berat}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        result: str = response.data["id"]
        return result

    def test_stats_contract(self) -> None:
        response = self.client.get("/api/v1/dashboard/stats")
        self.assertEqual(response.status_code, 200)
        for key in (
            "bank_sampah_nama",
            "pengelola_nama",
            "periode",
            "nasabah_aktif",
            "transaksi_bulan_ini",
            "total_sampah_kg_bulan_ini",
            "total_nilai_bulan_ini",
        ):
            self.assertIn(key, response.data)

    def test_stats_reflect_new_data(self) -> None:
        self.make_transaksi()
        response = self.client.get("/api/v1/dashboard/stats")
        self.assertGreaterEqual(response.data["nasabah_aktif"], 1)
        self.assertGreaterEqual(response.data["transaksi_bulan_ini"], 1)

    def test_recent_transactions_contract(self) -> None:
        response = self.client.get("/api/v1/dashboard/recent-transactions")
        self.assertEqual(response.status_code, 200)
        self.assertIn("transactions", response.data)
        self.assertLessEqual(len(response.data["transactions"]), 3)

    def test_operational_trends_returns_aligned_zero_filled_periods(self) -> None:
        transaction_id = self.make_transaksi()
        Transaksi.objects.filter(pk=transaction_id).update(
            tanggal=timezone.make_aware(datetime(2024, 1, 3, 12))
        )
        response = self.client.get(
            "/api/v1/dashboard/operational-trends",
            {"start_date": "2024-01-03", "end_date": "2024-01-14", "granularity": "week"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["granularity"], "week")
        self.assertEqual(
            [b["period_start"] for b in response.data["buckets"]], ["2024-01-01", "2024-01-08"]
        )
        self.assertEqual(response.data["buckets"][0]["setoran_count"], 1)
        self.assertEqual(response.data["buckets"][0]["pencairan_count"], 0)
        self.assertEqual(response.data["buckets"][1]["setoran_total_nilai"], "0.00")
        self.assertEqual(response.data["buckets"][1]["setoran_count"], 0)
        self.assertEqual(response.data["buckets"][1]["pencairan_total_nominal"], "0.00")

    def test_operational_trends_groups_months_and_zero_fills(self) -> None:
        transaction_id = self.make_transaksi()
        Transaksi.objects.filter(pk=transaction_id).update(
            tanggal=timezone.make_aware(datetime(2024, 2, 15, 12))
        )
        response = self.client.get(
            "/api/v1/dashboard/operational-trends",
            {"start_date": "2024-01-15", "end_date": "2024-03-10", "granularity": "month"},
        )

        self.assertEqual(response.status_code, 200)
        buckets = response.data["buckets"]
        self.assertEqual(
            [bucket["period_start"] for bucket in buckets],
            ["2024-01-01", "2024-02-01", "2024-03-01"],
        )
        self.assertEqual(buckets[1]["setoran_count"], 1)
        self.assertEqual(buckets[0]["setoran_count"], 0)
        self.assertEqual(buckets[2]["setoran_count"], 0)

    def test_operational_trends_includes_both_date_boundaries(self) -> None:
        start_id = self.make_transaksi()
        end_id = self._make_setoran(nasabah_kode="NAS-0002", jenis_kode="PLS-002")
        Transaksi.objects.filter(pk=start_id).update(
            tanggal=timezone.make_aware(datetime(2024, 1, 2, 0, 0, 0))
        )
        Transaksi.objects.filter(pk=end_id).update(
            tanggal=timezone.make_aware(datetime(2024, 1, 2, 23, 59, 59, 999999))
        )

        response = self.client.get(
            "/api/v1/dashboard/operational-trends",
            {"start_date": "2024-01-02", "end_date": "2024-01-02", "granularity": "day"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["buckets"]), 1)
        bucket = response.data["buckets"][0]
        self.assertEqual(bucket["period_start"], "2024-01-02")
        self.assertEqual(bucket["setoran_count"], 2)
        self.assertEqual(bucket["setoran_total_nilai"], "17500.00")

    def test_operational_trends_aggregates_pencairan_amounts_and_counts(self) -> None:
        nasabah = self.make_nasabah()
        Pencairan.objects.create(
            nasabah=nasabah,
            bank_sampah=self.bank,
            dicatat_oleh=self.user,
            tanggal=timezone.make_aware(datetime(2024, 1, 3, 12)),
            nominal=Decimal("1250.00"),
            metode=Pencairan.Metode.TUNAI,
            saldo_sebelum=Decimal("5000.00"),
            saldo_sesudah=Decimal("3750.00"),
        )
        response = self.client.get(
            "/api/v1/dashboard/operational-trends",
            {"start_date": "2024-01-01", "end_date": "2024-01-07", "granularity": "day"},
        )
        self.assertEqual(response.status_code, 200)
        bucket = response.data["buckets"][2]
        self.assertEqual(bucket["pencairan_total_nominal"], "1250.00")
        self.assertEqual(bucket["pencairan_count"], 1)

    def test_waste_categories_ranks_weight_and_counts_distinct_deposits(self) -> None:
        today = timezone.localdate()
        timestamp = timezone.make_aware(datetime.combine(today, datetime.min.time()))
        first_id = self.make_transaksi()
        Transaksi.objects.filter(pk=first_id).update(tanggal=timestamp)
        first_transaction = Transaksi.objects.get(pk=first_id)
        first_detail = DetailTransaksi.objects.get(transaksi=first_transaction)
        DetailTransaksi.objects.filter(pk=first_detail.pk).update(kategori_snapshot="plastik")
        DetailTransaksi.objects.create(
            transaksi=first_transaction,
            jenis_sampah=first_detail.jenis_sampah,
            nama_sampah_snapshot=first_detail.nama_sampah_snapshot,
            kategori_snapshot="plastik",
            harga_snapshot=first_detail.harga_snapshot,
            berat=Decimal("1.000"),
            subtotal=Decimal("3500.00"),
        )

        second_id = self._make_setoran(nasabah_kode="NAS-0002", jenis_kode="KRT-001", berat="5.000")
        Transaksi.objects.filter(pk=second_id).update(tanggal=timestamp)
        DetailTransaksi.objects.filter(transaksi_id=second_id).update(kategori_snapshot="kertas")

        response = self.client.get(
            "/api/v1/dashboard/waste-categories",
            {"start_date": today.isoformat(), "end_date": today.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["categories"],
            [
                {"category": "kertas", "total_weight_kg": Decimal("5.000"), "deposit_count": 1},
                {"category": "plastik", "total_weight_kg": Decimal("3.500"), "deposit_count": 1},
            ],
        )

    def test_reporting_endpoints_are_scoped_to_the_pengurus_bank(self) -> None:
        other_bank = BankSampah.objects.create(
            nama="Bank Sampah Lain", alamat="Bandung", kota="Bandung", no_hp_pic="+628987654321"
        )
        other_user = User.objects.create_user(
            email="pengurus.lain@example.com",
            nama="Pengurus Lain",
            bank_sampah=other_bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        other_nasabah = Nasabah.objects.create(
            bank_sampah=other_bank,
            nomor="NAS-OTHER",
            nama="Nasabah Lain",
            alamat="Jl. Lain",
            no_hp="+628987654322",
            email="nasabah.lain@example.com",
        )
        other_jenis = JenisSampah.objects.create(
            bank_sampah=other_bank,
            nomor="PLS-OTHER",
            nama_sampah="Plastik",
            kategori=JenisSampah.Kategori.PLASTIK,
        )
        HargaSampah.objects.create(
            jenis_sampah=other_jenis,
            bank_sampah=other_bank,
            harga_per_kg=Decimal("1000.00"),
            berlaku_mulai=timezone.now() - timedelta(days=1),
        )
        today = timezone.localdate()
        timestamp = timezone.make_aware(datetime.combine(today, datetime.min.time()))
        other_transaction = Transaksi.objects.create(
            nasabah=other_nasabah,
            bank_sampah=other_bank,
            dicatat_oleh=other_user,
            tanggal=timestamp,
            total_nilai=Decimal("100000.00"),
        )
        DetailTransaksi.objects.create(
            transaksi=other_transaction,
            jenis_sampah=other_jenis,
            nama_sampah_snapshot="Plastik",
            kategori_snapshot="plastik",
            harga_snapshot=Decimal("1000.00"),
            berat=Decimal("100.000"),
            subtotal=Decimal("100000.00"),
        )
        Pencairan.objects.create(
            nasabah=other_nasabah,
            bank_sampah=other_bank,
            dicatat_oleh=other_user,
            tanggal=timestamp,
            nominal=Decimal("50000.00"),
            metode=Pencairan.Metode.TUNAI,
            saldo_sebelum=Decimal("100000.00"),
            saldo_sesudah=Decimal("50000.00"),
        )

        params = {"start_date": today.isoformat(), "end_date": today.isoformat()}
        trends = self.client.get(
            "/api/v1/dashboard/operational-trends", {**params, "granularity": "day"}
        )
        categories = self.client.get("/api/v1/dashboard/waste-categories", params)

        self.assertEqual(trends.status_code, 200)
        self.assertEqual(
            trends.data["buckets"][0],
            {
                "period_start": today.isoformat(),
                "setoran_total_nilai": "0.00",
                "setoran_count": 0,
                "pencairan_total_nominal": "0.00",
                "pencairan_count": 0,
            },
        )
        self.assertEqual(categories.status_code, 200)
        self.assertEqual(categories.data["categories"], [])

    def test_reporting_endpoints_validate_required_query_parameters(self) -> None:
        invalid_requests: tuple[tuple[str, dict[str, str]], ...] = (
            ("/api/v1/dashboard/operational-trends", {}),
            ("/api/v1/dashboard/waste-categories", {}),
            (
                "/api/v1/dashboard/operational-trends",
                {"start_date": "2024-02-01", "end_date": "2024-01-01", "granularity": "day"},
            ),
            (
                "/api/v1/dashboard/operational-trends",
                {"start_date": "2024-01-01", "end_date": "2024-02-01", "granularity": "year"},
            ),
            (
                "/api/v1/dashboard/waste-categories",
                {"start_date": "not-a-date", "end_date": "2024-02-01"},
            ),
        )
        for path, params in invalid_requests:
            with self.subTest(path=path, params=params):
                response = self.client.get(path, params)
                self.assertEqual(response.status_code, 400)

    def test_wa_template_rejects_blank(self) -> None:
        response = self.client.put(
            "/api/v1/pengaturan/wa-template", {"template": ""}, format="json"
        )
        self.assertGreaterEqual(response.status_code, 400)

    def test_wa_template_read_contract(self) -> None:
        response = self.client.get("/api/v1/pengaturan/wa-template")
        self.assertEqual(response.status_code, 200)
        self.assertIn("template", response.data)
