from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction

from api.models import User
from shared_kernel.permissions import superadmin_allowlist


class Command(BaseCommand):
    help = "Create missing allowlisted Superadmins without changing existing accounts."

    @staticmethod
    def _validate_single_superadmin(matches: list[User]) -> None:
        if len(matches) > 1:
            raise CommandError("Allowlisted email matches multiple accounts")
        if matches[0].role != User.Role.SUPERADMIN:
            raise CommandError("Allowlisted email belongs to a non-Superadmin account")

    def handle(self, *args: object, **options: object) -> None:
        emails = sorted(superadmin_allowlist())
        if not emails:
            raise CommandError("PILAH_SUPERADMIN_EMAILS must not be empty")
        for email in emails:
            try:
                validate_email(email)
            except ValidationError as exc:
                raise CommandError("PILAH_SUPERADMIN_EMAILS contains an invalid email") from exc

        with transaction.atomic():
            for email in emails:
                existing = list(User.objects.select_for_update().filter(email__iexact=email))
                if existing:
                    self._validate_single_superadmin(existing)
                    continue
                try:
                    with transaction.atomic():
                        User.objects.create_user(
                            email=email,
                            nama="SuperAdmin PILAH",
                            role=User.Role.SUPERADMIN,
                            is_profile_complete=True,
                        )
                except IntegrityError:
                    raced = list(User.objects.select_for_update().filter(email__iexact=email))
                    if not raced:
                        raise
                    self._validate_single_superadmin(raced)
        self.stdout.write(self.style.SUCCESS("Superadmin bootstrap complete"))
