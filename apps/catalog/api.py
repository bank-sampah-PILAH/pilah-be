"""Public port of the catalog context."""

from uuid import UUID

from api.models import BankSampah, JenisSampah


def get_active_jenis(bank: BankSampah, jenis_sampah_id: UUID) -> JenisSampah | None:
    return JenisSampah.objects.filter(id=jenis_sampah_id, bank_sampah=bank, is_active=True).first()
