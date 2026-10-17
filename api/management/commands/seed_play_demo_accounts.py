from argparse import ArgumentParser
from decimal import Decimal
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from api.models import BankSampah, Nasabah, Saldo, User
from shared_kernel.permissions import superadmin_allowlist

DEMO_BANK_ID = UUID("00000000-0000-4000-8000-000000000362")
DEMO_NASABAH_ID = UUID("00000000-0000-4000-8000-000000000363")
DEMO_BANK_NAME = "Bank Sampah PILAH Demo"
DEMO_NASABAH_NUMBER = "DEMO-0001"
DEMO_NASABAH_EMAIL = "pilah.nasabah@gmail.com"
SUPERADMIN_EMAIL = "pilah.superadmin@gmail.com"

ACCOUNTS = {
    "owner": ("pilah.pengelola@gmail.com", "Demo Pengelola PILAH", User.Role.PENGELOLA),
    "pengurus": ("pilah.pengurus@gmail.com", "Demo Pengurus PILAH", User.Role.PENGELOLA),
    "nasabah": (DEMO_NASABAH_EMAIL, "Demo Nasabah PILAH", User.Role.NASABAH),
    "superadmin": (SUPERADMIN_EMAIL, "SuperAdmin PILAH", User.Role.SUPERADMIN),
}


class Command(BaseCommand):
    help = "Create the explicit production Google demo accounts and their minimal sample data."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--confirm-production", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        dry_run = bool(options.get("dry_run"))
        self._validate_runtime(dry_run, bool(options.get("confirm_production")))

        with transaction.atomic():
            bank = self._existing_bank()
            users = {
                name: self._existing_user(email, role)
                for name, (email, _display_name, role) in ACCOUNTS.items()
            }
            membership = self._existing_membership(users["nasabah"])

            if dry_run:
                self.stdout.write(
                    "Dry run: validated production target; would ensure one demo bank, "
                    "4 Google accounts, an approved nasabah membership, and a balance "
                    "initialized to zero if missing."
                )
                return

            bank = bank or self._create_bank()
            for name, (email, display_name, role) in ACCOUNTS.items():
                users[name] = self._ensure_user(
                    users[name],
                    email=email,
                    display_name=display_name,
                    role=role,
                    bank=bank,
                    primary=name == "owner",
                )

            nasabah_user = users["nasabah"]
            if nasabah_user is None:
                raise CommandError("Production demo nasabah account could not be created")
            membership = membership or self._create_membership(bank, nasabah_user)
            if membership.user_id is None:
                membership.user = nasabah_user
                membership.save(update_fields=["user", "updated_at"])
            Saldo.objects.get_or_create(
                nasabah=membership,
                defaults={"total_saldo": Decimal("0.00")},
            )

        self.stdout.write(self.style.SUCCESS("Production Google demo accounts are ready."))

    @staticmethod
    def _validate_runtime(dry_run: bool, confirmed: bool) -> None:
        if settings.PILAH_ENVIRONMENT != "production" or settings.DEBUG:
            raise CommandError("Demo accounts can only be seeded in production with DEBUG=false")
        if SUPERADMIN_EMAIL not in superadmin_allowlist():
            raise CommandError("pilah.superadmin@gmail.com must be in PILAH_SUPERADMIN_EMAILS")
        if not dry_run and not confirmed:
            raise CommandError("Pass --confirm-production before writing production demo data")

    @staticmethod
    def _existing_bank() -> BankSampah | None:
        bank = BankSampah.objects.select_for_update().filter(pk=DEMO_BANK_ID).first()
        if bank is not None and (
            bank.nama != DEMO_BANK_NAME
            or bank.jenis_organisasi != BankSampah.OrganizationType.MANDIRI
            or bank.parent_id is not None
            or bank.status != BankSampah.Status.ACTIVE
            or not bank.is_active
        ):
            raise CommandError("Production demo bank identity conflicts with existing data")
        return bank

    @staticmethod
    def _existing_user(email: str, role: str) -> User | None:
        matches = list(User.objects.select_for_update().filter(email__iexact=email)[:2])
        if len(matches) > 1:
            raise CommandError(f"Production demo account conflict: {email} matches multiple users")
        if not matches:
            return None

        user = matches[0]
        if user.role != role or not user.is_active:
            raise CommandError(
                f"Production demo account conflict for {email}: role or active state"
            )
        if role == User.Role.SUPERADMIN:
            if user.bank_sampah_id is not None:
                raise CommandError(f"Production demo account conflict for {email}: bank assignment")
        elif role == User.Role.NASABAH:
            if user.bank_sampah_id is not None or user.is_primary_pengelola:
                raise CommandError(f"Production demo account conflict for {email}: bank assignment")
        elif user.bank_sampah_id not in (None, DEMO_BANK_ID):
            raise CommandError(f"Production demo account conflict for {email}: another bank")
        return user

    @staticmethod
    def _existing_membership(user: User | None) -> Nasabah | None:
        query = Q(email__iexact=DEMO_NASABAH_EMAIL)
        if user is not None:
            query |= Q(user=user)
        matches = list(Nasabah.objects.select_for_update().filter(query).order_by("pk")[:2])
        if len(matches) > 1:
            raise CommandError("Production demo nasabah email matches multiple memberships")
        membership = matches[0] if matches else None
        if membership is not None and membership.bank_sampah_id != DEMO_BANK_ID:
            raise CommandError("Production demo nasabah email is already used by another bank")
        if (
            membership is not None
            and user is not None
            and membership.user_id not in (None, user.pk)
        ):
            raise CommandError("Production demo nasabah membership belongs to another account")
        if membership is not None and user is None and membership.user_id is not None:
            raise CommandError("Production demo nasabah membership belongs to another account")
        if membership is not None and membership.email.lower() != DEMO_NASABAH_EMAIL:
            raise CommandError("Production demo nasabah account has a conflicting membership email")
        if membership is not None and membership.nomor != DEMO_NASABAH_NUMBER:
            raise CommandError("Production demo nasabah account has a conflicting member number")
        if membership is not None and (
            not membership.is_active or membership.status != Nasabah.Status.APPROVED
        ):
            raise CommandError("Production demo nasabah membership is inactive or unapproved")
        if (
            user is not None
            and Nasabah.objects.select_for_update()
            .filter(user=user)
            .exclude(bank_sampah_id=DEMO_BANK_ID)
            .exists()
        ):
            raise CommandError("Production demo nasabah account already belongs to another bank")
        if (
            membership is None
            and Nasabah.objects.select_for_update().filter(pk=DEMO_NASABAH_ID).exists()
        ):
            raise CommandError("Production demo nasabah identity conflicts with existing data")
        number_matches = Nasabah.objects.select_for_update().filter(
            bank_sampah_id=DEMO_BANK_ID,
            nomor=DEMO_NASABAH_NUMBER,
        )
        if membership is not None:
            number_matches = number_matches.exclude(pk=membership.pk)
        if number_matches.exists():
            raise CommandError("Production demo nasabah number is already used")
        return membership

    @staticmethod
    def _create_bank() -> BankSampah:
        return BankSampah.objects.create(
            id=DEMO_BANK_ID,
            nama=DEMO_BANK_NAME,
            alamat="Alamat data demo PILAH",
            kota="Depok",
            no_hp_pic="",
            jenis_organisasi=BankSampah.OrganizationType.MANDIRI,
            status=BankSampah.Status.ACTIVE,
            is_active=True,
        )

    @staticmethod
    def _ensure_user(
        user: User | None,
        *,
        email: str,
        display_name: str,
        role: str,
        bank: BankSampah,
        primary: bool,
    ) -> User:
        if user is None:
            return User.objects.create_user(
                email=email,
                nama=display_name,
                role=role,
                is_profile_complete=True,
                bank_sampah=bank if role == User.Role.PENGELOLA else None,
                is_primary_pengelola=primary,
                **(
                    {"alamat": "Alamat demo untuk akun nasabah PILAH"}
                    if role == User.Role.NASABAH
                    else {}
                ),
            )

        target_bank = bank if role == User.Role.PENGELOLA else None
        fields = []
        if user.bank_sampah_id != (target_bank.pk if target_bank else None):
            user.bank_sampah = target_bank
            fields.append("bank_sampah")
        if user.is_primary_pengelola != primary:
            user.is_primary_pengelola = primary
            fields.append("is_primary_pengelola")
        if not user.is_profile_complete:
            user.is_profile_complete = True
            fields.append("is_profile_complete")
        if not user.nama:
            user.nama = display_name
            fields.append("nama")
        if role == User.Role.NASABAH and not user.alamat:
            user.alamat = "Alamat demo untuk akun nasabah PILAH"
            fields.append("alamat")
        if fields:
            user.save(update_fields=[*fields, "updated_at"])
        return user

    @staticmethod
    def _create_membership(bank: BankSampah, user: User) -> Nasabah:
        membership = Nasabah.objects.create(
            id=DEMO_NASABAH_ID,
            user=user,
            bank_sampah=bank,
            nomor=DEMO_NASABAH_NUMBER,
            nama=user.nama or "Demo Nasabah PILAH",
            jenis_kelamin=user.jenis_kelamin,
            tanggal_lahir=user.tanggal_lahir,
            alamat=user.alamat or "Alamat demo untuk akun nasabah PILAH",
            no_hp=user.no_hp,
            email=DEMO_NASABAH_EMAIL,
            is_active=True,
            status=Nasabah.Status.APPROVED,
        )
        return membership
