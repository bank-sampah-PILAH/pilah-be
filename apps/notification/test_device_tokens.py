from rest_framework.test import APITestCase

from api.models import User
from apps.notification.models import DeviceToken


class DeviceTokenTests(APITestCase):
    def test_register_and_remove_token(self) -> None:
        user = User.objects.create_user(email="device@example.test", nama="Device")
        self.client.force_authenticate(user)
        url = "/api/v1/device-tokens/"
        self.assertEqual(
            self.client.post(
                url, {"token": "abc", "platform": "android"}, format="json"
            ).status_code,
            200,
        )
        self.assertTrue(DeviceToken.objects.filter(user=user, token="abc").exists())
        self.assertEqual(self.client.delete(url, {"token": "abc"}, format="json").status_code, 204)
        self.assertFalse(DeviceToken.objects.filter(token="abc").exists())

    def test_token_is_reassigned_and_cannot_be_removed_by_previous_user(self) -> None:
        first = User.objects.create_user(email="first@example.test", nama="First")
        second = User.objects.create_user(email="second@example.test", nama="Second")
        url = "/api/v1/device-tokens/"
        self.client.force_authenticate(first)
        self.client.post(url, {"token": "abc", "platform": "android"}, format="json")
        self.client.force_authenticate(second)
        self.client.post(url, {"token": "abc", "platform": "android"}, format="json")
        self.client.force_authenticate(first)
        self.client.delete(url, {"token": "abc"}, format="json")
        self.assertTrue(DeviceToken.objects.filter(user=second, token="abc").exists())
