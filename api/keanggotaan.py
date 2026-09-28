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

# Email adalah kunci penautan keanggotaan ke akun Google, dan tidak ada
# penjaga lain pada jalur update: pemeriksaan email yang ada hanya keunikan
# dalam satu bank sampah dan validasi format. Tanpa penguncian ini pengurus
# dapat memindahkan keanggotaan ke alamat lain dan memutus tautan akunnya.
#
# Sisa profil sengaja tidak ikut terkunci. PIL-223 sempat mengunci keenamnya,
# lalu client memutuskan pengurus tetap perlu dapat memperbaiki data nasabah
# di lapangan (PIL-288).
FIELD_PROFIL_GLOBAL = ("email",)


# Profil yang dimiliki akun dan berlaku lintas bank sampah (PRD F21). Email
# tidak ikut: ia kunci penautan, bukan data profil yang boleh disunting.
FIELD_PROFIL_AKUN = ("nama", "jenis_kelamin", "tanggal_lahir", "alamat", "no_hp")


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
        field in data and data[field] != getattr(nasabah, field) for field in FIELD_PROFIL_GLOBAL
    )


def sinkronkan_profil_ke_akun(nasabah: Nasabah) -> None:
    """Tulis profil keanggotaan ini ke akun pemiliknya.

    Profil dimiliki akun dan berlaku lintas bank sampah, sedangkan baris
    keanggotaan hanya menyimpan salinannya. Karena itu setiap penyimpanan
    profil oleh nasabah menimpa seluruh keanggotaan tertaut lewat
    ``OnboardingService.propagate_profile_to_memberships``. Tanpa penulisan
    balik ini, perbaikan pengurus akan hilang pada penyimpanan berikutnya.

    Sengaja hanya menyentuh lima field profil: email adalah kunci penautan dan
    tetap terkunci, sedangkan role serta flag akun bukan urusan pengurus.
    """
    user = nasabah.user
    if user is None:
        return
    berubah = [
        field
        for field in FIELD_PROFIL_AKUN
        if getattr(user, field) != getattr(nasabah, field)
    ]
    if not berubah:
        return
    for field in berubah:
        setattr(user, field, getattr(nasabah, field))
    user.save(update_fields=[*berubah, "updated_at"])
