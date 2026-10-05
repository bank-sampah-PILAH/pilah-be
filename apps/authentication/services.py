from collections.abc import Mapping
from datetime import timedelta
from typing import Any, cast

from django.conf import settings
from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, Nasabah, NasabahApprovalLog, Saldo, User
from shared_kernel.permissions import superadmin_allowlist

REGISTRATION_TOKEN_MAX_AGE = 600
REGISTRATION_TOKEN_SALT = "pilah-google-registration"


class AuthServiceError(Exception):
    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class AuthService:
    @staticmethod
    def register_with_google(registration_token: str, role: str) -> tuple[dict[str, Any], bool]:
        try:
            profile = cast(
                Mapping[str, Any],
                signing.loads(
                    registration_token,
                    salt=REGISTRATION_TOKEN_SALT,
                    max_age=REGISTRATION_TOKEN_MAX_AGE,
                ),
            )
        except signing.SignatureExpired as exc:
            raise AuthServiceError(
                "Sesi pendaftaran kedaluwarsa. Silakan masuk dengan Google lagi.",
                code="registration_token_expired",
                status_code=400,
            ) from exc
        except signing.BadSignature as exc:
            raise AuthServiceError(
                "Sesi pendaftaran tidak valid. Silakan masuk dengan Google lagi.",
                code="registration_token_invalid",
                status_code=400,
            ) from exc

        email = str(profile.get("email") or "").strip().lower()
        google_id = str(profile.get("sub") or "")
        name = str(profile.get("name") or email.split("@")[0])
        if not email or not google_id:
            raise AuthServiceError(
                "Sesi pendaftaran tidak valid. Silakan masuk dengan Google lagi.",
                code="registration_token_invalid",
                status_code=400,
            )

        user = AuthService._user_for_email(email)
        created = False
        if user is None:
            is_allowlisted = superadmin_allowlist().__contains__(email.lower().strip())
            registered_role = User.Role.SUPERADMIN if is_allowlisted else role
            try:
                with transaction.atomic():
                    user = User.objects.create_user(
                        email=email,
                        google_id=google_id,
                        nama=name,
                        role=registered_role,
                        is_profile_complete=is_allowlisted,
                        is_staff=is_allowlisted,
                        is_superuser=is_allowlisted,
                    )
                    created = True
            except IntegrityError:
                user = AuthService._user_for_email(email)
                if user is None:
                    raise

        AuthService._enforce_superadmin_allowlist(user, email)
        AuthService._update_google_identity(user, google_id, name)
        return AuthService._session_response(user, is_new_user=created), created

    @staticmethod
    def _user_for_email(email: str) -> User | None:
        matches = list(User.objects.filter(email__iexact=email)[:2])
        if len(matches) > 1:
            raise AuthServiceError(
                "Beberapa akun menggunakan alamat email ini. Hubungi dukungan untuk memperbaikinya.",
                code="ambiguous_email_match",
                status_code=409,
            )
        return matches[0] if matches else None

    @staticmethod
    def _superadmin_not_allowlisted() -> AuthServiceError:
        return AuthServiceError(
            "Email Superadmin tidak terdaftar pada whitelist",
            code="superadmin_not_allowlisted",
            status_code=403,
        )

    @staticmethod
    def _enforce_superadmin_allowlist(user: User, email: str) -> None:
        if user.role != User.Role.SUPERADMIN:
            return
        if not AuthService._sync_superadmin_admin_flags(user, email):
            raise AuthService._superadmin_not_allowlisted()

    @staticmethod
    def _sync_superadmin_admin_flags(user: User, email: str) -> bool:
        is_allowlisted = AuthService.is_superadmin_allowlisted(email)
        if user.is_staff != is_allowlisted or user.is_superuser != is_allowlisted:
            user.is_staff = is_allowlisted
            user.is_superuser = is_allowlisted
            user.save(update_fields=["is_staff", "is_superuser", "updated_at"])
        return is_allowlisted

    @staticmethod
    def _update_google_identity(user: User, google_id: str, name: str) -> None:
        updates = []
        if not user.google_id:
            user.google_id = google_id
            updates.append("google_id")
        if not user.nama:
            user.nama = name
            updates.append("nama")
        if updates:
            user.save(update_fields=updates)

    @staticmethod
    def _registration_response(
        profile: Mapping[str, Any], email: str, google_id: str, name: str
    ) -> dict[str, Any]:
        registration_token = signing.dumps(
            {
                "sub": google_id,
                "email": email,
                "name": name,
                "picture": profile.get("picture") or "",
            },
            salt=REGISTRATION_TOKEN_SALT,
            compress=True,
        )
        return {
            "registration_required": True,
            "registration_token": registration_token,
            "expires_in": REGISTRATION_TOKEN_MAX_AGE,
            "google_profile": {
                "email": email,
                "name": name,
                "picture": profile.get("picture") or None,
            },
        }

    @staticmethod
    def _role_for_new_account(is_allowlisted: bool, dev_role: Any, nasabah: Nasabah | None) -> str:
        if is_allowlisted:
            return User.Role.SUPERADMIN
        if dev_role:
            return str(dev_role)
        # A Google-verified email matching an active Nasabah record
        # identifies a new account as Nasabah. Existing accounts keep
        # their assigned role, and _sync_nasabah_prefill links only
        # Nasabah users.
        if nasabah is not None:
            return User.Role.NASABAH
        return User.Role.PENGELOLA

    @staticmethod
    def _create_new_account(
        email: str, google_id: str, name: str, role: str, is_allowlisted: bool
    ) -> tuple[User, bool]:
        if role == User.Role.SUPERADMIN and not is_allowlisted:
            raise AuthService._superadmin_not_allowlisted()
        try:
            with transaction.atomic():
                return (
                    User.objects.create_user(
                        email=email,
                        google_id=google_id,
                        nama=name,
                        role=role,
                        is_profile_complete=role == User.Role.SUPERADMIN,
                        is_staff=role == User.Role.SUPERADMIN,
                        is_superuser=role == User.Role.SUPERADMIN,
                    ),
                    True,
                )
        except IntegrityError:
            # A concurrent Google request may have created this account
            # after the initial lookup. Authenticate that account instead
            # of turning a valid token into an uncaught server error.
            user = AuthService._user_for_email(email)
            if user is None:
                raise
            return user, False

    @staticmethod
    def login_with_google(raw_id_token: str) -> dict[str, Any]:
        profile = AuthService._verify_google_token(raw_id_token)
        email = str(profile["email"]).strip().lower()
        google_id = profile["sub"]
        name = profile.get("name") or email.split("@")[0]
        dev_role = profile.get("_pilah_dev_role")
        user = AuthService._user_for_email(email)
        nasabah = Nasabah.objects.filter(email__iexact=email, is_active=True).first()
        is_allowlisted = AuthService.is_superadmin_allowlisted(email)

        if user is None and nasabah is None and not is_allowlisted and dev_role is None:
            return AuthService._registration_response(profile, email, google_id, name)

        is_new_user = user is None
        if user is None:
            role = AuthService._role_for_new_account(is_allowlisted, dev_role, nasabah)
            user, is_new_user = AuthService._create_new_account(
                email, google_id, name, role, is_allowlisted
            )

        # Called for existing accounts and re-matched races; both are no-ops
        # for a just-created user (identity fields and flags already set).
        AuthService._enforce_superadmin_allowlist(user, email)
        AuthService._update_google_identity(user, google_id, str(name))
        AuthService._sync_nasabah_prefill(user)

        return AuthService._session_response(user, is_new_user=is_new_user)

    @staticmethod
    def _session_response(user: User, *, is_new_user: bool) -> dict[str, Any]:
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
                "no_hp": user.no_hp,
                "jenis_kelamin": user.jenis_kelamin,
                "tanggal_lahir": user.tanggal_lahir.isoformat() if user.tanggal_lahir else None,
                "alamat": user.alamat,
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
    def _sync_nasabah_prefill(user: User) -> None:
        """Claim a pengurus-entered membership on first matching,
        Google-verified login — but never copy its profile fields onto the
        user, nor the user's onto it. The account's profile and the bank
        sampah's record of the nasabah are separate data: the user fills
        theirs in via complete_profile, and the pengurus keeps theirs.

        Gated on role because a pengurus-entered email can coincidentally
        match an account that registered as something other than nasabah,
        and that account must not be silently turned into a member.
        """
        if user.role != User.Role.NASABAH:
            return
        nasabah = Nasabah.objects.filter(
            email__iexact=user.email, is_active=True, user__isnull=True
        ).first()
        if nasabah is None:
            return
        nasabah.user = user
        nasabah.save(update_fields=["user", "updated_at"])

    @staticmethod
    def user_state(user: User) -> str:
        if user.role == User.Role.SUPERADMIN:
            return "superadmin_dashboard"
        if not user.is_profile_complete:
            return "complete_profile"
        if user.role == User.Role.PENGELOLA_INDUK:
            return (
                "pengelola_induk_dashboard" if user.bank_sampah_id else "register_bank_sampah_induk"
            )
        if user.role == User.Role.NASABAH:
            # Routing doesn't gate on approval: a membership application, once
            # submitted, sends the user straight to their own beranda
            # regardless of status. Pending/rejected states — and appealing a
            # rejection by reapplying — are handled there (GET /nasabah/me),
            # not by stalling onboarding on a blocking screen.
            return "nasabah_dashboard" if user.keanggotaan_nasabah.exists() else "register_nasabah"
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
                "dev-pengelola:": ("dev-pengelola", User.Role.PENGELOLA),
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
        if verified_profile.get("email_verified") is not True:
            raise serializers.ValidationError({"id_token": ["Email Google belum terverifikasi"]})
        return {
            "sub": profile_subject,
            "email": profile_email,
            "name": verified_profile.get("name"),
            "picture": verified_profile.get("picture"),
        }

    @staticmethod
    def is_superadmin_allowlisted(email: str) -> bool:
        return email.strip().lower() in superadmin_allowlist()


NO_HP_TERPAKAI_DI_BANK = "Nomor HP ini sudah terdaftar di bank sampah ini, hubungi pengurus"


class OnboardingService:
    @staticmethod
    @transaction.atomic
    def complete_profile(user: User, profile_data: Mapping[str, Any]) -> User:
        # One-shot for pengelola, whose profile step gates their bank
        # registration. A nasabah owns their profile and may re-submit it at
        # any time, whatever their membership status.
        if user.is_profile_complete and user.role != User.Role.NASABAH:
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
                "alamat",
                "is_profile_complete",
                "updated_at",
            ]
        )
        return user

    @staticmethod
    @transaction.atomic
    def register_nasabah(user: User, payload: Mapping[str, Any]) -> Nasabah:
        if user.role != User.Role.NASABAH:
            raise PermissionError("Hanya nasabah yang dapat mengajukan keanggotaan")
        if not user.alamat.strip():
            raise ValueError("Lengkapi alamat pada profil Anda terlebih dahulu")

        bank = BankSampah.objects.filter(id=payload["bank_sampah_id"]).first()
        if (
            not bank
            or bank.status != BankSampah.Status.ACTIVE
            or not bank.is_active
            or bank.jenis_organisasi == BankSampah.OrganizationType.INDUK
        ):
            raise ValueError("Bank sampah tidak ditemukan atau belum tersedia")

        own_record = Nasabah.objects.filter(bank_sampah=bank, user=user).first()
        if own_record is not None:
            if own_record.status != Nasabah.Status.REJECTED:
                raise ValueError("Anda sudah terdaftar sebagai nasabah di bank sampah ini")
            # A rejection is correctable, not a permanent lockout: resubmit
            # the same row as a fresh application rather than raising.
            #
            # Conditional UPDATE, not own_record.save(): guards against two
            # concurrent reapply requests both passing the check above.
            # A losing request affects 0 rows and falls through to the
            # error below instead of silently double-applying.
            #
            # The account's phone is copied too, with the same collision guard
            # as a first application: it may now belong to another row here.
            if (
                Nasabah.objects.filter(bank_sampah=bank, no_hp=user.no_hp)
                .exclude(pk=own_record.pk)
                .exists()
            ):
                raise ValueError(NO_HP_TERPAKAI_DI_BANK)
            # The check above does not close the race: the same phone can be
            # committed elsewhere before this UPDATE, and the constraint then
            # refuses it. Savepoint so the refusal does not poison the outer
            # transaction before the ValueError leaves it.
            try:
                with transaction.atomic():
                    updated = Nasabah.objects.filter(
                        pk=own_record.pk, status=Nasabah.Status.REJECTED
                    ).update(
                        nama=user.nama,
                        jenis_kelamin=user.jenis_kelamin,
                        tanggal_lahir=user.tanggal_lahir,
                        alamat=user.alamat,
                        no_hp=user.no_hp,
                        status=Nasabah.Status.PENDING,
                        is_active=True,
                        updated_at=timezone.now(),
                    )
            except IntegrityError as exc:
                raise ValueError(NO_HP_TERPAKAI_DI_BANK) from exc
            if updated == 0:
                raise ValueError("Anda sudah terdaftar sebagai nasabah di bank sampah ini")
            own_record.refresh_from_db()
            Saldo.objects.get_or_create(nasabah=own_record)
            NasabahApprovalLog.objects.create(
                nasabah=own_record,
                pengurus=None,
                status=NasabahApprovalLog.Status.APPEALED,
                catatan=payload.get("pesan", ""),
            )
            return own_record

        # A pengurus-entered record for this same person converges onto
        # `own_record` above at first Google login (AuthService matches on
        # verified `email`, not on this self-declared `no_hp`), so reaching
        # here with a phone collision means it belongs to someone else.
        if Nasabah.objects.filter(bank_sampah=bank, no_hp=user.no_hp).exists():
            raise ValueError(NO_HP_TERPAKAI_DI_BANK)

        nasabah = Nasabah(
            bank_sampah=bank,
            user=user,
            nomor=OnboardingService._next_nasabah_nomor(bank),
            nama=user.nama,
            jenis_kelamin=user.jenis_kelamin,
            tanggal_lahir=user.tanggal_lahir,
            no_hp=user.no_hp,
            email=user.email,
            alamat=user.alamat,
            # A self-registration awaits pengurus review (PIL-188); the model
            # default of APPROVED is for records a pengurus enters directly,
            # who has already vetted them by typing them in.
            status=Nasabah.Status.PENDING,
        )
        for _ in range(5):
            try:
                with transaction.atomic():
                    nasabah.save()
                break
            except IntegrityError:
                nasabah.nomor = OnboardingService._next_nasabah_nomor(bank)
        else:
            raise ValueError("Gagal membuat nomor nasabah, silakan coba lagi")
        Saldo.objects.create(nasabah=nasabah)
        return nasabah

    @staticmethod
    def _next_nasabah_nomor(bank: BankSampah) -> str:
        count = Nasabah.objects.filter(bank_sampah=bank).count()
        return f"NAS-{count + 1:04d}"
