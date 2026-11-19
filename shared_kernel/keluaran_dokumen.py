"""Aturan meloloskan nilai menurut konteks tempatnya tercetak di dokumen.

Satu nilai yang sama butuh aturan berbeda tergantung di mana ia mendarat.
Di dalam ``<pre>`` yang berlaku aturan HTML: ``<`` harus menjadi ``&lt;``.
Di dalam ``<script>`` aturan itu justru merusak, karena ``&lt;`` bukan JSON
yang sah — di sana ``<`` harus menjadi ``\u003c``, yang tetap dibaca
JavaScript sebagai ``<``.

Halaman popup OAuth pernah mencetak tiga nilai ke dua konteks berbeda dengan
satu pemanggilan ``json.dumps`` mentah untuk semuanya, dan ketiganya bisa
disuntik. Akar masalahnya bukan satu fungsi yang salah melainkan tidak adanya
apa pun yang mengikat aturan ke konteksnya: penulis template harus mengingat
sendiri sink mana butuh aturan mana.

Modul ini menjadikan konteks itu sebagai nilai bernama yang membawa aturannya
(pola Strategy). Pemanggil memilih konteks di sink-nya, bukan memilih fungsi,
dan ``SEMUA_KONTEKS`` membuat himpunannya bisa diiterasi sebuah test.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.utils.html import escape

# Tiga karakter yang membuat literal JSON berhenti menjadi data begitu
# ditempelkan ke dalam dokumen HTML. Parser HTML mengakhiri sebuah blok
# <script> pada "</script>" pertama tanpa peduli bahwa urutan itu berada di
# dalam string JavaScript, jadi meloloskannya harus terjadi di sisi JSON.
# Peta ini salinan django.utils.html._json_script_escapes, yaitu peta yang
# dipakai django.utils.html.json_script (diperiksa sama pada Django 6.0.8,
# lihat django/utils/html.py di hulu). Namanya privat dan tanpa jaminan
# kestabilan, jadi disalin alih-alih diimpor — konsekuensinya menyetarakan
# ulang salinan ini adalah pekerjaan tangan setiap kali Django naik versi.
_LOLOS_JSON_DALAM_HTML = {ord("<"): "\\u003C", ord(">"): "\\u003E", ord("&"): "\\u0026"}


def _sebagai_teks_html(nilai: Any) -> str:
    """JSON yang dibaca manusia, diloloskan sebagai teks HTML."""
    return escape(json.dumps(nilai, indent=2))


def _sebagai_literal_skrip(nilai: Any) -> str:
    """Literal JSON yang aman ditempel di dalam blok ``<script>``."""
    return json.dumps(nilai).translate(_LOLOS_JSON_DALAM_HTML)


@dataclass(frozen=True)
class KonteksKeluaran:
    """Satu konteks keluaran beserta aturan meloloskannya.

    Strategy: aturannya ikut pada konteksnya, sehingga sink memilih tempat
    ("saya mencetak ke dalam skrip"), bukan algoritme ("saya pakai translate").
    """

    nama: str
    _aturan: Callable[[Any], str]

    def loloskan(self, nilai: Any) -> str:
        return self._aturan(nilai)


TEKS_HTML = KonteksKeluaran("teks HTML", _sebagai_teks_html)
LITERAL_SKRIP = KonteksKeluaran("literal skrip", _sebagai_literal_skrip)

SEMUA_KONTEKS: tuple[KonteksKeluaran, ...] = (TEKS_HTML, LITERAL_SKRIP)
"""Setiap konteks yang dikenal, supaya sebuah test bisa menuntut semuanya aman.

Kontraknya satu arah: konteks baru wajib masuk tuple ini, dan test keamanan
wajib mengiterasi tuple ini alih-alih menyebut konteks satu per satu. Dengan
begitu konteks berikutnya ikut terjaga pada saat ia ditambahkan, bukan pada
saat seseorang ingat menuliskan test untuknya.
"""
