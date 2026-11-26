"""Validasi parameter `search` bersama.

Karakter kontrol C0 (termasuk NUL) tidak pernah menjadi bagian nama atau nomor
yang sah, dan NUL membuat PostgreSQL menolak query dengan DataError (500).
Seperti `periode` dan `tipe`, nilai yang tidak valid dijawab 422.
"""

from rest_framework import serializers

_KARAKTER_KONTROL = frozenset(chr(code) for code in (*range(0x20), 0x7F))


def validasi_pencarian(nilai: str) -> str:
    if any(char in _KARAKTER_KONTROL for char in nilai):
        raise serializers.ValidationError(
            {"search": "Pencarian tidak boleh memuat karakter kontrol"}
        )
    return nilai
