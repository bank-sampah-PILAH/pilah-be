import os
import shlex
from unittest.mock import patch

from django.test import SimpleTestCase

from scripts.seed_staging import seed_staging


class SeedStagingPipelineTests(SimpleTestCase):
    def test_seed_passes_validated_emails_as_data_without_shell_execution(self) -> None:
        env = {
            "FLY_API_TOKEN": "placeholder",
            "PILAH_SEED_PENGURUS_EMAIL": "pengurus@example.com",
            "PILAH_SEED_CUSTOMER_EMAIL": "one@example.com",
            "PILAH_SEED_CUSTOMER_TWO_EMAIL": "two@example.com",
            "PILAH_SEED_SUPERADMIN_EMAIL": "admin@example.com",
            "PILAH_SEED_PENDING_PENGURUS_EMAIL": "pending@example.com",
        }
        with patch.dict(os.environ, env, clear=True), patch("subprocess.run") as run:
            seed_staging()
            argv = run.call_args.args[0]
            self.assertEqual(argv[:5], ["flyctl", "ssh", "console", "--app", "pilah-be-staging"])
            command = shlex.split(argv[argv.index("--command") + 1])
            self.assertEqual(command[:3], ["python", "/app/manage.py", "seed_testing_data"])
            self.assertIn("--environment=staging", command)
            self.assertIn("--confirm=SEED-PILAH-STAGING-DATA", command)
            self.assertIn("--pengurus-email=pengurus@example.com", command)
            self.assertIn("--induk-email=induk.demo@example.com", command)
            self.assertTrue(run.call_args.kwargs["check"])

            for invalid in ("", "x@example.com' ; touch /tmp/pwned #", "$(id)@example.com"):
                os.environ["PILAH_SEED_PENGURUS_EMAIL"] = invalid
                run.reset_mock()
                with self.assertRaises(ValueError):
                    seed_staging()
                run.assert_not_called()
