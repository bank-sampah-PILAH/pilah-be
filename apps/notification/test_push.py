from django.test import TestCase
from django.utils import timezone

from api.models import User
from apps.notification.api import queue_push, queue_push_bulk
from apps.notification.models import PushNotification


class PushTests(TestCase):
    def test_bulk_enqueue_persists_history_and_all_registered_device_deliveries(self) -> None:
        from apps.notification.models import DeviceToken, PushDelivery

        first = User.objects.create_user(email="bulk-one@example.test", nama="One")
        second = User.objects.create_user(email="bulk-two@example.test", nama="Two")
        first_device = DeviceToken.objects.create(user=first, token="bulk-one", platform="android")
        second_device = DeviceToken.objects.create(user=second, token="bulk-two", platform="web")

        notifications = queue_push_bulk([first, second], title="Jadwal", body="Mulai 2 jam lagi.")

        assert notifications is not None
        self.assertEqual({item.user_id for item in notifications}, {first.pk, second.pk})
        self.assertEqual(
            set(PushDelivery.objects.values_list("device_id", flat=True)),
            {first_device.pk, second_device.pk},
        )

    def test_bulk_enqueue_without_recipients_is_empty(self) -> None:
        self.assertEqual(queue_push_bulk([], title="Jadwal", body="Mulai 2 jam lagi."), [])

    def test_notification_is_persisted_without_a_device(self) -> None:
        user = User.objects.create_user(email="push@example.test", nama="Push")
        queue_push(user, title="Jadwal baru", body="Lihat jadwal terbaru.")
        self.assertTrue(PushNotification.objects.filter(user=user, title="Jadwal baru").exists())

    def test_users_only_see_and_mark_their_own_notifications(self) -> None:
        from rest_framework.test import APIClient

        first = User.objects.create_user(email="first-push@example.test", nama="First")
        second = User.objects.create_user(email="second-push@example.test", nama="Second")
        own = queue_push(first, title="Jadwal baru", body="Lihat jadwal terbaru.")
        other = queue_push(second, title="Lain", body="Pesan lain.")
        assert own is not None
        assert other is not None
        client = APIClient()
        client.force_authenticate(first)
        response = client.get("/api/v1/notifications/")
        self.assertEqual([item["id"] for item in response.data["results"]], [own.pk])
        self.assertEqual(client.post(f"/api/v1/notifications/{other.pk}/read/").status_code, 404)
        self.assertEqual(client.post(f"/api/v1/notifications/{own.pk}/read/").status_code, 204)
        own.refresh_from_db()
        self.assertIsNotNone(own.read_at)

    def test_notification_list_is_paginated_in_stable_order(self) -> None:
        from rest_framework.test import APIClient

        user = User.objects.create_user(email="page-push@example.test", nama="Page")
        notifications = [
            PushNotification.objects.create(user=user, title=str(index), body="Body")
            for index in range(23)
        ]
        PushNotification.objects.filter(pk__in=[item.pk for item in notifications]).update(
            created_at=timezone.now()
        )
        expected_ids = [item.pk for item in reversed(notifications)]
        client = APIClient()
        client.force_authenticate(user)

        first = client.get("/api/v1/notifications/?page=1&page_size=20")
        second = client.get("/api/v1/notifications/?page=2&page_size=20")

        self.assertEqual(first.data["count"], 23)
        self.assertEqual([row["id"] for row in first.data["results"]], expected_ids[:20])
        self.assertIsNone(first.data["previous"])
        self.assertIsNotNone(first.data["next"])
        self.assertEqual([row["id"] for row in second.data["results"]], expected_ids[20:])
        self.assertIsNotNone(second.data["previous"])
        self.assertIsNone(second.data["next"])

    def test_notification_list_caps_requested_page_size_at_100(self) -> None:
        from rest_framework.test import APIClient

        user = User.objects.create_user(email="large-page@example.test", nama="Page")
        PushNotification.objects.bulk_create(
            [PushNotification(user=user, title="Title", body="Body") for _ in range(101)]
        )
        client = APIClient()
        client.force_authenticate(user)

        response = client.get("/api/v1/notifications/?page_size=1000")

        self.assertEqual(response.data["count"], 101)
        self.assertEqual(len(response.data["results"]), 100)

    def test_notification_list_excludes_hidden_rows(self) -> None:
        from rest_framework.test import APIClient

        user = User.objects.create_user(email="hidden-push@example.test", nama="Hidden")
        visible = PushNotification.objects.create(user=user, title="Visible", body="Body")
        hidden = PushNotification.objects.create(user=user, title="Hidden", body="Body")
        hidden.hidden_at = timezone.now()
        hidden.save(update_fields=["hidden_at"])
        client = APIClient()
        client.force_authenticate(user)

        response = client.get("/api/v1/notifications/")

        self.assertEqual(response.data["count"], 1)
        self.assertEqual([row["id"] for row in response.data["results"]], [visible.pk])

    def test_clear_hides_notifications_beyond_first_page(self) -> None:
        from rest_framework.test import APIClient

        user = User.objects.create_user(email="clear-push@example.test", nama="Clear")
        PushNotification.objects.bulk_create(
            [PushNotification(user=user, title=str(index), body="Body") for index in range(27)]
        )
        client = APIClient()
        client.force_authenticate(user)
        self.assertEqual(client.get("/api/v1/notifications/").data["count"], 27)

        cleared = client.post("/api/v1/notifications/clear/")

        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.data, {"hidden_count": 27})
        self.assertEqual(client.get("/api/v1/notifications/?page_size=100").data["count"], 0)
        self.assertEqual(PushNotification.objects.filter(user=user).count(), 27)
        self.assertEqual(
            PushNotification.objects.filter(user=user, hidden_at__isnull=False).count(), 27
        )

    def test_clear_is_user_scoped_and_preserves_rows_read_state_and_deliveries(self) -> None:
        from rest_framework.test import APIClient

        from apps.notification.models import DeviceToken, PushDelivery

        user = User.objects.create_user(email="clear-owner@example.test", nama="Owner")
        other = User.objects.create_user(email="clear-other@example.test", nama="Other")
        read_at = timezone.now()
        read = PushNotification.objects.create(
            user=user, title="Read", body="Body", read_at=read_at
        )
        unread = PushNotification.objects.create(user=user, title="Unread", body="Body")
        other_notification = PushNotification.objects.create(user=other, title="Other", body="Body")
        devices = [
            DeviceToken.objects.create(user=user, token="clear-read", platform="android"),
            DeviceToken.objects.create(user=user, token="clear-unread", platform="ios"),
            DeviceToken.objects.create(user=other, token="clear-other", platform="web"),
        ]
        for notification, device, status in zip(
            (read, unread, other_notification), devices, ("sent", "pending", "pending"), strict=True
        ):
            PushDelivery.objects.create(notification=notification, device=device, status=status)
        deliveries_before = list(
            PushDelivery.objects.order_by("pk").values(
                "id",
                "notification_id",
                "device_id",
                "status",
                "attempts",
                "next_attempt_at",
                "last_error",
            )
        )
        client = APIClient()
        self.assertEqual(client.post("/api/v1/notifications/clear/").status_code, 401)
        client.force_authenticate(user)

        cleared = client.post("/api/v1/notifications/clear/")

        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.data, {"hidden_count": 2})
        read.refresh_from_db()
        unread.refresh_from_db()
        other_notification.refresh_from_db()
        self.assertEqual(read.read_at, read_at)
        self.assertIsNone(unread.read_at)
        self.assertIsNotNone(read.hidden_at)
        self.assertIsNotNone(unread.hidden_at)
        self.assertIsNone(other_notification.hidden_at)
        self.assertEqual(PushNotification.objects.count(), 3)
        self.assertEqual(
            list(
                PushDelivery.objects.order_by("pk").values(
                    "id",
                    "notification_id",
                    "device_id",
                    "status",
                    "attempts",
                    "next_attempt_at",
                    "last_error",
                )
            ),
            deliveries_before,
        )
        self.assertEqual(client.post("/api/v1/notifications/clear/").data, {"hidden_count": 0})
        client.force_authenticate(other)
        self.assertEqual(client.get("/api/v1/notifications/").data["count"], 1)

    def test_enqueue_creates_delivery_for_registered_devices(self) -> None:
        from apps.notification.models import DeviceToken, PushDelivery

        user = User.objects.create_user(email="delivery@example.test", nama="Delivery")
        token = DeviceToken.objects.create(user=user, token="device", platform="android")
        notification = queue_push(user, title="Jadwal baru", body="Lihat jadwal terbaru.")
        delivery = PushDelivery.objects.get(notification=notification)
        self.assertEqual(delivery.device_id, token.pk)

    def test_send_fcm_uses_firebase_project_and_requires_project_id(self) -> None:
        from unittest.mock import Mock, patch

        from apps.notification.models import DeviceToken, PushDelivery
        from apps.notification.push import send_fcm

        user = User.objects.create_user(email="fcm@example.test", nama="FCM")
        device = DeviceToken.objects.create(user=user, token="fcm-token", platform="android")
        notification = queue_push(user, title="Jadwal", body="Lihat jadwal.")
        delivery = PushDelivery.objects.get(notification=notification, device=device)
        credentials = object()
        session = Mock()
        response = Mock()
        session.post.return_value = response

        with (
            patch(
                "apps.notification.push.google.auth.default",
                side_effect=[(credentials, "default-project"), (credentials, None)],
            ) as auth_default,
            patch(
                "apps.notification.push.AuthorizedSession", return_value=session
            ) as session_factory,
            patch.dict("os.environ", {"FIREBASE_PROJECT_ID": "configured-project"}),
        ):
            send_fcm(delivery)
            with patch.dict("os.environ", {"FIREBASE_PROJECT_ID": ""}):
                with self.assertRaisesRegex(RuntimeError, "Firebase project ID is unavailable"):
                    send_fcm(delivery)

        auth_default.assert_called_with(
            scopes=["https://www.googleapis.com/auth/firebase.messaging"]
        )
        self.assertEqual(auth_default.call_count, 2)
        session_factory.assert_called_once_with(credentials)
        args, kwargs = session.post.call_args
        self.assertEqual(
            args, ("https://fcm.googleapis.com/v1/projects/configured-project/messages:send",)
        )
        self.assertEqual(
            kwargs["json"],
            {
                "message": {
                    "token": "fcm-token",
                    "notification": {"title": "Jadwal", "body": "Lihat jadwal."},
                }
            },
        )
        self.assertEqual(kwargs["timeout"], 10)
        response.raise_for_status.assert_called_once_with()

    def test_delivery_sends_once_and_records_success(self) -> None:
        from unittest.mock import patch

        from django.core.management import call_command

        from apps.notification.models import DeviceToken, PushDelivery

        user = User.objects.create_user(email="send@example.test", nama="Send")
        DeviceToken.objects.create(user=user, token="device", platform="android")
        notification = queue_push(user, title="Jadwal baru", body="Lihat jadwal terbaru.")
        with (
            patch("apps.notification.push.send_fcm") as send,
            patch("apps.notification.push._fcm_client", return_value=(object(), "project")),
        ):
            call_command("deliver_push")
            call_command("deliver_push")
        self.assertEqual(send.call_count, 1)
        self.assertEqual(PushDelivery.objects.get(notification=notification).status, "sent")

    def test_delivery_reuses_fcm_client_within_command_run(self) -> None:
        from unittest.mock import patch

        from django.core.management import call_command

        from apps.notification.models import DeviceToken

        for number in range(2):
            user = User.objects.create_user(email=f"batch-{number}@example.test", nama="Batch")
            DeviceToken.objects.create(user=user, token=f"batch-{number}", platform="android")
            queue_push(user, title="Jadwal", body="Lihat jadwal.")
        client = (object(), "project")
        with (
            patch("apps.notification.push.send_fcm") as send,
            patch("apps.notification.push._fcm_client", return_value=client) as create_client,
        ):
            call_command("deliver_push")
        create_client.assert_called_once_with()
        self.assertEqual(send.call_count, 2)
        self.assertTrue(all(call.args[1] == client for call in send.call_args_list))

    def test_unregistered_device_is_removed(self) -> None:
        from unittest.mock import Mock, patch

        import requests
        from django.core.management import call_command

        from apps.notification.models import DeviceToken

        user = User.objects.create_user(email="invalid@example.test", nama="Invalid")
        DeviceToken.objects.create(user=user, token="invalid", platform="android")
        queue_push(user, title="Jadwal", body="Lihat jadwal.")
        response = Mock(status_code=404)
        response.json.return_value = {
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError",
                        "errorCode": "UNREGISTERED",
                    }
                ]
            }
        }
        with (
            patch(
                "apps.notification.push.send_fcm", side_effect=requests.HTTPError(response=response)
            ),
            patch("apps.notification.push._fcm_client", return_value=(object(), "project")),
        ):
            call_command("deliver_push")
        self.assertFalse(DeviceToken.objects.filter(token="invalid").exists())

    def test_invalid_argument_token_is_removed_but_bad_request_keeps_token(self) -> None:
        from unittest.mock import Mock, patch

        import requests
        from django.core.management import call_command

        from apps.notification.models import DeviceToken, PushDelivery

        user = User.objects.create_user(email="invalid-argument@example.test", nama="Invalid")
        token = DeviceToken.objects.create(user=user, token="invalid-argument", platform="android")
        notification = queue_push(user, title="Jadwal", body="Lihat jadwal.")
        response = Mock(status_code=400)
        response.json.return_value = {
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError",
                        "errorCode": "INVALID_ARGUMENT",
                    }
                ]
            }
        }
        with (
            patch(
                "apps.notification.push.send_fcm",
                side_effect=requests.HTTPError(response=response),
            ),
            patch("apps.notification.push._fcm_client", return_value=(object(), "project")),
        ):
            call_command("deliver_push")
        self.assertFalse(DeviceToken.objects.filter(pk=token.pk).exists())
        self.assertEqual(PushDelivery.objects.get(notification=notification).status, "invalid")

        user = User.objects.create_user(email="bad-request@example.test", nama="Bad Request")
        token = DeviceToken.objects.create(user=user, token="bad-request", platform="android")
        notification = queue_push(user, title="Jadwal", body="Lihat jadwal.")
        response.json.return_value = {
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.BadRequest",
                        "fieldViolations": [{"field": "message.notification.body"}],
                    }
                ]
            }
        }
        with (
            patch(
                "apps.notification.push.send_fcm",
                side_effect=requests.HTTPError(response=response),
            ),
            patch("apps.notification.push._fcm_client", return_value=(object(), "project")),
        ):
            call_command("deliver_push")
        self.assertTrue(DeviceToken.objects.filter(pk=token.pk).exists())
        self.assertEqual(PushDelivery.objects.get(notification=notification).status, "pending")

    def test_non_json_fcm_error_is_retried(self) -> None:
        from unittest.mock import Mock, patch

        import requests
        from django.core.management import call_command

        from apps.notification.models import DeviceToken, PushDelivery

        user = User.objects.create_user(email="invalid-json@example.test", nama="Invalid JSON")
        device = DeviceToken.objects.create(user=user, token="invalid-json", platform="android")
        notification = queue_push(user, title="Jadwal", body="Lihat jadwal.")
        response = Mock()
        response.json.side_effect = ValueError
        with (
            patch(
                "apps.notification.push.send_fcm", side_effect=requests.HTTPError(response=response)
            ),
            patch("apps.notification.push._fcm_client", return_value=(object(), "project")),
        ):
            call_command("deliver_push")

        delivery = PushDelivery.objects.get(notification=notification, device=device)
        self.assertEqual(delivery.status, "pending")
        self.assertEqual(delivery.last_error, "HTTPError")
        self.assertTrue(DeviceToken.objects.filter(pk=device.pk).exists())

    def test_temporary_failure_waits_before_retry(self) -> None:
        from unittest.mock import patch

        from django.core.management import call_command

        from apps.notification.models import DeviceToken, PushDelivery

        user = User.objects.create_user(email="retry@example.test", nama="Retry")
        DeviceToken.objects.create(user=user, token="retry", platform="android")
        notification = queue_push(user, title="Jadwal", body="Lihat jadwal.")
        with (
            patch("apps.notification.push.send_fcm", side_effect=TimeoutError) as send,
            patch("apps.notification.push._fcm_client", return_value=(object(), "project")),
        ):
            call_command("deliver_push")
            call_command("deliver_push")
        delivery = PushDelivery.objects.get(notification=notification)
        self.assertEqual(delivery.status, "pending")
        self.assertEqual(delivery.attempts, 1)
        self.assertIsNotNone(delivery.next_attempt_at)
        self.assertEqual(send.call_count, 1)

    def test_reassigned_device_does_not_receive_previous_users_notification(self) -> None:
        from unittest.mock import patch

        from django.core.management import call_command

        from apps.notification.models import DeviceToken

        first = User.objects.create_user(email="old@example.test", nama="Old")
        second = User.objects.create_user(email="new@example.test", nama="New")
        token = DeviceToken.objects.create(user=first, token="shared", platform="android")
        queue_push(first, title="Jadwal", body="Lihat jadwal.")
        token.user = second
        token.save(update_fields=["user"])
        with (
            patch("apps.notification.push.send_fcm") as send,
            patch("apps.notification.push._fcm_client", return_value=(object(), "project")),
        ):
            call_command("deliver_push")
        send.assert_not_called()

    def test_notification_storage_failure_does_not_abort_business_transaction(self) -> None:
        from unittest.mock import patch

        from django.db import DatabaseError, transaction

        user = User.objects.create_user(email="nonblocking@example.test", nama="Before")
        with transaction.atomic():
            user.nama = "After"
            user.save(update_fields=["nama"])
            with patch(
                "apps.notification.models.PushNotification.objects.bulk_create",
                side_effect=DatabaseError("unavailable"),
            ):
                queue_push(user, title="Jadwal", body="Lihat jadwal.")
        user.refresh_from_db()
        self.assertEqual(user.nama, "After")
