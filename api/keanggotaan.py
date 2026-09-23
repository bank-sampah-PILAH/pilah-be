"""Batas wewenang pengurus atas data nasabah (PIL-223).

Profil nasabah adalah milik pemilik akun dan berlaku di seluruh bank sampah
tempat ia terdaftar, sedangkan nomor anggota dan status keanggotaan adalah data
bank sampah. Karena itu, begitu sebuah keanggotaan tertaut ke akun, pengurus
hanya boleh mengubah data keanggotaan.

Semua pemeriksaan wewenang atas data nasabah harus lewat modul ini supaya
aturannya tidak tersebar di beberapa view.
"""

from typing import Any, Mapping

from api.models import Nasabah

# Profil global milik pemilik akun. Bukan `kode`, `is_active`, maupun `status`,
# yang merupakan data keanggotaan pada satu bank sampah. Ketika PIL-154 sudah
# masuk, `email` ikut ke daftar ini karena menjadi kunci penautan akun.
FIELD_PROFIL_GLOBAL = ("nama", "jenis_kelamin", "tanggal_lahir", "alamat", "no_hp")


def punya_akun(nasabah: Nasabah) -> bool:
    """``True`` bila keanggotaan ini sudah tertaut ke akun pengguna."""
    return nasabah.user_id is not None


def profil_terkunci(nasabah: Nasabah, data: Mapping[str, Any]) -> bool:
    """``True`` bila ``data`` mengubah profil global nasabah berakun.

    ``data`` harus berupa ``validated_data`` serializer, bukan payload mentah,
    karena nomor HP dinormalisasi ke bentuk +62 dan tanggal lahir dikonversi
    menjadi ``date``. Membandingkan payload mentah membuat form yang mengirim
    ulang nilai yang sama ditolak tanpa alasan.

    Yang dibandingkan adalah nilainya, bukan keberadaan field, supaya form yang
    mengirim seluruh data nasabah tetap dapat menyimpan perubahan pada data
    keanggotaan.
    """
    if not punya_akun(nasabah):
        return False
    return any(
        field in data and data[field] != getattr(nasabah, field)
        for field in FIELD_PROFIL_GLOBAL
    )
