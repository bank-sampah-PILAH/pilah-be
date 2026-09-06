from argparse import ArgumentParser

from django.core.management.base import BaseCommand, CommandError

from api.models import User


class Command(BaseCommand):
    help = "Create or update a PILAH SuperAdmin account."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--email", required=True)
        parser.add_argument("--password", required=True)
        parser.add_argument("--nama", default="SuperAdmin PILAH")

    def handle(self, *args: object, **options: object) -> None:
        email = str(options["email"])
        password = str(options["password"])
        nama = str(options["nama"])
        if len(password) < 8:
            raise CommandError("Password minimal 8 karakter")
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "nama": nama,
                "role": User.Role.SUPERADMIN,
                "is_profile_complete": True,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        user.nama = nama
        user.role = User.Role.SUPERADMIN
        user.is_profile_complete = True
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()
        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} SuperAdmin {email}"))
