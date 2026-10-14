from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from api.models import BankSampah, User


class SeedEnvironmentTests(TestCase):
    def test_fixture_seeding_fails_closed_outside_staging_runtime(self) -> None:
        for runtime in ("", "production"):
            for debug in (False, True):
                for cli_environment in ("local", "staging"):
                    with self.subTest(runtime=runtime, debug=debug, cli=cli_environment):
                        if debug and not runtime:
                            continue
                        with override_settings(DEBUG=debug, PILAH_ENVIRONMENT=runtime):
                            with self.assertRaises(CommandError):
                                call_command(
                                    "seed_testing_data",
                                    environment=cli_environment,
                                    confirm="SEED-PILAH-STAGING-DATA",
                                    stdout=StringIO(),
                                )
                        self.assertFalse(User.objects.exists())
                        self.assertFalse(BankSampah.objects.exists())

    @override_settings(DEBUG=False, PILAH_ENVIRONMENT="staging", PILAH_SUPERADMIN_EMAILS=())
    def test_staging_seed_requires_allowlisted_superadmin(self) -> None:
        with self.assertRaises(CommandError):
            call_command(
                "seed_testing_data",
                environment="staging",
                confirm="SEED-PILAH-STAGING-DATA",
                stdout=StringIO(),
            )
        self.assertFalse(User.objects.exists())
