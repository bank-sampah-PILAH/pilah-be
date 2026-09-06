from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from api.models import BankSampah, Nasabah, Transaksi, User

CONFIRMATION = "RESET-PILAH-TEST-DATA"


class Command(BaseCommand):
    help = "Clear application data while preserving the database schema and migrations."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", required=True)

    def handle(self, *args, **options):
        if options["confirm"] != CONFIRMATION:
            raise CommandError(f"Pass --confirm={CONFIRMATION} to run this destructive command.")

        call_command("flush", interactive=False, verbosity=0)

        remaining = {
            "users": User.objects.count(),
            "bank_sampah": BankSampah.objects.count(),
            "nasabah": Nasabah.objects.count(),
            "transaksi": Transaksi.objects.count(),
        }
        if any(remaining.values()):
            raise CommandError(f"Application data reset verification failed: {remaining}")

        self.stdout.write(self.style.SUCCESS("Application data reset verified"))
