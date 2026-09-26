import secrets
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, cast

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, Nasabah, User
from apps.notify.api import DEFAULT_WA_TEMPLATE


class AuthService:
    @staticmethod
    def login_with_google(raw_id_token: str) -> dict[str, Any]:
        profile = AuthService._verify_google_token(raw_id_token)
        email = profile["email"]
        google_id = profile["sub"]
        name = profile.get("name") or email.split("@")[0]
        # Google proves identity, not a user's PILAH authorization.
        role = profile.get("_pilah_dev_role", User.Role.PENGELOLA)

        user = User.objects.filter(email=email).first()
        is_new_user = user is None
        if user is None:
            user = User.objects.create_user(
                email=email,
                google_id=google_id,
                nama=name,
                role=role,
                is_profile_complete=False,
            )
        else:
            updates = []
            nama_was_empty = not user.nama
            if not user.google_id:
                user.google_id = google_id
                updates.append("google_id")
            if not user.nama:
                user.nama = name
                updates.append("nama")
            if updates:
                user.save(update_fields=updates)

        # PIL-154: nasabah added by pengurus via email syncs with the Google
        # account on first login — prefill empty User fields, never overwrite.
        # The token-derived nama yields to the pengurus-entered nasabah name
        # whenever it was empty before this sync (new accounts included).
        nasabah = Nasabah.objects.filter(email__iexact=user.email, is_active=True).first()
        if nasabah:
            profile_updates = []
            for user_field, nasabah_field in (
                ("nama", "nama"),
                ("no_hp", "no_hp"),
                ("jenis_kelamin", "jenis_kelamin"),
                ("tanggal_lahir", "tanggal_lahir"),
            ):
                fillable = user_field == "nama" and (is_new_user or nama_was_empty)
                if (fillable or not getattr(user, user_field)) and getattr(nasabah, nasabah_field):
                    setattr(user, user_field, getattr(nasabah, nasabah_field))
                    profile_updates.append(user_field)
            # Only a fully-populated profile counts as complete — a nasabah
            # record may itself be missing jenis_kelamin/tanggal_lahir, and
            # flagging complete here would lock /onboarding/profile out.
            if profile_updates and all(
                getattr(user, f) for f in ("nama", "no_hp", "jenis_kelamin", "tanggal_lahir")
            ):
                user.is_profile_complete = True
                profile_updates.append("is_profile_complete")
            if profile_updates:
                user.save(update_fields=profile_updates)

        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        if user.bank_sampah_id:
            access["bank_sampah_id"] = str(user.bank_sampah_id)
        access["role"] = user.role
        access["email"] = user.email
        bank = user.bank_sampah
        state = AuthService.user_state(user)
        return {
            "access_token": str(access),
            "refresh_token": str(refresh),
            "token_type": "Bearer",
            "expires_in": int(
                cast(timedelta, settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"]).total_seconds()
            ),
            "user": {
                "id": str(user.id),
                "name": user.nama,
                "nama": user.nama,
                "email": user.email,
                "role": user.role,
                "bank_sampah_id": str(user.bank_sampah_id) if user.bank_sampah_id else None,
                "bank_sampah_nama": bank.nama if bank else None,
                "bank_sampah_status": bank.status if bank else None,
                "is_profile_complete": user.is_profile_complete,
                "is_primary_pengelola": user.is_primary_pengelola,
                "state": state,
            },
            "next_step": state,
            "is_new_user": is_new_user,
        }

    @staticmethod
    def user_state(user: User) -> str:
        if user.role == User.Role.SUPERADMIN:
            return "superadmin_dashboard"
        if user.role == User.Role.PENGELOLA_INDUK:
            return "pengelola_induk_dashboard"
        if user.role == User.Role.NASABAH:
            return "nasabah_dashboard"
        if not user.is_profile_complete:
            return "complete_profile"
        bank = user.bank_sampah
        if not user.bank_sampah_id or bank is None:
            return "register_bank_sampah"
        if bank.status == BankSampah.Status.PENDING:
            return "approval_pending"
        if bank.status == BankSampah.Status.REJECTED:
            return "registration_rejected"
        return "dashboard"

    @staticmethod
    def _verify_google_token(raw_id_token: str) -> Mapping[str, Any]:
        if settings.PILAH_ALLOW_FAKE_GOOGLE_TOKEN:
            dev_roles = {
                "dev-superadmin:": ("dev-superadmin", User.Role.SUPERADMIN),
                "dev-pengelola-induk:": ("dev-pengelola-induk", User.Role.PENGELOLA_INDUK),
                "dev-nasabah:": ("dev-nasabah", User.Role.NASABAH),
            }
            for prefix, (subject_prefix, role) in dev_roles.items():
                if raw_id_token.startswith(prefix):
                    _, email, name = (raw_id_token.split(":", 2) + [""])[:3]
                    return {
                        "sub": f"{subject_prefix}-{email}",
                        "email": email,
                        "name": name or email.split("@")[0],
                        "_pilah_dev_role": role,
                    }
        if settings.PILAH_ALLOW_FAKE_GOOGLE_TOKEN and raw_id_token.startswith("dev:"):
            _, email, name = (raw_id_token.split(":", 2) + [""])[:3]
            return {"sub": f"dev-{email}", "email": email, "name": name or email.split("@")[0]}
        audience = settings.GOOGLE_CLIENT_ID or None
        try:
            profile = google_id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]  # google-auth ships no stubs
                raw_id_token, google_requests.Request(), audience
            )
        except Exception as exc:
            raise serializers.ValidationError(
                {"id_token": ["ID Token invalid atau expired"]}
            ) from exc
        verified_profile = cast(Mapping[str, Any], profile)
        profile_subject = verified_profile.get("sub")
        profile_email = verified_profile.get("email")
        if (
            not isinstance(profile_subject, str)
            or not profile_subject
            or not isinstance(profile_email, str)
            or not profile_email
        ):
            raise serializers.ValidationError(
                {"id_token": ["ID Token tidak memuat email atau subject yang diperlukan"]}
            )
        return {
            "sub": profile_subject,
            "email": profile_email,
            "name": verified_profile.get("name"),
        }


class OnboardingService:
    @staticmethod
    @transaction.atomic
    def complete_profile(user: User, profile_data: Mapping[str, Any]) -> User:
        if user.is_profile_complete:
            raise ValueError("Profil sudah lengkap")
        for field, value in profile_data.items():
            setattr(user, field, value)
        user.is_profile_complete = True
        user.save(
            update_fields=[
                "nama",
                "no_hp",
                "jenis_kelamin",
                "tanggal_lahir",
                "is_profile_complete",
                "updated_at",
            ]
        )
        return user

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
    @transaction.atomic
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
