"""Status transitions for Pengumuman (PIL-243 authoring, PIL-332 manage).

All workflow rules live here; views stay thin HTTP adapters. Payload problems
raise serializers.ValidationError (422 envelope); illegal from-states raise
TransisiStatusTidakValid (raw 400).
"""

import datetime
import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from api.models import Pengumuman, User
from apps.announcement.exceptions import TransisiStatusTidakValid


def _validate_jadwal(
    terbit_pada: datetime.datetime, masa_berlaku: datetime.datetime | None
) -> None:
    if masa_berlaku is not None and masa_berlaku <= terbit_pada:
        raise serializers.ValidationError(
            {"masa_berlaku_hingga": "Masa berlaku harus setelah waktu terbit"}
        )


class PengumumanService:
    @staticmethod
    @transaction.atomic
    def terbitkan(
        pengumuman_id: uuid.UUID,
        bank_sampah_id: uuid.UUID,
        *,
        oleh: User,
        terbit_pada: datetime.datetime | None,
        masa_berlaku_hingga: datetime.datetime | None = None,
    ) -> Pengumuman:
        """Publish now (terbit_pada None) or schedule (future terbit_pada).

        Allowed from draft only; the bank scoping is re-checked under lock so a
        concurrent cross-bank transition cannot slip through.
        """
        pengumuman = Pengumuman.objects.select_for_update().get(
            pk=pengumuman_id, bank_sampah_id=bank_sampah_id
        )
        if pengumuman.status != Pengumuman.Status.DRAFT:
            raise TransisiStatusTidakValid()
        resolved_terbit = (
            terbit_pada if terbit_pada is not None else (pengumuman.terbit_pada or timezone.now())
        )
        resolved_masa = (
            masa_berlaku_hingga
            if masa_berlaku_hingga is not None
            else pengumuman.masa_berlaku_hingga
        )
        _validate_jadwal(resolved_terbit, resolved_masa)
        pengumuman.status = Pengumuman.Status.TERBIT
        pengumuman.terbit_pada = resolved_terbit
        pengumuman.masa_berlaku_hingga = resolved_masa
        pengumuman.diterbitkan_oleh = oleh
        pengumuman.save(
            update_fields=[
                "status",
                "terbit_pada",
                "masa_berlaku_hingga",
                "diterbitkan_oleh",
                "updated_at",
            ]
        )
        return pengumuman

    @staticmethod
    @transaction.atomic
    def tarik(pengumuman_id: uuid.UUID, bank_sampah_id: uuid.UUID, *, oleh: User) -> Pengumuman:
        """Withdraw a published announcement; immediately invisible to nasabah."""
        pengumuman = Pengumuman.objects.select_for_update().get(
            pk=pengumuman_id, bank_sampah_id=bank_sampah_id
        )
        if pengumuman.status != Pengumuman.Status.TERBIT:
            raise TransisiStatusTidakValid()
        pengumuman.status = Pengumuman.Status.DITARIK
        pengumuman.ditarik_oleh = oleh
        pengumuman.ditarik_pada = timezone.now()
        pengumuman.save(update_fields=["status", "ditarik_oleh", "ditarik_pada", "updated_at"])
        return pengumuman

    @staticmethod
    def pasti_bisa_diubah(pengumuman: Pengumuman, *, hanya_draft: bool = False) -> None:
        """Edit/delete guard on the derived status: an announcement may be
        edited while draft or terjadwal (hanya_draft=False); a draft may be
        deleted. A published (or expired/withdrawn) one may not."""
        efektif = pengumuman.status_efektif()
        dapat_diubah = efektif == "draft" or (not hanya_draft and efektif == "terjadwal")
        if not dapat_diubah:
            raise TransisiStatusTidakValid(
                "Pengumuman yang sudah terbit atau ditarik tidak dapat diubah"
            )
