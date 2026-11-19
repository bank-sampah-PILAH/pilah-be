"""Id permintaan: satu id yang menghubungkan aplikasi, respons, dan log server.

Aplikasi mengirim ``X-Request-Id`` (UUID acak) pada setiap panggilan. Id itu
dicatat di PostHog saat panggilan gagal, dan di sini ditulis pada setiap baris
log server selama permintaan berjalan, sehingga kegagalan yang dilihat pengguna
bisa dicari dari id-nya.

Id dari klien tidak dipercaya begitu saja: nilainya masuk ke setiap baris log,
jadi baris baru atau spasi di dalamnya bisa dipakai menyelipkan baris log
palsu (CWE-117, OWASP A09). Id yang bentuknya tidak wajar diganti dengan id
buatan server. Modul ini sengaja tidak mengimpor Django kecuali tipe permintaan
dan respons, supaya aman dimuat dari ``config/settings.py``.
"""

import logging
import re
import uuid
from collections.abc import Callable
from contextvars import ContextVar

from django.http import HttpRequest, HttpResponse

from shared_kernel.http_headers import REQUEST_ID

TANPA_ID = "-"
"""Dipakai pada baris log yang tidak berasal dari sebuah permintaan."""

current_request_id: ContextVar[str] = ContextVar("request_id", default=TANPA_ID)

_BENTUK_WAJAR = re.compile(r"[A-Za-z0-9-]{8,64}")


def _id_dari(request: HttpRequest) -> str:
    dikirim = request.headers.get(REQUEST_ID, "")
    if _BENTUK_WAJAR.fullmatch(dikirim):
        return dikirim
    return str(uuid.uuid4())


class RequestIdMiddleware:
    """Memberi setiap permintaan sebuah id, dan mengembalikannya di header respons.

    Dipasang paling luar, supaya baris log dari middleware lain dan respons
    yang dibuat tanpa mencapai view (preflight CORS, pengalihan HTTPS) pun
    membawa id.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = _id_dari(request)
        token = current_request_id.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            current_request_id.reset(token)
        response[REQUEST_ID] = request_id
        return response


class RequestIdFilter(logging.Filter):
    """Menaruh id permintaan yang sedang berjalan pada setiap baris log."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id.get()
        return True
