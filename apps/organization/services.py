from django.db import transaction

from api.models import BankSampah, BankSampahApprovalLog, User


class ApprovalService:
    @staticmethod
    @transaction.atomic
    def approve(bank: BankSampah, superadmin: User, catatan: str = "") -> BankSampahApprovalLog:
        bank.status = BankSampah.Status.ACTIVE
        bank.is_active = True
        bank.save(update_fields=["status", "is_active", "updated_at"])
        return BankSampahApprovalLog.objects.create(
            bank_sampah=bank,
            superadmin=superadmin,
            status=BankSampahApprovalLog.Status.APPROVED,
            catatan=catatan,
        )

    @staticmethod
    @transaction.atomic
    def reject(bank: BankSampah, superadmin: User, catatan: str = "") -> BankSampahApprovalLog:
        bank.status = BankSampah.Status.REJECTED
        bank.is_active = False
        bank.save(update_fields=["status", "is_active", "updated_at"])
        return BankSampahApprovalLog.objects.create(
            bank_sampah=bank,
            superadmin=superadmin,
            status=BankSampahApprovalLog.Status.REJECTED,
            catatan=catatan,
        )
