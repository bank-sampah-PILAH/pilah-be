import json
import stat
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from api.management.commands.load_test_data import CONFIRMATION, Command, fixture_id
from api.models import BankSampah, DetailTransaksi, Nasabah, Saldo, Transaksi, User


@override_settings(DEBUG=True, PILAH_ENVIRONMENT="local")
class LoadTestDataTests(TestCase):
    def command(self, action: str, **kwargs: object) -> dict[str, Any]:
        output = StringIO()
        call_command(
            "load_test_data",
            action,
            run_id="test-pil-393",
            confirm=CONFIRMATION,
            stdout=output,
            **kwargs,
        )
        data: dict[str, Any] = json.loads(output.getvalue())
        return data

    def test_production_and_invalid_targets_are_rejected_before_writes(self) -> None:
        for environment in ("production", "staging", "anything"):
            with (
                self.subTest(environment=environment),
                self.settings(
                    DEBUG=False,
                    PILAH_ENVIRONMENT=environment,
                ),
            ):
                with self.assertRaises(CommandError):
                    self.command("cleanup")
        with self.assertRaises(CommandError):
            self.command("seed")
        self.assertEqual(BankSampah.objects.count(), 0)

    def test_seed_refuses_credentials_manifest_inside_git_worktree(self) -> None:
        with TemporaryDirectory() as folder:
            checkout = Path(folder) / "checkout"
            checkout.mkdir()
            (checkout / ".git").mkdir()
            manifest = checkout / "accounts.json"
            with self.assertRaisesMessage(CommandError, "outside Git worktrees"):
                self.command("seed", manifest=manifest)
            self.assertFalse(manifest.exists())
            self.assertEqual(BankSampah.objects.count(), 0)

    def test_validation_rejects_invalid_run_ids_confirmation_and_seed_paths(self) -> None:
        with TemporaryDirectory() as folder:
            existing = Path(folder) / "existing.json"
            existing.touch()
            for action, options in (
                ("cleanup", {"run_id": "../invalid"}),
                ("cleanup", {"confirm": "wrong"}),
                ("seed", {"manifest": None}),
                ("seed", {"manifest": Path("relative.json")}),
                ("seed", {"manifest": existing}),
            ):
                with self.subTest(action=action, options=options), self.assertRaises(CommandError):
                    command_options: dict[str, object] = {
                        "run_id": "test-pil-393",
                        "confirm": CONFIRMATION,
                    }
                    command_options.update(options)
                    call_command(
                        "load_test_data",
                        action,
                        **command_options,
                    )
        self.assertFalse(BankSampah.objects.exists())

    def test_full_fixture_journeys_reset_audit_and_scoped_cleanup(self) -> None:
        other = BankSampah.objects.create(nama="Unrelated UAT bank", no_hp_pic="")
        with TemporaryDirectory() as folder:
            path = Path(folder) / "accounts.json"
            baseline = self.command("seed", manifest=path)
            manifest = json.loads(path.read_text())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(baseline["customers"], 1000)
            self.assertEqual(Transaksi.objects.count(), 10000)
            self.assertEqual(User.objects.count(), 30)
            self.assertEqual(Saldo.objects.filter(total_saldo=25000).count(), 1000)
            self.assertEqual(
                self.command("telemetry")["database_metrics"],
                "unavailable for non-PostgreSQL database",
            )
            with self.assertRaises(CommandError):
                self.command("seed", manifest=Path(folder) / "accounts-again.json")
            client = APIClient()
            for index, endpoints in (
                (0, ("nasabah?search=Load", "jenis-sampah", "jadwal", "aktivitas")),
                (21, ("nasabah/me/beranda", "nasabah/me/saldo", "jadwal", "nasabah/me/riwayat")),
            ):
                account = manifest["accounts"][index]
                login = client.post(
                    "/api/v1/auth/login",
                    {
                        "email": account["email"],
                        "password": account["password"],
                    },
                    format="json",
                )
                self.assertEqual(login.status_code, 200, login.data)
                client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access_token']}")
                for endpoint in endpoints:
                    response = client.get(f"/api/v1/{endpoint}")
                    self.assertEqual(response.status_code, 200, response.data)
            client.force_authenticate(User.objects.get(pk=manifest["accounts"][0]["id"]))
            search = client.get("/api/v1/nasabah?search=Load%20Nasabah%200777")
            self.assertEqual(search.data["count"], 1)
            self.assertEqual(
                search.data["results"][0]["id"], str(fixture_id("test-pil-393", "nasabah", 777))
            )
            payload = {
                "nasabah_id": manifest["recipient_ids"][0],
                "items": [{"jenis_sampah_id": manifest["jenis_id"], "berat": "1.000"}],
            }
            key = str(uuid4())
            first = client.post(
                "/api/v1/transaksi", payload, format="json", HTTP_IDEMPOTENCY_KEY=key
            )
            replay = client.post(
                "/api/v1/transaksi", payload, format="json", HTTP_IDEMPOTENCY_KEY=key
            )
            self.assertEqual(first.status_code, 201, first.data)
            self.assertEqual(replay.status_code, 200, replay.data)
            self.assertEqual(first.data["id"], replay.data["id"])
            self.assertEqual(self.command("audit", expected_writes=1)["new_writes"], 1)
            with self.assertRaisesMessage(CommandError, "Expected 2"):
                self.command("audit", expected_writes=2)
            member = Nasabah.objects.get(pk=manifest["recipient_ids"][0])
            Saldo.objects.filter(nasabah=member).update(total_saldo=1)
            with self.assertRaisesMessage(CommandError, "Incorrect balance"):
                self.command("audit", expected_writes=1)
            self.assertEqual(self.command("reset")["new_writes"], 0)
            self.assertTrue(
                User.objects.get(pk=manifest["accounts"][0]["id"]).check_password(
                    manifest["accounts"][0]["password"],
                )
            )
            self.command("cleanup")
            self.assertEqual(list(BankSampah.objects.values_list("id", flat=True)), [other.id])
            self.assertFalse(User.objects.exists())
            self.assertFalse(Transaksi.objects.exists())

    def test_audit_rejects_inconsistent_fixture_rows(self) -> None:
        with TemporaryDirectory() as folder:
            self.command("seed", manifest=Path(folder) / "accounts.json")
        run_id = "test-pil-393"
        bank = BankSampah.objects.get(pk=fixture_id(run_id, "bank"))
        User.objects.create_user(
            email=f"extra@{run_id}.load.invalid",
            nama="Extra fixture user",
            bank_sampah=bank,
        )
        foreign_bank = BankSampah.objects.create(nama="Outside bank", no_hp_pic="")
        foreign_member = Nasabah.objects.create(
            bank_sampah=foreign_bank,
            nomor="FOREIGN-1",
            nama="Outside member",
            no_hp="",
            email="outside@example.invalid",
        )
        transaction = Transaksi.objects.filter(bank_sampah=bank).first()
        assert transaction is not None
        transaction.nasabah = foreign_member
        transaction.catatan = "manual write without key"
        transaction.save(update_fields=["nasabah", "catatan"])
        detail = DetailTransaksi.objects.filter(transaksi=transaction).first()
        assert detail is not None
        detail.subtotal += 1
        detail.harga_snapshot = 1
        detail.save(update_fields=["subtotal", "harga_snapshot"])

        with self.assertRaises(CommandError) as raised:
            Command().audit(run_id, expected_writes=1)
        message = str(raised.exception)
        for expected in (
            "Expected 1 new writes, found 0",
            "Fixture account/customer count changed",
            "Transaction and item totals differ",
            "Item amount differs from fixture price and weight",
            "Cross-bank recipient found",
            "A new write lacks an idempotency key",
            "Incorrect balance",
        ):
            self.assertIn(expected, message)

    def test_audit_detects_duplicate_idempotency_keys_despite_database_constraint(self) -> None:
        rows = MagicMock()
        rows.count.return_value = 10000
        rows.annotate.return_value.exclude.return_value.exists.return_value = False
        rows.filter.return_value.exists.return_value = False
        cross_bank = MagicMock()
        cross_bank.exists.return_value = False
        no_key = MagicMock()
        no_key.filter.return_value.exists.return_value = False
        duplicate = MagicMock()
        duplicate.values.return_value.annotate.return_value.filter.return_value.exists.return_value = True
        rows.exclude.side_effect = [cross_bank, no_key, duplicate]
        members = MagicMock()
        members.count.return_value = 1000
        members.annotate.return_value.select_related.return_value = []
        users = MagicMock()
        users.count.return_value = 30
        details = MagicMock()
        details.exclude.return_value.exists.return_value = False
        with (
            patch.object(Transaksi.objects, "filter", return_value=rows),
            patch.object(Nasabah.objects, "filter", return_value=members),
            patch.object(User.objects, "filter", return_value=users),
            patch.object(DetailTransaksi.objects, "filter", return_value=details),
            self.assertRaisesMessage(CommandError, "Duplicate idempotency key"),
        ):
            Command().audit("test-pil-393", expected_writes=None)

    def test_postgres_telemetry_reports_connections_and_lock_waits(self) -> None:
        connection = MagicMock(vendor="postgresql")
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (8, 2, 1)
        with patch("api.management.commands.load_test_data.connection", connection):
            self.assertEqual(
                Command.telemetry(),
                {"connections": 8, "active": 2, "waiting_for_lock": 1},
            )
        connection.cursor.return_value.__enter__.return_value.execute.assert_called_once()

    def test_cleanup_refuses_missing_owned_fixture(self) -> None:
        with self.assertRaisesMessage(CommandError, "Owned fixture bank not found"):
            self.command("cleanup")

    def test_cleanup_refuses_foreign_data_in_owned_bank(self) -> None:
        bank = BankSampah.objects.create(
            id=fixture_id("test-pil-393", "bank"),
            nama="PIL-393 LOAD test-pil-393",
            no_hp_pic="",
        )
        User.objects.create_user("real@example.com", bank_sampah=bank, nama="Real UAT user")
        with self.assertRaisesMessage(CommandError, "Foreign data"):
            self.command("cleanup")
        self.assertTrue(User.objects.filter(email="real@example.com").exists())
