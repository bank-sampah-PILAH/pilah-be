from django.core.management.base import BaseCommand

from apps.notification.push import deliver_pending


class Command(BaseCommand):
    help = "Deliver pending Firebase notifications"

    def handle(self, *args, **options):
        deliver_pending()
