"""Batas wewenang pengurus atas data nasabah (PIL-223, direvisi PIL-288).

Profil nasabah dimiliki pemilik akun dan berlaku di seluruh bank sampah tempat
ia terdaftar, sedangkan nomor anggota dan status keanggotaan adalah data bank
sampah. Pengurus boleh memperbaiki profil nasabah berakun, karena ialah yang
bertemu nasabah di lapangan, kecuali email yang menjadi kunci penautan akun.

Perbaikan pengurus ikut ditulis ke akun supaya tidak tertimpa ketika nasabah
menyimpan profilnya sendiri.

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


# Profil yang dimiliki akun dan berlaku lintas bank sampah (PRD F21). Email
# tidak ikut: ia kunci penautan, bukan data profil yang boleh disunting.
FIELD_PROFIL_AKUN = ("nama", "jenis_kelamin", "tanggal_lahir", "alamat", "no_hp")


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


def no_hp_bentrok_di_keanggotaan_lain(nasabah: Nasabah, no_hp: str) -> bool:
    """``True`` bila ``no_hp`` sudah dipakai nasabah lain pada bank sampah
    tempat akun ini juga terdaftar.

    Nomor HP unik per bank sampah. Karena profil ikut tersalin ke seluruh
    keanggotaan tertaut, nomor yang bentrok di bank sampah lain baru meledak
    saat nasabah menyimpan profilnya sendiri, dan pesannya ditujukan kepada
    nasabah. Diperiksa lebih awal supaya pengurus yang mengetiknya yang
    diberi tahu.
    """
    user = nasabah.user
    if user is None or not no_hp:
        return False
    bank_lain = user.keanggotaan_nasabah.exclude(id=nasabah.id).values_list(
        "bank_sampah_id", flat=True
    )
    return (
        Nasabah.objects.filter(bank_sampah_id__in=list(bank_lain), no_hp=no_hp)
        .exclude(user_id=user.id)
        .exists()
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
        field for field in FIELD_PROFIL_AKUN if getattr(user, field) != getattr(nasabah, field)
    ]
    if not berubah:
        return
    for field in berubah:
        setattr(user, field, getattr(nasabah, field))
    user.save(update_fields=[*berubah, "updated_at"])
