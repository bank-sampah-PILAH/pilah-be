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
from shared_kernel.permissions import (
    email_verification_exempt_allowlist,
    review_superadmin_allowlist,
    superadmin_allowlist,
)

CONFIRMATION = "SEED-PILAH-STAGING-REVIEW-ACCOUNT"
REVIEW_ACCOUNTS = (
    ("pilah.pengelola@pilah.com", "Demo Pengelola PILAH", User.Role.PENGELOLA),
    ("pilah.pengurus@pilah.com", "Demo Pengurus PILAH", User.Role.PENGELOLA),
    ("pilah.nasabah@pilah.com", "Demo Nasabah PILAH", User.Role.NASABAH),
    ("pilah.superadmin@pilah.com", "SuperAdmin PILAH", User.Role.SUPERADMIN),
)
REVIEW_SUPERADMIN_EMAIL = "pilah.superadmin@pilah.com"
REVIEW_NASABAH_ID = UUID("00000000-0000-4000-8000-000000000800")
REVIEW_NASABAH_NUMBER = "NAS-REVIEWER"
REVIEW_NASABAH_PHONE = "+6285550000800"
REVIEW_NASABAH_ADDRESS = "Alamat demo untuk akun nasabah PILAH"


class Command(BaseCommand):
    help = "Create the staging password reviewer accounts."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--confirm", required=True)

    def handle(self, *args: object, **options: object) -> None:
        self._validate_runtime(str(options["confirm"]))
        password = settings.PILAH_REVIEW_ACCOUNT_PASSWORD

        with transaction.atomic():
            bank = self._review_bank()
            for email, name, role in REVIEW_ACCOUNTS:
                user = self._existing_user(email, role, bank)
                if user is None:
                    user = User.objects.create_user(
                        email=email,
                        nama=name,
                        role=role,
                        is_profile_complete=True,
                        password=password,
                        **(
                            {
                                "bank_sampah": bank,
                                "is_primary_pengelola": False,
                            }
                            if role == User.Role.PENGELOLA
                            else {}
                        ),
                        **(
                            {
                                "no_hp": REVIEW_NASABAH_PHONE,
                                "alamat": REVIEW_NASABAH_ADDRESS,
                            }
                            if role == User.Role.NASABAH
                            else {}
                        ),
                    )
                else:
                    fields: list[str] = []
                    if user.bank_sampah_id is None and role == User.Role.PENGELOLA:
                        user.bank_sampah = bank
                        fields.extend(("bank_sampah", "is_primary_pengelola"))
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
                if role == User.Role.NASABAH:
                    self._ensure_nasabah_membership(bank, user)

        self.stdout.write(self.style.SUCCESS("Staging reviewer accounts are ready."))

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
        if bank is None:
            raise CommandError("The staging E2E bank is required before reviewer accounts")
        return bank

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
            or user.is_primary_pengelola
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
                Q(pk=REVIEW_NASABAH_ID) | Q(user=user) | Q(email__iexact="pilah.nasabah@pilah.com")
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
                email="pilah.nasabah@pilah.com",
                is_active=True,
                status=Nasabah.Status.APPROVED,
            )
            return

        membership = matches[0]
        if (
            membership.pk != REVIEW_NASABAH_ID
            or membership.bank_sampah_id != bank.pk
            or membership.user_id not in (None, user.pk)
            or membership.email.lower() != "pilah.nasabah@pilah.com"
        ):
            raise CommandError("Staging reviewer membership identity conflicts with existing data")
        if membership.user_id is None:
            membership.user = user
            membership.save(update_fields=["user", "updated_at"])
