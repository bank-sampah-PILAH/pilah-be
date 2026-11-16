from typing import Any

from django.core.management.base import BaseCommand

from apps.jadwal.api import queue_due_schedule_reminders
from apps.notification.push import deliver_pending


class Command(BaseCommand):
    help = "Deliver pending Firebase notifications"

    def handle(self, *args: Any, **options: Any) -> None:
        queue_due_schedule_reminders()
        deliver_pending()
