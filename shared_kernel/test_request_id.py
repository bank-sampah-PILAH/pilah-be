"""Id permintaan: satu id yang sama terlihat di aplikasi, respons, dan log server."""

import logging
import uuid

from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase

from shared_kernel.http_headers import REQUEST_ID
from shared_kernel.request_id import (
    RequestIdFilter,
    RequestIdMiddleware,
    current_request_id,
)

ID_KLIEN = "5d1f3a9e-0b7c-4c1e-8a52-6f0c2d9b7e11"


class MiddlewareIdTests(TestCase):
    def test_memakai_id_dari_klien_dan_mengembalikannya(self) -> None:
        response = self.client.get("/healthz", HTTP_X_REQUEST_ID=ID_KLIEN)

        self.assertEqual(response[REQUEST_ID], ID_KLIEN)

    def test_membuat_id_sendiri_bila_klien_tidak_mengirim(self) -> None:
        response = self.client.get("/healthz")

        self.assertEqual(str(uuid.UUID(response[REQUEST_ID])), response[REQUEST_ID])

    def test_mengganti_id_yang_bentuknya_tidak_wajar(self) -> None:
        # Baris baru atau spasi di id bisa dipakai menyelipkan baris palsu ke log
        # (CWE-117), dan id yang sangat panjang membengkakkan setiap baris log.
        for buruk in ("abc\nFAKE LOG LINE", "dengan spasi 12345", "x" * 200, "a b", "<b>"):
            with self.subTest(buruk=buruk):
                response = self.client.get("/healthz", HTTP_X_REQUEST_ID=buruk)

                self.assertNotEqual(response[REQUEST_ID], buruk)
                uuid.UUID(response[REQUEST_ID])

    def test_respons_preflight_cors_juga_membawa_id(self) -> None:
        # Middleware ini paling luar, jadi respons yang dibuat middleware lain
        # tanpa mencapai view pun membawa id.
        response = self.client.options(
            "/api/v1/dashboard/stats",
            HTTP_ORIGIN="http://localhost:7357",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
            HTTP_X_REQUEST_ID=ID_KLIEN,
        )

        self.assertEqual(response[REQUEST_ID], ID_KLIEN)


class KonteksIdTests(SimpleTestCase):
    def test_id_terlihat_selama_permintaan_dan_hilang_sesudahnya(self) -> None:
        dilihat: list[str] = []

        def view(request: HttpRequest) -> HttpResponse:
            dilihat.append(current_request_id.get())
            return HttpResponse()

        request = RequestFactory().get("/x", HTTP_X_REQUEST_ID=ID_KLIEN)

        RequestIdMiddleware(view)(request)

        self.assertEqual(dilihat, [ID_KLIEN])
        self.assertEqual(current_request_id.get(), "-")

    def test_id_dilepas_walau_view_melempar_error(self) -> None:
        def view(request: HttpRequest) -> HttpResponse:
            raise RuntimeError("boom")

        request = RequestFactory().get("/x", HTTP_X_REQUEST_ID=ID_KLIEN)

        with self.assertRaises(RuntimeError):
            RequestIdMiddleware(view)(request)

        self.assertEqual(current_request_id.get(), "-")


class LogTests(SimpleTestCase):
    def _record(self) -> logging.LogRecord:
        return logging.LogRecord("x", logging.WARNING, __file__, 1, "pesan", (), None)

    def test_filter_menaruh_id_pada_baris_log(self) -> None:
        token = current_request_id.set(ID_KLIEN)
        try:
            record = self._record()
            self.assertTrue(RequestIdFilter().filter(record))
        finally:
            current_request_id.reset(token)

        self.assertEqual(record.request_id, ID_KLIEN)  # type: ignore[attr-defined]

    def test_baris_log_di_luar_permintaan_memakai_tanda_strip(self) -> None:
        record = self._record()

        RequestIdFilter().filter(record)

        self.assertEqual(record.request_id, "-")  # type: ignore[attr-defined]

    def test_log_yang_dikonfigurasi_menulis_id_pada_barisnya(self) -> None:
        # Menguji konfigurasi sungguhan di settings, bukan hanya filternya:
        # handler bernama "console" harus memuat id pada hasil akhirnya.
        handler = next(h for h in logging.getLogger().handlers if h.name == "console")
        token = current_request_id.set(ID_KLIEN)
        try:
            record = self._record()
            self.assertTrue(handler.filter(record))
            baris = handler.format(record)
        finally:
            current_request_id.reset(token)

        self.assertIn(ID_KLIEN, baris)
        self.assertIn("pesan", baris)
