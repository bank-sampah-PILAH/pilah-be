"""Public port of the notify context.

Other contexts (ledger today, anything tomorrow) send notifications through
here — never by importing WhatsAppService directly. When delivery needs a
queue, only this function changes.
"""

import logging
from typing import Any

from api.models import Transaksi, User
from apps.notification.models import PushNotification
from apps.notification.services import (  # noqa: F401  # re-exported: notify owns the template default
    DEFAULT_WA_TEMPLATE,
    WhatsAppService,
)

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_WA_TEMPLATE", "send_setoran_receipt"]


def send_setoran_receipt(transaksi: Transaksi) -> dict[str, Any]:
    return WhatsAppService.notify(transaksi)


def queue_push(user: User, *, title: str, body: str) -> PushNotification | None:
    from django.db import DatabaseError, transaction

    from apps.notification.models import DeviceToken, PushDelivery, PushNotification

    try:
        with transaction.atomic():
            notification = PushNotification.objects.create(user=user, title=title, body=body)
            PushDelivery.objects.bulk_create(
                [
                    PushDelivery(notification=notification, device=device)
                    for device in DeviceToken.objects.filter(user=user)
                ]
            )
        return notification
    except DatabaseError:
        logger.error("Could not persist push notification")
        return None
