from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from api.models import User


class CreateSuperadminCommandTests(TestCase):
    def test_creates_a_superadmin_who_can_sign_in_with_the_password(self) -> None:
        out = StringIO()

        call_command(
            "createsuperadmin",
            email="root@example.test",
            password="s3cret-pass",
            nama="Root",
            stdout=out,
        )

        user = User.objects.get(email="root@example.test")
        self.assertEqual(user.role, User.Role.SUPERADMIN)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_profile_complete)
        self.assertTrue(user.check_password("s3cret-pass"))
        self.assertIn("Created SuperAdmin root@example.test", out.getvalue())

    def test_rerunning_promotes_existing_account_and_resets_password(self) -> None:
        User.objects.create_user(
            email="root@example.test", nama="Old", role=User.Role.NASABAH, password="old-password"
        )
        out = StringIO()

        call_command(
            "createsuperadmin", email="root@example.test", password="new-password", stdout=out
        )

        user = User.objects.get(email="root@example.test")
        self.assertEqual(User.objects.filter(email="root@example.test").count(), 1)
        self.assertEqual(user.role, User.Role.SUPERADMIN)
        self.assertEqual(user.nama, "SuperAdmin PILAH")
        self.assertTrue(user.check_password("new-password"))
        self.assertIn("Updated SuperAdmin root@example.test", out.getvalue())

    def test_short_password_is_rejected_without_creating_account(self) -> None:
        with self.assertRaisesRegex(CommandError, "minimal 8"):
            call_command("createsuperadmin", email="root@example.test", password="short")

        self.assertFalse(User.objects.filter(email="root@example.test").exists())
