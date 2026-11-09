"""Public port of the notify context.

Other contexts (ledger today, anything tomorrow) send notifications through
here — never by importing WhatsAppService directly. When delivery needs a
queue, only this function changes.
"""

import logging
from collections.abc import Iterable
from typing import Any

from api.models import Transaksi, User
from apps.notification.models import PushNotification
from apps.notification.services import (  # noqa: F401  # re-exported: notify owns the template default
    DEFAULT_WA_TEMPLATE,
    WhatsAppService,
)

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_WA_TEMPLATE", "queue_push", "queue_push_bulk", "send_setoran_receipt"]


def send_setoran_receipt(transaksi: Transaksi) -> dict[str, Any]:
    return WhatsAppService.notify(transaksi)


def queue_push(user: User, *, title: str, body: str) -> PushNotification | None:
    notifications = queue_push_bulk([user], title=title, body=body)
    return notifications[0] if notifications else None


def queue_push_bulk(
    users: Iterable[User], *, title: str, body: str
) -> list[PushNotification] | None:
    from django.db import DatabaseError, transaction

    from apps.notification.models import DeviceToken, PushDelivery

    recipients = list(users)
    if not recipients:
        return []

    try:
        with transaction.atomic():
            notifications = PushNotification.objects.bulk_create(
                [PushNotification(user=user, title=title, body=body) for user in recipients]
            )
            by_user = {notification.user_id: notification for notification in notifications}
            PushDelivery.objects.bulk_create(
                [
                    PushDelivery(notification=by_user[device.user_id], device=device)
                    for device in DeviceToken.objects.filter(user__in=recipients)
                ]
            )
        return notifications
    except DatabaseError:
        logger.error("Could not persist push notification")
        return None
