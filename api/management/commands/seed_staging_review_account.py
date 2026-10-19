from argparse import ArgumentParser

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api.models import User
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


class Command(BaseCommand):
    help = "Create the staging password reviewer accounts."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--confirm", required=True)

    def handle(self, *args: object, **options: object) -> None:
        self._validate_runtime(str(options["confirm"]))
        password = settings.PILAH_REVIEW_ACCOUNT_PASSWORD

        with transaction.atomic():
            for email, name, role in REVIEW_ACCOUNTS:
                user = self._existing_user(email, role)
                if user is None:
                    User.objects.create_user(
                        email=email,
                        nama=name,
                        role=role,
                        is_profile_complete=True,
                        password=password,
                    )
                    continue

                fields = []
                if user.email != email:
                    user.email = email
                    fields.append("email")
                if not user.nama:
                    user.nama = name
                    fields.append("nama")
                if not user.is_profile_complete:
                    user.is_profile_complete = True
                    fields.append("is_profile_complete")
                if not user.check_password(password):
                    user.set_password(password)
                    fields.append("password")
                if fields:
                    user.save(update_fields=[*fields, "updated_at"])

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
    def _existing_user(email: str, role: str) -> User | None:
        matches = list(
            User.objects.select_for_update().filter(email__iexact=email).order_by("pk")[:2]
        )
        if len(matches) > 1:
            raise CommandError("Staging reviewer account identity conflicts with existing data")
        if not matches:
            return None

        user = matches[0]
        if (
            user.role != role
            or not user.is_active
            or user.bank_sampah_id is not None
            or user.is_primary_pengelola
            or user.keanggotaan_nasabah.exists()
            or user.google_id is not None
            or user.is_staff
            or user.is_superuser
        ):
            raise CommandError("Staging reviewer account identity conflicts with existing data")
        return user
