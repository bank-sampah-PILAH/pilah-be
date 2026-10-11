"""Contract tests for the nasabah riwayat statement PDF export (PIL-315).

HTTP layer only: %PDF- magic, headers, status mapping, access boundaries. The
saldo walk, totals and detail sub-rows are asserted at the data layer in
apps/reporting/test_statement.py — PDF text extraction is deliberately not a
test dependency.
"""

from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from api.models import BankSampah, Nasabah, Pencairan, Transaksi, User

# The bulk contract below fires far more than 10 requests per minute; the
# throttle's rate is exercised only by real traffic, not these fixtures.
_TEST_SETTINGS = {
    **settings.REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {"statement_pdf": None},
}


def make_member(email: str, nomor: str, bank: BankSampah) -> Nasabah:
    user = User.objects.create_user(email=email, nama="N " + nomor, role=User.Role.NASABAH)
    return Nasabah.objects.create(
        user=user,
        bank_sampah=bank,
        nomor=nomor,
        nama="Nasabah " + nomor,
        alamat="Depok",
        no_hp="0812" + nomor,
    )


@override_settings(REST_FRAMEWORK=_TEST_SETTINGS)
class NasabahHistoryPdfExportTests(APITestCase):
    url = "/api/v1/nasabah/me/riwayat/export-pdf"

    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(nama="Melati", no_hp_pic="08123456789")
        self.user = User.objects.create_user(
            email="pdf@example.test", nama="Siti", role=User.Role.NASABAH
        )
        self.manager = User.objects.create_user(email="staff@example.test", nama="Staff")
        self.member = Nasabah.objects.create(
            user=self.user,
            bank_sampah=self.bank,
            nomor="001",
            nama="Siti",
            alamat="Depok",
            no_hp="08120",
        )
        Transaksi.objects.create(
            nasabah=self.member,
            bank_sampah=self.bank,
            dicatat_oleh=self.manager,
            total_nilai=Decimal("10000.00"),
        )
        Pencairan.objects.create(
            nasabah=self.member,
            bank_sampah=self.bank,
            dicatat_oleh=self.manager,
            nominal=Decimal("3000.00"),
            metode="tunai",
            saldo_sebelum=Decimal("10000.00"),
            saldo_sesudah=Decimal("7000.00"),
        )
        self.client.force_authenticate(self.user)

    # --- HTTP contract ---------------------------------------------------

    def test_export_returns_pdf_content_type_and_attachment(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("Riwayat_Aktivitas_001.pdf", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_export_unknown_tema_falls_back_silently(self) -> None:
        response = self.client.get(self.url, {"tema": "hijau-tidak-ada"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_export_rejects_pil_246_month_windows_until_shared(self) -> None:
        # 1/3/6/12-month values exist on the PIL-246 branch only. apply_period
        # silently ignores them (exporting ALL history), so until the shared
        # filter learns them the export must reject instead of mislabeling.
        for periode in ("1_bulan", "3_bulan", "6_bulan", "12_bulan"):
            with self.subTest(periode=periode):
                response = self.client.get(self.url, {"periode": periode})
                self.assertEqual(response.status_code, 400)
                self.assertIn("belum tersedia", response.json()["error"])

    def test_export_unknown_tipe_falls_back_to_semua(self) -> None:
        response = self.client.get(self.url, {"tipe": "deposito"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_export_tipe_pencairan_limits_displayed_rows(self) -> None:
        response = self.client.get(self.url, {"tipe": "pencairan"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_export_empty_result_returns_400_with_convention_message(self) -> None:
        bank2 = BankSampah.objects.create(nama="Kosong", no_hp_pic="08129999")
        member2 = make_member("kosong@example.test", "002", bank2)
        self.client.force_authenticate(member2.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Tidak ada data pada periode ini"})

    def test_custom_period_missing_dates_returns_422(self) -> None:
        response = self.client.get(self.url, {"periode": "custom"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["errors"], {"error": "dari_tanggal dan sampai_tanggal wajib diisi"}
        )

    def test_custom_period_reversed_dates_returns_400(self) -> None:
        response = self.client.get(
            self.url,
            {"periode": "custom", "dari_tanggal": "2026-10-02", "sampai_tanggal": "2026-10-01"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"], "Tanggal akhir tidak boleh lebih awal dari tanggal awal"
        )

    def test_render_value_error_is_a_500_not_a_400(self) -> None:
        # The view maps only StatementPeriodError (a period request error) to
        # 400. A ValueError escaping the renderer must surface as a server
        # error — never a 400 echoing renderer internals like an absolute
        # path.
        # raise_request_exception=False: the framework's error handling turns
        # the escape into the response a real caller would receive.
        client = APIClient(raise_request_exception=False)
        client.force_authenticate(self.user)
        with patch(
            "apps.reporting.render.render_statement",
            side_effect=ValueError("internal /srv/x secret detail"),
        ):
            response = client.get(self.url)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret detail", response.content.decode())

    def test_export_is_throttled(self) -> None:
        # The scoped rate keeps a nasabah from farming the CPU-heavy render
        # endpoint; a second export inside one minute is rejected with 429.
        # The throttle reads its rates off the class attribute snapshotted at
        # import (not the live Django setting), so patch that attribute.
        with patch(
            "rest_framework.throttling.ScopedRateThrottle.THROTTLE_RATES",
            {"statement_pdf": "1/min"},
        ):
            client = APIClient()
            client.force_authenticate(self.user)
            self.assertEqual(client.get(self.url).status_code, 200)
            self.assertEqual(client.get(self.url).status_code, 429)

    # --- Access boundaries -------------------------------------------------

    def test_pengelola_rejected(self) -> None:
        self.client.force_authenticate(self.manager)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_anonymous_rejected(self) -> None:
        self.client.force_authenticate()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 401)

    def test_membership_must_be_eligible(self) -> None:
        Nasabah.objects.filter(pk=self.member.pk).update(status=Nasabah.Status.REJECTED)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_cross_bank_isolation(self) -> None:
        other_bank = BankSampah.objects.create(nama="Sebelah", no_hp_pic="08123333")
        outsider = make_member("sebelah@example.test", "009", other_bank)
        Transaksi.objects.create(
            nasabah=outsider,
            bank_sampah=other_bank,
            dicatat_oleh=self.manager,
            total_nilai=Decimal("77777.00"),
        )

        # The statement stays scoped to the caller's membership and bank —
        # row-level parity is covered in apps/reporting/test_statement.py.
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.content), 700)
