import re

from rest_framework import serializers


def normalize_indonesian_phone(value):
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


def get_initials(name):
    parts = [part for part in name.split() if part]
    return "".join(part[0].upper() for part in parts[:2]) or "NA"
