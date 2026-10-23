"""Content-Security-Policy: satu kebijakan per konteks respons.

API ini hampir seluruhnya JSON, dan JSON tidak memuat subsumber apa pun, jadi
`default-src 'none'` di sana tidak bisa merusak apa pun. Halaman HTML yang
masih dilayani adalah soal lain dan diurus terpisah.
"""

import secrets
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

KEBIJAKAN_API = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
"""Kebijakan untuk respons yang bukan dokumen HTML."""


def nonce_baru() -> str:
    """Nonce acak untuk satu respons.

    Harus tidak bisa diramalkan: nonce yang berulang atau bisa dihitung
    memberi penyerang cara memberi skripnya sendiri nonce yang sah, yang
    sama saja dengan ``'unsafe-inline'``.
    """
    return secrets.token_urlsafe(16)


def kebijakan_halaman(izinkan_cdn: bool) -> str:
    """Kebijakan halaman HTML yang dilayani Django sendiri.

    Admin Django 6 tidak memuat skrip maupun gaya inline, jadi ``'self'``
    saja sudah cukup dan ``'unsafe-inline'`` tidak perlu muncul sama sekali.

    ``izinkan_cdn`` hanya aktif saat pengembangan: Swagger UI drf-spectacular
    memuat asetnya dari CDN, dan halaman itu ``debug_only`` sehingga tidak
    pernah ada di produksi. Produksi tetap ``'self'`` saja.
    """
    sumber = "'self' https:" if izinkan_cdn else "'self'"
    return (
        f"default-src 'self'; script-src {sumber}; style-src {sumber}; "
        f"img-src 'self' data:; font-src {sumber} data:; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )


def kebijakan_halaman_bernonce(nonce: str) -> str:
    """Kebijakan halaman yang skrip inline-nya diizinkan lewat nonce saja."""
    return (
        f"default-src 'none'; script-src 'nonce-{nonce}'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )


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
        nonce = getattr(response, "csp_nonce", None)
        if nonce:
            response.setdefault("Content-Security-Policy", kebijakan_halaman_bernonce(nonce))
        elif _dokumen_html(response):
            response.setdefault("Content-Security-Policy", kebijakan_halaman(settings.DEBUG))
        else:
            response.setdefault("Content-Security-Policy", KEBIJAKAN_API)
        return response
