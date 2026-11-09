import re
from datetime import date

from django.utils import timezone
from rest_framework import serializers


def normalize_indonesian_phone(value: str) -> str:
    if not value:
        raise serializers.ValidationError("Format nomor tidak valid. Contoh: 081234567890")
    digits = re.sub(r"\D", "", value)
    if digits.startswith("62"):
        national = digits[2:]
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        national = digits
    if not national.startswith("8") or not 9 <= len(national) <= 13:
        raise serializers.ValidationError("Format nomor tidak valid. Contoh: 081234567890")
    return f"+62{national}"


def tanggal_lahir_valid(value: date | None) -> date | None:
    """Tanggal lahir yang diterima, atau ``None``.

    ``None`` lolos sejak PIL-478: tanggal lahir tidak lagi wajib, dan temuan
    UAT menyebutnya terlalu sensitif untuk diminta. Penjagaannya tetap ada
    untuk tanggal yang mustahil.

    Pemeriksaan ``None`` bukan kehati-hatian berlebih. DRF memanggil
    ``validate_<field>`` setiap kali kuncinya ada di payload, termasuk ketika
    nilainya ``null``, jadi membandingkan ``None`` dengan sebuah tanggal
    melempar ``TypeError`` dan keluar sebagai 500 alih-alih penolakan yang
    dapat dibaca klien. Form yang mengosongkan tanggal mengirim tepat itu.
    """
    if value is not None and value > timezone.localdate():
        raise serializers.ValidationError("Tanggal lahir tidak boleh di masa depan")
    return value


def get_initials(name: str) -> str:
    parts = [part for part in name.split() if part]
    return "".join(part[0].upper() for part in parts[:2]) or "NA"
