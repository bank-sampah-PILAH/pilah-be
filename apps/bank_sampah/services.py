import secrets
import uuid
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from api.models import BankSampah, BankSampahApprovalLog, PengurusDikeluarkan, User
from apps.authentication.api import lock_for_onboarding
from apps.notification.api import DEFAULT_WA_TEMPLATE, queue_push

PENDING_ONLY_MESSAGE = "Hanya pengajuan berstatus menunggu yang dapat diproses"


class ApprovalService:
    @staticmethod
    def _lock_pending(bank: BankSampah) -> None:
        """Lock the row, refresh the caller's instance, and require PENDING.

        The caller's instance may be stale (loaded before a concurrent
        decision), so the status check must run on the locked row.
        """
        BankSampah.objects.select_for_update().get(pk=bank.pk)
        bank.refresh_from_db()
        if bank.status != BankSampah.Status.PENDING:
            raise ValueError(PENDING_ONLY_MESSAGE)

    @staticmethod
    @transaction.atomic
    def approve(bank: BankSampah, superadmin: User, catatan: str = "") -> BankSampahApprovalLog:
        ApprovalService._lock_pending(bank)
        bank.status = BankSampah.Status.ACTIVE
        bank.is_active = True
        bank.save(update_fields=["status", "is_active", "updated_at"])
        for manager in User.objects.filter(
            bank_sampah=bank, is_primary_pengelola=True, is_active=True
        ):
            queue_push(
                manager,
                title="Pendaftaran disetujui",
                body=f"{bank.nama} sudah aktif. Anda dapat mulai mengelola bank sampah.",
            )
        return BankSampahApprovalLog.objects.create(
            bank_sampah=bank,
            superadmin=superadmin,
            status=BankSampahApprovalLog.Status.APPROVED,
            catatan=catatan,
        )

    @staticmethod
    @transaction.atomic
    def reject(bank: BankSampah, superadmin: User, catatan: str = "") -> BankSampahApprovalLog:
        ApprovalService._lock_pending(bank)
        bank.status = BankSampah.Status.REJECTED
        bank.is_active = False
        bank.save(update_fields=["status", "is_active", "updated_at"])
        for manager in User.objects.filter(
            bank_sampah=bank, is_primary_pengelola=True, is_active=True
        ):
            queue_push(
                manager,
                title="Pendaftaran perlu diperbaiki",
                body=f"Pendaftaran {bank.nama} belum disetujui. Periksa catatan dan ajukan kembali.",
            )
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
        lock_for_onboarding(user)
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
        bank.latitude = payload.get("latitude")
        bank.longitude = payload.get("longitude")
        bank.status = BankSampah.Status.PENDING
        bank.is_active = False
        bank.wa_template = bank.wa_template or DEFAULT_WA_TEMPLATE
        bank.save()
        user.bank_sampah = bank
        user.is_primary_pengelola = True
        user.save(update_fields=["bank_sampah", "is_primary_pengelola", "updated_at"])
        for admin in User.objects.filter(role=User.Role.SUPERADMIN, is_active=True):
            queue_push(
                admin,
                title="Pendaftaran bank sampah baru",
                body=f"{bank.nama} menunggu peninjauan Anda.",
            )
        return bank

    @staticmethod
    @transaction.atomic
    def accept_invite(user: User, token: str) -> tuple[BankSampah, str]:
        lock_for_onboarding(user)
        bank = BankSampah.objects.filter(
            invite_token=token, invite_token_expires__gt=timezone.now()
        ).first()
        if not bank:
            raise ValueError("Tautan undangan tidak valid atau sudah kedaluwarsa")
        if bank.status != BankSampah.Status.ACTIVE or not bank.is_active:
            raise ValueError("Undangan tidak dapat digunakan karena bank sampah tidak aktif")
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

    @staticmethod
    def transfer_primary(caller: User, target_id: uuid.UUID) -> User:
        """Hand the Pengurus Utama role to another pengurus of the same bank.

        Locks the bank row so two handovers cannot interleave, re-reads the
        caller under that lock (a stale request must not hand over twice), and
        demotes the caller before promoting the target: the unique constraint
        is immediate, so the order is not optional.
        """
        assert caller.bank_sampah_id is not None  # ponytail: IsPrimaryPengelola gates this
        with transaction.atomic():
            bank = BankSampah.objects.select_for_update().get(pk=caller.bank_sampah_id)
            current = User.objects.select_for_update().get(pk=caller.pk)
            if not current.is_primary_pengelola or current.bank_sampah_id != bank.pk:
                raise PermissionError("Hanya Pengurus Utama yang dapat menyerahkan jabatan")
            if target_id == current.pk:
                raise ValueError("Tidak dapat menyerahkan jabatan kepada diri sendiri")
            target = (
                User.objects.select_for_update()
                .filter(pk=target_id, bank_sampah=bank, role=User.Role.PENGELOLA, is_active=True)
                .first()
            )
            if target is None:
                raise LookupError("Pengurus tidak ditemukan di bank sampah ini")
            current.is_primary_pengelola = False
            current.save(update_fields=["is_primary_pengelola", "updated_at"])
            TeamService._promote(target)
        queue_push(
            target,
            title="Anda kini Pengurus Utama",
            body=f"Anda sekarang menjadi Pengurus Utama {bank.nama}.",
        )
        return target

    @staticmethod
    def _promote(target: User) -> None:
        target.is_primary_pengelola = True
        target.save(update_fields=["is_primary_pengelola", "updated_at"])

    @staticmethod
    def remove_member(caller: User, member_id: uuid.UUID) -> None:
        """Take a pengurus out of the caller's bank, keeping their history.

        Only the bank link is cut; the account, its transactions and its
        approval records stay. The invite link is rotated away because it may
        have been shared with the person being removed. Like ``transfer_primary``
        it re-reads the caller under the bank lock: a handover that committed
        while this request waited must not let the stale caller remove the new
        Pengurus Utama.
        """
        assert caller.bank_sampah_id is not None  # ponytail: IsPrimaryPengelola gates this
        if member_id == caller.pk:
            raise ValueError("Tidak dapat mengeluarkan diri sendiri dari bank sampah")
        with transaction.atomic():
            bank = BankSampah.objects.select_for_update().get(pk=caller.bank_sampah_id)
            current = User.objects.select_for_update().get(pk=caller.pk)
            if not current.is_primary_pengelola or current.bank_sampah_id != bank.pk:
                raise PermissionError("Hanya Pengurus Utama yang dapat mengeluarkan pengurus")
            member = (
                User.objects.select_for_update()
                .filter(pk=member_id, bank_sampah=bank, role=User.Role.PENGELOLA, is_active=True)
                .first()
            )
            if member is None:
                raise LookupError("Pengurus tidak ditemukan di bank sampah ini")
            member.bank_sampah = None
            member.is_primary_pengelola = False
            member.save(update_fields=["bank_sampah", "is_primary_pengelola", "updated_at"])
            PengurusDikeluarkan.objects.create(
                user=member, bank_sampah=bank, dikeluarkan_oleh=current
            )
            bank.invite_token = ""
            bank.invite_token_expires = None
            bank.save(update_fields=["invite_token", "invite_token_expires", "updated_at"])
