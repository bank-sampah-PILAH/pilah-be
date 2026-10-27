from argparse import ArgumentParser
from uuid import UUID

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from api.management.commands.seed_testing_data import ACTIVE_BANK_ID
from api.models import BankSampah, Nasabah, User
from apps.bank_sampah.constants import REVIEW_BANK_ID
from shared_kernel.permissions import (
    email_verification_exempt_allowlist,
    review_superadmin_allowlist,
    superadmin_allowlist,
)

CONFIRMATION = "SEED-PILAH-STAGING-REVIEW-ACCOUNT"
REVIEW_PENGELOLA_EMAIL = "pilah.pengelola@pilah.com"
REVIEW_NASABAH_EMAIL = "pilah.nasabah@pilah.com"
REVIEW_SUPERADMIN_EMAIL = "pilah.superadmin@pilah.com"
REVIEW_ACCOUNTS = (
    (REVIEW_PENGELOLA_EMAIL, "Demo Pengelola PILAH", User.Role.PENGELOLA),
    ("pilah.pengurus@pilah.com", "Demo Pengurus PILAH", User.Role.PENGELOLA),
    (REVIEW_NASABAH_EMAIL, "Demo Nasabah PILAH", User.Role.NASABAH),
    (REVIEW_SUPERADMIN_EMAIL, "SuperAdmin PILAH", User.Role.SUPERADMIN),
)
REVIEW_NASABAH_ID = UUID("00000000-0000-4000-8000-000000000800")
REVIEW_NASABAH_NUMBER = "NAS-REVIEWER"
REVIEW_NASABAH_PHONE = "+6285550000800"
REVIEW_NASABAH_ADDRESS = "Alamat demo untuk akun nasabah PILAH"
REVIEW_BANK_NAME = "Bank Sampah PILAH Review Pending"


class Command(BaseCommand):
    help = "Create the staging password reviewer accounts."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--confirm", required=True)

    def handle(self, *args: object, **options: object) -> None:
        self._validate_runtime(str(options["confirm"]))
        password = settings.PILAH_REVIEW_ACCOUNT_PASSWORD

        with transaction.atomic():
            bank = self._review_bank()
            self._ensure_review_bank()
            for email, name, role in REVIEW_ACCOUNTS:
                user = self._existing_user(email, role, bank)
                if user is None:
                    user = self._create_user(email, name, role, bank, password)
                else:
                    self._update_user(user, email, name, role, bank, password)
                if role == User.Role.NASABAH:
                    self._ensure_nasabah_membership(bank, user)

        self.stdout.write(self.style.SUCCESS("Staging reviewer accounts are ready."))

    @staticmethod
    def _create_user(email: str, name: str, role: str, bank: BankSampah, password: str) -> User:
        return User.objects.create_user(
            email=email,
            nama=name,
            role=role,
            is_profile_complete=True,
            password=password,
            bank_sampah=bank if role == User.Role.PENGELOLA else None,
            is_primary_pengelola=email == REVIEW_PENGELOLA_EMAIL,
            no_hp=REVIEW_NASABAH_PHONE if role == User.Role.NASABAH else "",
            alamat=REVIEW_NASABAH_ADDRESS if role == User.Role.NASABAH else "",
        )

    @staticmethod
    def _update_user(
        user: User, email: str, name: str, role: str, bank: BankSampah, password: str
    ) -> None:
        fields: list[str] = []
        if user.bank_sampah_id is None and role == User.Role.PENGELOLA:
            user.bank_sampah = bank
            fields.append("bank_sampah")
        primary = email == REVIEW_PENGELOLA_EMAIL
        if user.is_primary_pengelola != primary:
            user.is_primary_pengelola = primary
            fields.append("is_primary_pengelola")
        if user.email != email:
            user.email = email
            fields.append("email")
        if not user.nama:
            user.nama = name
            fields.append("nama")
        if not user.is_profile_complete:
            user.is_profile_complete = True
            fields.append("is_profile_complete")
        if role == User.Role.NASABAH and not user.no_hp:
            user.no_hp = REVIEW_NASABAH_PHONE
            fields.append("no_hp")
        if role == User.Role.NASABAH and not user.alamat:
            user.alamat = REVIEW_NASABAH_ADDRESS
            fields.append("alamat")
        if not user.check_password(password):
            user.set_password(password)
            fields.append("password")
        if fields:
            user.save(update_fields=[*fields, "updated_at"])

    @staticmethod
    def _validate_runtime(confirmation: str) -> None:
        if settings.PILAH_ENVIRONMENT != "staging" or settings.DEBUG:
            raise CommandError(
                "The reviewer account can only be seeded in staging with DEBUG=false"
            )
        if confirmation != CONFIRMATION:
            raise CommandError(
                f"Pass --confirm={CONFIRMATION} to seed the staging reviewer account"
            )
        if (
            REVIEW_SUPERADMIN_EMAIL in superadmin_allowlist()
            or REVIEW_SUPERADMIN_EMAIL not in review_superadmin_allowlist()
        ):
            raise CommandError("The reviewer email must be in PILAH_REVIEW_SUPERADMIN_EMAILS only")
        if not {email for email, _name, _role in REVIEW_ACCOUNTS}.issubset(
            email_verification_exempt_allowlist()
        ):
            raise CommandError(
                "All reviewer emails must be in PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS"
            )

        password = settings.PILAH_REVIEW_ACCOUNT_PASSWORD
        if not password.strip():
            raise CommandError("PILAH_REVIEW_ACCOUNT_PASSWORD must be configured on Fly staging")
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError(
                "PILAH_REVIEW_ACCOUNT_PASSWORD does not meet password requirements"
            ) from exc

    @staticmethod
    def _review_bank() -> BankSampah:
        bank = BankSampah.objects.select_for_update().filter(pk=ACTIVE_BANK_ID).first()
        if bank is None or not bank.is_active or bank.status != BankSampah.Status.ACTIVE:
            raise CommandError("An active staging E2E bank is required before reviewer accounts")
        return bank

    @staticmethod
    def _ensure_review_bank() -> None:
        bank = BankSampah.objects.select_for_update().filter(pk=REVIEW_BANK_ID).first()
        if bank is None:
            BankSampah.objects.create(
                id=REVIEW_BANK_ID,
                nama=REVIEW_BANK_NAME,
                alamat="Alamat sintetis untuk peninjauan PILAH",
                kota="Depok",
                no_hp_pic="",
                jenis_organisasi=BankSampah.OrganizationType.MANDIRI,
                status=BankSampah.Status.PENDING,
                is_active=False,
            )
            return
        if (
            bank.nama != REVIEW_BANK_NAME
            or bank.jenis_organisasi != BankSampah.OrganizationType.MANDIRI
            or bank.parent_id is not None
            or bank.status not in BankSampah.Status.values
            or bank.is_active != (bank.status == BankSampah.Status.ACTIVE)
        ):
            raise CommandError("Staging review bank identity conflicts with existing data")

    @staticmethod
    def _existing_user(email: str, role: str, bank: BankSampah) -> User | None:
        matches = list(
            User.objects.select_for_update().filter(email__iexact=email).order_by("pk")[:2]
        )
        if len(matches) > 1:
            raise CommandError("Staging reviewer account identity conflicts with existing data")
        if not matches:
            return None

        user = matches[0]
        expected_bank_id = bank.pk if role == User.Role.PENGELOLA else None
        if (
            user.role != role
            or not user.is_active
            or user.bank_sampah_id not in (None, expected_bank_id)
            or (user.is_primary_pengelola and email != REVIEW_PENGELOLA_EMAIL)
            or (role != User.Role.NASABAH and user.keanggotaan_nasabah.exists())
            or user.google_id is not None
            or user.is_staff
            or user.is_superuser
        ):
            raise CommandError("Staging reviewer account identity conflicts with existing data")
        return user

    @staticmethod
    def _ensure_nasabah_membership(bank: BankSampah, user: User) -> None:
        matches = list(
            Nasabah.objects.select_for_update()
            .filter(
                Q(pk=REVIEW_NASABAH_ID)
                | (Q(bank_sampah=bank) & (Q(user=user) | Q(email__iexact=REVIEW_NASABAH_EMAIL)))
            )
            .order_by("pk")[:2]
        )
        if len(matches) > 1:
            raise CommandError("Staging reviewer membership identity conflicts with existing data")
        if not matches:
            Nasabah.objects.create(
                id=REVIEW_NASABAH_ID,
                user=user,
                bank_sampah=bank,
                nomor=REVIEW_NASABAH_NUMBER,
                nama="Demo Nasabah PILAH",
                alamat=REVIEW_NASABAH_ADDRESS,
                no_hp=REVIEW_NASABAH_PHONE,
                email=REVIEW_NASABAH_EMAIL,
                is_active=True,
                status=Nasabah.Status.APPROVED,
            )
            return

        membership = matches[0]
        if (
            membership.pk != REVIEW_NASABAH_ID
            or membership.bank_sampah_id != bank.pk
            or membership.user_id not in (None, user.pk)
            or membership.email.lower() != REVIEW_NASABAH_EMAIL
            or not membership.is_active
            or membership.status != Nasabah.Status.APPROVED
        ):
            raise CommandError("Staging reviewer membership identity conflicts with existing data")
        if membership.user_id is None:
            membership.user = user
            membership.save(update_fields=["user", "updated_at"])
