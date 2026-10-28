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
        if any(nama == sudah for sudah, _ in self._arahan):
            raise ValueError(
                f"arahan {nama} sudah disetel pada kebijakan ini. Peramban memakai "
                "kemunculan pertama dan MENGABAIKAN sisanya, jadi arahan kedua akan "
                "diam-diam mati — persis mode kegagalan yang modul ini ada untuk "
                "mencegahnya. Gabungkan sumbernya menjadi satu pemanggilan."
            )
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

    def sambung(self, *sumber: str) -> "PembangunKebijakan":
        """`connect-src`: tujuan yang boleh dihubungi fetch/XHR/WebSocket."""
        return self._tambah("connect-src", *sumber)

    def kerangka(self, *sumber: str) -> "PembangunKebijakan":
        """`frame-src`: halaman yang boleh disemat DI DALAM halaman ini.

        Bukan `frame-ancestors`, yang arahnya berlawanan — lihat `penyemat`.
        Menukar keduanya menghasilkan kebijakan yang terlihat benar.
        """
        return self._tambah("frame-src", *sumber)

    def penyemat(self, *sumber: str) -> "PembangunKebijakan":
        """`frame-ancestors`: siapa yang boleh menyemat halaman INI.

        Arah berlawanan dari `kerangka`.
        """
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


def kebijakan_halaman(izinkan_pengembangan: bool, nonce: str | None = None) -> str:
    """Kebijakan halaman HTML yang dilayani Django sendiri.

    Admin Django 6 tidak memuat skrip maupun gaya inline, jadi ``'self'`` saja
    sudah cukup dan ``'unsafe-inline'`` tidak perlu muncul sama sekali.

    ``izinkan_pengembangan`` hanya aktif saat pengembangan, untuk dua halaman
    ``debug_only`` yang keduanya 404 di produksi: Swagger UI drf-spectacular
    yang memuat asetnya dari cdn.jsdelivr.net, dan ``api-test`` yang memakai
    Google Identity Services — skripnya, iframe tombol masuknya, dan panggilan
    balik ke accounts.google.com. Karena itu varian ini juga membuka
    ``connect-src`` dan ``frame-src``, yang di produksi tetap jatuh ke
    ``default-src 'self'``.

    ``nonce`` mengizinkan tag inline MILIK halaman itu sendiri, satu nonce per
    respons. Dipakai kedua halaman pengembang di atas: tag inline-nya tidak
    bisa dipindah ke berkas luar tanpa menyalin template pihak ketiga. Berbeda
    dari `kebijakan_halaman_bernonce`, yang untuk dokumen tertutup.
    """
    luar = (DIRI, HTTPS) if izinkan_pengembangan else (DIRI,)
    inline = (sumber_nonce(nonce),) if nonce else ()
    pembangun = (
        PembangunKebijakan()
        .bawaan(DIRI)
        .skrip(*luar, *inline)
        .gaya(*luar, *inline)
        .gambar(*luar, DATA)
        .fon(*luar, DATA)
    )
    if izinkan_pengembangan:
        pembangun.sambung(DIRI, HTTPS).kerangka(HTTPS)
    return _penutup(pembangun, DIRI)


def kebijakan_halaman_bernonce(nonce: str) -> str:
    """Kebijakan dokumen tertutup: skrip inline lewat nonce, dan tidak ada lagi.

    Dipakai popup OAuth, yang tidak memuat aset apa pun dari luar, sehingga
    ``default-src 'none'`` di sana tidak menghalangi apa pun. Halaman yang
    memuat aset luar memakai `kebijakan_halaman` dengan nonce, bukan ini.
    """
    pembangun = PembangunKebijakan().bawaan(TIDAK_ADA).skrip(sumber_nonce(nonce))
    return _penutup(pembangun, TIDAK_ADA)


def nonce_baru() -> str:
    """Nonce acak untuk satu respons.

    Harus tidak bisa diramalkan: nonce yang berulang atau bisa dihitung memberi
    penyerang cara memberi skripnya sendiri nonce yang sah, yang sama saja
    dengan ``'unsafe-inline'``.
    """
    return secrets.token_urlsafe(16)


_ATRIBUT_NONCE = "csp_nonce"
_ATRIBUT_TERTUTUP = "csp_dokumen_tertutup"


def tandai_dokumen_tertutup(response: HttpResponse, nonce: str) -> None:
    """Respons ini dokumen tertutup dengan skrip inline bernonce (popup OAuth).

    Dibaca `CspMiddleware`, yang menyusun kebijakannya. View menyatakan fakta
    tentang responsnya ("saya punya skrip inline dengan nonce ini, dan saya
    tidak memuat apa pun dari luar"), bukan kebijakannya sendiri.
    """
    setattr(response, _ATRIBUT_NONCE, nonce)
    setattr(response, _ATRIBUT_TERTUTUP, True)


def tandai_halaman_bernonce(response: HttpResponse, nonce: str) -> None:
    """Respons ini halaman HTML biasa yang punya tag inline bernonce ini.

    Berbeda dari `tandai_dokumen_tertutup`: halaman ini tetap memuat aset dari
    luar, jadi kebijakannya `kebijakan_halaman` ditambah nonce, bukan
    `default-src 'none'`.
    """
    setattr(response, _ATRIBUT_NONCE, nonce)


def _dokumen_html(response: HttpResponse) -> bool:
    return response.get("Content-Type", "").startswith("text/html")


class CspMiddleware:
    """Memasang Content-Security-Policy menurut konteks responsnya.

    Kebijakan dipilih setelah `get_response(request)` kembali, sehingga tipe
    konten respons sudah diketahui dan kebijakannya bisa dipilih dari sana
    alih-alih dari daftar path yang harus dirawat terpisah. Karena pemilihan
    itu terjadi di fase respons, middleware ini justru dipasang PALING LUAR —
    lihat komentar pada `MIDDLEWARE` di `config/settings.py`.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", self._kebijakan(response))
        return response

    @staticmethod
    def _kebijakan(response: HttpResponse) -> str:
        nonce: str | None = getattr(response, _ATRIBUT_NONCE, None)
        if nonce and getattr(response, _ATRIBUT_TERTUTUP, False):
            return kebijakan_halaman_bernonce(nonce)
        if _dokumen_html(response):
            return kebijakan_halaman(settings.DEBUG, nonce)
        return KEBIJAKAN_API
