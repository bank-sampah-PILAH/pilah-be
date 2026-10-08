from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from api.models import BankSampah, JenisSampah, Nasabah, Transaksi, User


@override_settings(PILAH_SUPERADMIN_EMAILS=("root@example.com", "second@example.com"))
class BootstrapSuperadminsTests(TestCase):
    def test_repeated_bootstrap_creates_only_allowlisted_superadmins(self) -> None:
        for _ in range(2):
            call_command("bootstrap_superadmins", stdout=StringIO())
        self.assertEqual(
            set(User.objects.values_list("email", "role")),
            {("root@example.com", "superadmin"), ("second@example.com", "superadmin")},
        )
        for user in User.objects.all():
            self.assertFalse(user.has_usable_password())
            self.assertTrue(user.is_profile_complete)
        for model in (BankSampah, Nasabah, JenisSampah, Transaksi):
            self.assertEqual(model.objects.count(), 0)

    def test_existing_superadmin_is_unchanged(self) -> None:
        user = User.objects.create_user(
            email="Root@Example.com",
            password="existing-password",
            nama="Existing Admin",
            role=User.Role.SUPERADMIN,
            no_hp="+628123456789",
            is_active=False,
        )
        before = User.objects.filter(pk=user.pk).values().get()
        call_command("bootstrap_superadmins", stdout=StringIO())
        self.assertEqual(User.objects.filter(pk=user.pk).values().get(), before)

    def test_conflicting_roles_fail_atomically_without_privilege_escalation(self) -> None:
        for role in (User.Role.PENGELOLA, User.Role.PENGELOLA_INDUK, User.Role.NASABAH):
            with self.subTest(role=role):
                User.objects.all().delete()
                user = User.objects.create_user(email="second@example.com", role=role)
                with self.assertRaises(CommandError):
                    call_command("bootstrap_superadmins", stdout=StringIO())
                user.refresh_from_db()
                self.assertEqual(user.role, role)
                self.assertEqual(User.objects.count(), 1)

    def test_missing_or_invalid_allowlist_fails_without_writes(self) -> None:
        for allowlist in ((), ("root@example.com", "not-an-email")):
            with (
                self.subTest(allowlist=allowlist),
                override_settings(PILAH_SUPERADMIN_EMAILS=allowlist),
            ):
                with self.assertRaises(CommandError):
                    call_command("bootstrap_superadmins", stdout=StringIO())
                self.assertFalse(User.objects.exists())
