from django.db import transaction

from api.models import Nasabah, NasabahApprovalLog, User


class NasabahApprovalService:
    @staticmethod
    @transaction.atomic
    def approve(nasabah: Nasabah, pengurus: User, catatan: str = "") -> NasabahApprovalLog:
        nasabah.status = Nasabah.Status.APPROVED
        nasabah.is_active = True
        nasabah.save(update_fields=["status", "is_active", "updated_at"])
        return NasabahApprovalLog.objects.create(
            nasabah=nasabah,
            pengurus=pengurus,
            status=NasabahApprovalLog.Status.APPROVED,
            catatan=catatan,
        )

    @staticmethod
    @transaction.atomic
    def reject(nasabah: Nasabah, pengurus: User, catatan: str = "") -> NasabahApprovalLog:
        nasabah.status = Nasabah.Status.REJECTED
        nasabah.is_active = False
        nasabah.save(update_fields=["status", "is_active", "updated_at"])
        return NasabahApprovalLog.objects.create(
            nasabah=nasabah,
            pengurus=pengurus,
            status=NasabahApprovalLog.Status.REJECTED,
            catatan=catatan,
        )
