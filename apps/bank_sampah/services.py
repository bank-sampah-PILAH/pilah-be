import secrets
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from api.models import BankSampah, BankSampahApprovalLog, User
from apps.notification.api import DEFAULT_WA_TEMPLATE


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


class BankOnboardingService:
    """Bank-sampah registration and team-join onboarding (PR #64 review
    item 4): moved out of `authentication` so that context keeps only "who
    are you" — user, Google login, tokens, profile completion.
    """

    @staticmethod
    @transaction.atomic
    def register_bank_sampah(user: User, payload: Mapping[str, Any]) -> BankSampah:
        if user.role != User.Role.PENGELOLA:
            raise PermissionError("Hanya pengelola yang dapat mendaftarkan bank sampah")
        bank = user.bank_sampah
        if bank and bank.status == BankSampah.Status.ACTIVE:
            raise ValueError("Bank sampah sudah aktif")
        if bank and bank.status == BankSampah.Status.PENDING:
            raise ValueError("Pendaftaran bank sampah sedang diproses")
        if bank is None:
            bank = BankSampah()
        bank.nama = payload["nama"]
        bank.alamat = payload["alamat"]
        bank.kota = payload.get("kota", "")
        bank.no_hp_pic = payload["no_hp_pic"]
        bank.foto_kegiatan = payload["foto_kegiatan"]
        bank.status = BankSampah.Status.PENDING
        bank.is_active = False
        bank.wa_template = bank.wa_template or DEFAULT_WA_TEMPLATE
        bank.save()
        user.bank_sampah = bank
        user.is_primary_pengelola = True
        user.save(update_fields=["bank_sampah", "is_primary_pengelola", "updated_at"])
        return bank

    @staticmethod
    def accept_invite(user: User, token: str) -> tuple[BankSampah, str]:
        bank = BankSampah.objects.filter(
            invite_token=token, invite_token_expires__gt=timezone.now()
        ).first()
        if not bank or bank.status != BankSampah.Status.ACTIVE:
            raise ValueError("Tautan undangan tidak valid atau sudah kedaluwarsa")
        if user.role != User.Role.PENGELOLA:
            raise PermissionError("Hanya pengelola yang dapat menerima undangan")
        if user.bank_sampah_id == bank.id:
            return bank, "already_member"
        user_bank = user.bank_sampah
        if user_bank and user_bank.status in [
            BankSampah.Status.ACTIVE.value,
            BankSampah.Status.PENDING.value,
        ]:
            raise ValueError("Akun ini sudah tergabung dengan bank sampah")
        outcome = "join_success"
        user.bank_sampah = bank
        user.is_primary_pengelola = False
        if user.nama and user.no_hp and user.jenis_kelamin and user.tanggal_lahir:
            user.is_profile_complete = True
        user.save(
            update_fields=[
                "bank_sampah",
                "is_primary_pengelola",
                "is_profile_complete",
                "updated_at",
            ]
        )
        return bank, outcome


class TeamService:
    @staticmethod
    def generate_invite(bank: BankSampah) -> str:
        bank.invite_token = secrets.token_urlsafe(32)
        bank.invite_token_expires = timezone.now() + timedelta(days=3)
        bank.save(update_fields=["invite_token", "invite_token_expires", "updated_at"])
        return bank.invite_token
