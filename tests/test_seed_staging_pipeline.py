import os
import shlex
from subprocess import CalledProcessError
from unittest.mock import patch

from django.test import SimpleTestCase

from scripts.seed_staging import seed_staging

SEED_ENV = {
    "FLY_API_TOKEN": "placeholder",
    "PILAH_SEED_PENGURUS_EMAIL": "pengurus@example.com",
    "PILAH_SEED_CUSTOMER_EMAIL": "one@example.com",
    "PILAH_SEED_CUSTOMER_TWO_EMAIL": "two@example.com",
    "PILAH_SEED_SUPERADMIN_EMAIL": "admin@example.com",
    "PILAH_SEED_PENDING_PENGURUS_EMAIL": "pending@example.com",
}


class SeedStagingPipelineTests(SimpleTestCase):
    def test_seed_passes_validated_emails_as_data_without_shell_execution(self) -> None:
        with patch.dict(os.environ, SEED_ENV, clear=True), patch("subprocess.run") as run:
            seed_staging()
            self.assertEqual(run.call_count, 2)
            commands = []
            for invocation in run.call_args_list:
                argv = invocation.args[0]
                self.assertEqual(
                    argv[:5], ["flyctl", "ssh", "console", "--app", "pilah-be-staging"]
                )
                self.assertNotIn("shell", invocation.kwargs)
                self.assertTrue(invocation.kwargs["check"])
                commands.append(shlex.split(argv[argv.index("--command") + 1]))
            command = commands[0]
            self.assertEqual(command[:3], ["python", "/app/manage.py", "seed_testing_data"])
            self.assertIn("--environment=staging", command)
            self.assertIn("--confirm=SEED-PILAH-STAGING-DATA", command)
            self.assertIn("--if-missing", command)
            self.assertIn("--pengurus-email=pengurus@example.com", command)
            self.assertIn("--induk-email=induk.demo@example.com", command)
            self.assertEqual(
                commands[1],
                [
                    "python",
                    "/app/manage.py",
                    "seed_staging_review_account",
                    "--confirm=SEED-PILAH-STAGING-REVIEW-ACCOUNT",
                ],
            )

            for invalid in ("", "x@example.com' ; touch /tmp/pwned #", "$(id)@example.com"):
                os.environ["PILAH_SEED_PENGURUS_EMAIL"] = invalid
                run.reset_mock()
                with self.assertRaises(ValueError):
                    seed_staging()
                run.assert_not_called()

    def test_seed_propagates_failure_and_stops_at_the_failed_remote_command(self) -> None:
        for failed_index in (0, 1):
            with self.subTest(failed_index=failed_index):
                failure = CalledProcessError(1, "flyctl")
                with (
                    patch.dict(os.environ, SEED_ENV, clear=True),
                    patch("subprocess.run", side_effect=[None] * failed_index + [failure]) as run,
                ):
                    with self.assertRaises(CalledProcessError):
                        seed_staging()
                    self.assertEqual(run.call_count, failed_index + 1)

    def test_seed_requires_fly_authentication_before_remote_execution(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch("subprocess.run") as run:
            with self.assertRaisesMessage(ValueError, "FLY_API_TOKEN is required"):
                seed_staging()
            run.assert_not_called()
