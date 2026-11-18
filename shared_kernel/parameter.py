"""Validasi parameter query berupa UUID (PIL-482).

Nilai mentah yang bukan UUID membuat ORM memunculkan ValidationError Django,
yang tidak ditangani DRF dan berakhir 500. Seperti `search`, `periode` dan
`tipe`, nilai yang tidak valid dijawab 422 dengan kunci parameternya.
"""

from uuid import UUID

from rest_framework import serializers


def validasi_uuid(nilai: str, *, kunci: str) -> UUID:
    try:
        hasil: UUID = serializers.UUIDField().run_validation(nilai)
    except serializers.ValidationError as exc:
        raise serializers.ValidationError({kunci: exc.detail}) from exc
    return hasil
