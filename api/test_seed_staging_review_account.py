from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from api.management.commands.seed_staging_review_account import CONFIRMATION
from api.models import User

REVIEWER_EMAIL = "pilah.superadmin@pilah.com"
REVIEWER_PASSWORD = "ReviewerLogin-Test-74!"


@override_settings(
    DEBUG=False,
    PILAH_ENVIRONMENT="staging",
    PILAH_SUPERADMIN_EMAILS=(),
    PILAH_REVIEW_SUPERADMIN_EMAILS=(REVIEWER_EMAIL,),
    PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS=(REVIEWER_EMAIL,),
    PILAH_REVIEW_ACCOUNT_PASSWORD=REVIEWER_PASSWORD,
)
class SeedStagingReviewAccountTests(TestCase):
    def test_seed_rejects_invalid_runtime_configuration(self) -> None:
        invalid_settings: tuple[tuple[dict[str, object], str, str], ...] = (
            ({"DEBUG": True}, CONFIRMATION, "only be seeded in staging"),
            ({}, "incorrect", "Pass --confirm="),
            (
                {"PILAH_REVIEW_SUPERADMIN_EMAILS": ()},
                CONFIRMATION,
                "PILAH_REVIEW_SUPERADMIN_EMAILS",
            ),
            (
                {"PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS": ()},
                CONFIRMATION,
                "PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS",
            ),
            (
                {"PILAH_REVIEW_ACCOUNT_PASSWORD": ""},
                CONFIRMATION,
                "PILAH_REVIEW_ACCOUNT_PASSWORD must be configured",
            ),
            (
                {"PILAH_REVIEW_ACCOUNT_PASSWORD": "short"},
                CONFIRMATION,
                "does not meet password requirements",
            ),
        )
        for overrides, confirmation, message in invalid_settings:
            with self.subTest(overrides=overrides):
                with self.settings(**overrides):
                    with self.assertRaisesMessage(CommandError, message):
                        call_command("seed_staging_review_account", confirm=confirmation)

    def test_seeded_reviewer_can_log_in_with_password(self) -> None:
        call_command("seed_staging_review_account", confirm=CONFIRMATION)
        call_command("seed_staging_review_account", confirm=CONFIRMATION)

        user = User.objects.get(email=REVIEWER_EMAIL)
        self.assertEqual(User.objects.filter(email__iexact=REVIEWER_EMAIL).count(), 1)
        self.assertEqual(user.role, User.Role.SUPERADMIN)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        response = APIClient().post(
            "/api/v1/auth/login",
            {"email": REVIEWER_EMAIL, "password": REVIEWER_PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["email"], REVIEWER_EMAIL)

    def test_seed_repairs_safe_existing_reviewer_but_rejects_other_roles(self) -> None:
        reviewer = User.objects.create_user(
            email=REVIEWER_EMAIL.upper(),
            nama="",
            role=User.Role.SUPERADMIN,
            is_profile_complete=False,
            password="old-password",
        )
        call_command("seed_staging_review_account", confirm=CONFIRMATION)
        reviewer.refresh_from_db()
        self.assertEqual(reviewer.email, REVIEWER_EMAIL)
        self.assertEqual(reviewer.nama, "SuperAdmin PILAH")
        self.assertTrue(reviewer.is_profile_complete)
        self.assertTrue(reviewer.check_password(REVIEWER_PASSWORD))

        reviewer.role = User.Role.PENGELOLA
        reviewer.save(update_fields=["role"])
        with self.assertRaisesMessage(CommandError, "identity conflicts"):
            call_command("seed_staging_review_account", confirm=CONFIRMATION)
        reviewer.refresh_from_db()
        self.assertEqual(reviewer.role, User.Role.PENGELOLA)

    def test_seed_rejects_duplicate_case_insensitive_identities(self) -> None:
        for email in (REVIEWER_EMAIL, REVIEWER_EMAIL.upper()):
            User.objects.create_user(
                email=email,
                nama="Reviewer",
                role=User.Role.SUPERADMIN,
                password=REVIEWER_PASSWORD,
            )
        with self.assertRaisesMessage(CommandError, "identity conflicts"):
            call_command("seed_staging_review_account", confirm=CONFIRMATION)
