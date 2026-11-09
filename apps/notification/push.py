import logging
import os
from datetime import timedelta

import google.auth
import requests
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from google.auth.transport.requests import AuthorizedSession

from apps.notification.models import DeviceToken, PushDelivery

logger = logging.getLogger(__name__)


def _handle_failure(delivery: PushDelivery, exc: Exception) -> None:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        try:
            details = exc.response.json().get("error", {}).get("details", [])
        except ValueError:
            details = []
        if any(item.get("errorCode") == "UNREGISTERED" for item in details):
            assert delivery.device is not None
            delivery.device.delete()
            delivery.device = None
            delivery.status = "invalid"
            delivery.last_error = "UNREGISTERED"
            delivery.save(update_fields=["attempts", "status", "last_error"])
            return
    logger.warning("Push delivery %s failed: %s", delivery.pk, type(exc).__name__)
    delivery.last_error = type(exc).__name__
    delivery.status = "failed" if delivery.attempts >= 5 else "pending"
    delivery.next_attempt_at = timezone.now() + timedelta(minutes=2**delivery.attempts)
    delivery.save(update_fields=["attempts", "status", "last_error", "next_attempt_at"])


def send_fcm(delivery: PushDelivery) -> None:
    assert delivery.device is not None
    credentials, project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/firebase.messaging"]
    )
    project = os.getenv("FIREBASE_PROJECT_ID") or project
    if not project:
        raise RuntimeError("Firebase project ID is unavailable")
    response = AuthorizedSession(credentials).post(  # type: ignore[no-untyped-call]
        f"https://fcm.googleapis.com/v1/projects/{project}/messages:send",
        json={
            "message": {
                "token": delivery.device.token,
                "notification": {
                    "title": delivery.notification.title,
                    "body": delivery.notification.body,
                },
            }
        },
        timeout=10,
    )
    response.raise_for_status()


def deliver_pending() -> None:
    while True:
        with transaction.atomic():
            delivery = (
                PushDelivery.objects.select_for_update(skip_locked=True, of=("self",))
                .select_related("device", "notification")
                .filter(status="pending")
                .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=timezone.now()))
                .order_by("pk")
                .first()
            )
            if delivery is None:
                return
            device = (
                DeviceToken.objects.select_for_update().filter(pk=delivery.device_id).first()
                if delivery.device_id is not None
                else None
            )
            if device is None or device.user_id != delivery.notification.user_id:
                delivery.delete()
                continue
            delivery.device = device
            delivery.attempts += 1
            try:
                send_fcm(delivery)
            except Exception as exc:
                _handle_failure(delivery, exc)
                continue
            else:
                delivery.status = "sent"
                delivery.last_error = ""
            delivery.save(update_fields=["attempts", "status", "last_error", "next_attempt_at"])
