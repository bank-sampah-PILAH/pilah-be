"""Content-Security-Policy: satu kebijakan per konteks respons.

API ini hampir seluruhnya JSON, dan JSON tidak memuat subsumber apa pun, jadi
`default-src 'none'` di sana tidak bisa merusak apa pun. Halaman HTML yang
masih dilayani adalah soal lain dan diurus terpisah.
"""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

KEBIJAKAN_API = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
"""Kebijakan untuk respons yang bukan dokumen HTML."""


def _dokumen_html(response: HttpResponse) -> bool:
    return response.get("Content-Type", "").startswith("text/html")


class CspMiddleware:
    """Memasang Content-Security-Policy menurut konteks responsnya.

    Dipasang setelah view berjalan, sehingga tipe konten respons sudah
    diketahui dan kebijakannya bisa dipilih dari sana alih-alih dari daftar
    path yang harus dirawat terpisah.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if not _dokumen_html(response):
            response.setdefault("Content-Security-Policy", KEBIJAKAN_API)
        return response
