"""Batas wewenang pengurus atas data nasabah (PIL-223, direvisi PIL-288).

Baris keanggotaan adalah catatan bank sampah tentang nasabah, terpisah dari
profil akun milik nasabah itu sendiri: tidak ada penyalinan di kedua arah.
Pengurus boleh memperbaiki catatan nasabah berakun, karena ialah yang bertemu
nasabah di lapangan, kecuali email yang menjadi kunci penautan akun. Perbaikan
itu hanya berlaku di bank sampahnya dan tidak menyentuh akun.

Semua pemeriksaan wewenang atas data nasabah harus lewat modul ini supaya
aturannya tidak tersebar di beberapa view.
"""

from typing import Any, Mapping

from api.models import Nasabah

# Email adalah kunci penautan keanggotaan ke akun Google, dan tidak ada
# penjaga lain pada jalur update: pemeriksaan email yang ada hanya keunikan
# dalam satu bank sampah dan validasi format. Tanpa penguncian ini pengurus
# dapat memindahkan keanggotaan ke alamat lain dan memutus tautan akunnya.
#
# Sisa profil sengaja tidak ikut terkunci. PIL-223 sempat mengunci keenamnya,
# lalu client memutuskan pengurus tetap perlu dapat memperbaiki data nasabah
# di lapangan (PIL-288).
FIELD_TERKUNCI = ("email",)


def punya_akun(nasabah: Nasabah) -> bool:
    """``True`` bila keanggotaan ini sudah tertaut ke akun pengguna."""
    return nasabah.user_id is not None


def email_terkunci(nasabah: Nasabah, data: Mapping[str, Any]) -> bool:
    """``True`` bila ``data`` mengubah email nasabah berakun.

    ``data`` harus berupa ``validated_data`` serializer, bukan payload mentah,
    karena nomor HP dinormalisasi ke bentuk +62 dan tanggal lahir dikonversi
    menjadi ``date``. Membandingkan payload mentah membuat form yang mengirim
    ulang nilai yang sama ditolak tanpa alasan.

    Yang dibandingkan adalah nilainya, bukan keberadaan field, supaya form yang
    mengirim seluruh data nasabah tetap dapat menyimpan perubahan lainnya.
    """
    if not punya_akun(nasabah):
        return False
    return any(field in data and data[field] != getattr(nasabah, field) for field in FIELD_TERKUNCI)
