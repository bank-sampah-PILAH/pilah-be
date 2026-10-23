"""Content-Security-Policy: satu kebijakan per konteks respons.

Kebijakan CSP adalah string panjang yang disusun dari arahan-arahan, dan
kesalahan menyusunnya tidak menimbulkan galat apa pun: **peramban MENGABAIKAN
arahan yang tidak dikenalnya**. Salah tulis `frame-ancestor` alih-alih
`frame-ancestors` menghasilkan header yang terlihat benar, lulus setiap test
yang mencocokkan teks, dan tidak melindungi apa pun. CSP gagal secara terbuka.

Karena itu nama arahan di modul ini hanya ada SATU KALI, di dalam
``PembangunKebijakan``. Pemanggil memakai metode bernama, sehingga salah tulis
menjadi ``AttributeError`` saat impor alih-alih arahan yang diam-diam mati.
"""

import secrets
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

TIDAK_ADA = "'none'"
DIRI = "'self'"
HTTPS = "https:"
DATA = "data:"


def sumber_nonce(nonce: str) -> str:
    return f"'nonce-{nonce}'"


class PembangunKebijakan:
    """Penyusun kebijakan CSP, satu arahan per langkah (pola Builder).

    Urutan arahan pada hasil akhir mengikuti urutan pemanggilan, sehingga
    kebijakan bisa dibaca dari kode yang membangunnya.
    """

    def __init__(self) -> None:
        self._arahan: list[tuple[str, tuple[str, ...]]] = []

    def _tambah(self, nama: str, *sumber: str) -> "PembangunKebijakan":
        self._arahan.append((nama, sumber))
        return self

    def bawaan(self, *sumber: str) -> "PembangunKebijakan":
        return self._tambah("default-src", *sumber)

    def skrip(self, *sumber: str) -> "PembangunKebijakan":
        return self._tambah("script-src", *sumber)

    def gaya(self, *sumber: str) -> "PembangunKebijakan":
        return self._tambah("style-src", *sumber)

    def gambar(self, *sumber: str) -> "PembangunKebijakan":
        return self._tambah("img-src", *sumber)

    def fon(self, *sumber: str) -> "PembangunKebijakan":
        return self._tambah("font-src", *sumber)

    def penyemat(self, *sumber: str) -> "PembangunKebijakan":
        """`frame-ancestors`: siapa yang boleh menyemat halaman ini."""
        return self._tambah("frame-ancestors", *sumber)

    def base_uri(self, *sumber: str) -> "PembangunKebijakan":
        return self._tambah("base-uri", *sumber)

    def tujuan_form(self, *sumber: str) -> "PembangunKebijakan":
        return self._tambah("form-action", *sumber)

    def bangun(self) -> str:
        return "; ".join(f"{nama} {' '.join(sumber)}" for nama, sumber in self._arahan)


def _penutup(pembangun: PembangunKebijakan, tujuan_form: str) -> str:
    """Tiga arahan yang harus ada pada SETIAP kebijakan.

    Tidak satu pun diturunkan dari `default-src`, jadi melewatkannya berarti
    kehilangan perlindungannya tanpa tanda apa pun. Ditulis satu kali di sini
    supaya tidak bisa terlewat di salah satu kebijakan saja.
    """
    return pembangun.penyemat(TIDAK_ADA).base_uri(TIDAK_ADA).tujuan_form(tujuan_form).bangun()


KEBIJAKAN_API = _penutup(PembangunKebijakan().bawaan(TIDAK_ADA), TIDAK_ADA)
"""Kebijakan untuk respons yang bukan dokumen HTML.

JSON tidak memuat subsumber apa pun, jadi `default-src 'none'` di sana tidak
bisa merusak apa pun.
"""


def kebijakan_halaman(izinkan_cdn: bool) -> str:
    """Kebijakan halaman HTML yang dilayani Django sendiri.

    Admin Django 6 tidak memuat skrip maupun gaya inline, jadi ``'self'`` saja
    sudah cukup dan ``'unsafe-inline'`` tidak perlu muncul sama sekali.

    ``izinkan_cdn`` hanya aktif saat pengembangan: Swagger UI drf-spectacular
    memuat asetnya dari CDN, dan halaman itu ``debug_only`` sehingga tidak
    pernah ada di produksi. Produksi tetap ``'self'`` saja.
    """
    sumber = (DIRI, HTTPS) if izinkan_cdn else (DIRI,)
    pembangun = (
        PembangunKebijakan()
        .bawaan(DIRI)
        .skrip(*sumber)
        .gaya(*sumber)
        .gambar(DIRI, DATA)
        .fon(*sumber, DATA)
    )
    return _penutup(pembangun, DIRI)


def kebijakan_halaman_bernonce(nonce: str) -> str:
    """Kebijakan halaman yang skrip inline-nya diizinkan lewat nonce saja."""
    pembangun = PembangunKebijakan().bawaan(TIDAK_ADA).skrip(sumber_nonce(nonce))
    return _penutup(pembangun, TIDAK_ADA)


def nonce_baru() -> str:
    """Nonce acak untuk satu respons.

    Harus tidak bisa diramalkan: nonce yang berulang atau bisa dihitung memberi
    penyerang cara memberi skripnya sendiri nonce yang sah, yang sama saja
    dengan ``'unsafe-inline'``.
    """
    return secrets.token_urlsafe(16)


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
        response.setdefault("Content-Security-Policy", self._kebijakan(response))
        return response

    @staticmethod
    def _kebijakan(response: HttpResponse) -> str:
        nonce = getattr(response, "csp_nonce", None)
        if nonce:
            return kebijakan_halaman_bernonce(nonce)
        if _dokumen_html(response):
            return kebijakan_halaman(settings.DEBUG)
        return KEBIJAKAN_API
