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

from rest_framework.exceptions import ValidationError

from api.models import Nasabah
from api.validators import normalize_indonesian_phone

# Email adalah kunci penautan keanggotaan ke akun Google, dan tidak ada
# penjaga lain pada jalur update: pemeriksaan email yang ada hanya keunikan
# dalam satu bank sampah dan validasi format. Tanpa penguncian ini pengurus
# dapat memindahkan keanggotaan ke alamat lain dan memutus tautan akunnya.
#
# Sisa profil sengaja tidak ikut terkunci. PIL-223 sempat mengunci keenamnya,
# lalu client memutuskan pengurus tetap perlu dapat memperbaiki data nasabah
# di lapangan (PIL-288).
FIELD_TERKUNCI = ("email",)


# Lima field profil yang ada di akun dan di catatan bank sampah. Email tidak
# ikut: ia kunci penautan, bukan data profil yang dibandingkan atau disalin.
FIELD_PROFIL = ("nama", "jenis_kelamin", "tanggal_lahir", "alamat", "no_hp")


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


def profil_akun(nasabah: Nasabah) -> dict[str, Any] | None:
    """Profil yang diisikan nasabah sendiri pada akunnya, atau ``None`` bila
    keanggotaan ini belum tertaut ke akun."""
    user = nasabah.user
    if user is None:
        return None
    return {field: getattr(user, field) for field in FIELD_PROFIL}


def profil_berbeda(nasabah: Nasabah) -> list[str]:
    """Field yang isinya di catatan bank sampah berbeda dari profil akun."""
    akun = profil_akun(nasabah)
    if akun is None:
        return []
    return [
        field
        for field in FIELD_PROFIL
        if _nilai_banding(field, akun[field]) != _nilai_banding(field, getattr(nasabah, field))
    ]


def _nilai_banding(field: str, nilai: Any) -> Any:
    """Nomor HP dibandingkan dalam bentuk +62, karena baris yang ditulis di luar
    serializer dapat menyimpan ``08…`` untuk nomor yang sama dengan akunnya."""
    if field != "no_hp":
        return nilai
    try:
        return normalize_indonesian_phone(nilai)
    except ValidationError:
        return nilai


def sinkronkan_dari_akun(nasabah: Nasabah) -> None:
    """Salin profil akun ke catatan bank sampah ini, atas permintaan pengurus.

    Satu arah saja, dan hanya untuk baris ini: nomor anggota, email, dan status
    tidak disentuh, begitu pula akun dan keanggotaan di bank sampah lain.
    """
    akun = profil_akun(nasabah)
    if akun is None:
        return
    for field, nilai in akun.items():
        setattr(nasabah, field, nilai)
    nasabah.save(update_fields=[*akun, "updated_at"])
