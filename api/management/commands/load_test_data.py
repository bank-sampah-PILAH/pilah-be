"""Owned, staging-only fixtures for PIL-393; never reset the application database."""

import json
import os
import re
import secrets
from argparse import ArgumentParser
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Floor
from django.utils import timezone

from api.models import (
    BankSampah,
    DetailTransaksi,
    DraftPencairan,
    DraftPencairanItem,
    HargaSampah,
    JadwalKegiatan,
    JenisSampah,
    Nasabah,
    Pencairan,
    PencairanRevisi,
    PengurusDikeluarkan,
    Saldo,
    Transaksi,
    TransaksiRevisi,
    User,
)
from apps.waste_catalog.services import catat_harga

CONFIRMATION = "PIL-393-STAGING-ONLY"
CUSTOMERS = 1000
HISTORY = 10000
PRICE = Decimal(2500)


def fixture_id(run_id: str, kind: str, number: int = 0) -> UUID:
    return uuid5(NAMESPACE_URL, f"pilah-load/PIL-393/{run_id}/{kind}/{number}")


def private_json(path: Path, data: dict[str, Any]) -> None:
    # Refuse symlinks/existing files so a manifest cannot overwrite another file.
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
        json.dump(data, output, indent=2)


class Command(BaseCommand):
    help = "Prepare, reset, audit or clean up one isolated PIL-393 local/staging bank."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("action", choices=("seed", "reset", "audit", "cleanup", "telemetry"))
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--confirm", required=True)
        parser.add_argument("--manifest", type=Path)
        parser.add_argument("--expected-writes", type=int)
        parser.add_argument("--expected-drafts", type=int)
        parser.add_argument("--expected-payouts", type=int)

    def handle(self, *args: Any, **options: Any) -> None:
        run_id = options["run_id"]
        action = options["action"]
        manifest_path = options["manifest"]
        self._validate_request(run_id, action, manifest_path, options)
        with transaction.atomic():
            result = self._run_action(run_id, action, manifest_path, options)
        self.stdout.write(json.dumps(result))

    @staticmethod
    def _validate_request(
        run_id: str, action: str, manifest_path: Path | None, options: dict[str, Any]
    ) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", run_id):
            raise CommandError("run-id must be 1–32 lowercase letters, digits or hyphens")
        if options["confirm"] != CONFIRMATION:
            raise CommandError(f"Pass --confirm={CONFIRMATION}")
        database = settings.DATABASES["default"]
        engine = database.get("ENGINE")
        host = database.get("HOST", "")
        staging_db_host = getattr(
            settings, "PILAH_STAGING_DB_HOST", os.getenv("PILAH_STAGING_DB_HOST", "")
        )
        local = (
            settings.DEBUG
            and settings.PILAH_ENVIRONMENT in ("", "local")
            and (
                (
                    engine == "django.db.backends.sqlite3"
                    and host in ("", "localhost", "127.0.0.1", "::1")
                )
                or (
                    engine == "django.db.backends.postgresql"
                    and isinstance(host, str)
                    and host.lower() in ("localhost", "127.0.0.1", "::1", "db")
                )
            )
        )
        staging = (
            settings.PILAH_ENVIRONMENT == "staging"
            and engine == "django.db.backends.postgresql"
            and isinstance(host, str)
            and host.lower().endswith(".neon.tech")
            and isinstance(staging_db_host, str)
            and host.lower() == staging_db_host.lower()
        )
        # Production uses a Cloud SQL socket. Fly staging uses its separate Neon DB.
        if not (local or staging):
            raise CommandError("Only a local database or staging's separate Neon DB is allowed")
        if action == "seed" and (
            manifest_path is None or not manifest_path.is_absolute() or manifest_path.exists()
        ):
            raise CommandError("seed requires a new absolute --manifest path outside Git")
        if (
            action == "seed"
            and manifest_path is not None
            and any((parent / ".git").exists() for parent in manifest_path.resolve().parents)
        ):
            raise CommandError("seed manifest must be outside Git worktrees")

    def _run_action(
        self, run_id: str, action: str, manifest_path: Path | None, options: dict[str, Any]
    ) -> dict[str, Any]:
        bank_id = fixture_id(run_id, "bank")
        if action == "seed":
            if BankSampah.objects.filter(pk=bank_id).exists():
                raise CommandError("Fixture already exists; use reset to retain sessions")
            manifest = self.seed(run_id)
            assert manifest_path is not None
            # Failure to persist credentials rolls back all fixture writes.
            result = self.audit(run_id, 0)
            private_json(manifest_path, manifest)
            return result

        if action == "reset" and BankSampah.objects.filter(pk=bank_id, is_active=False).exists():
            raise CommandError("Fixture bank is archived; refusing reset")
        self.check_owner(run_id)
        if action == "telemetry":
            return self.telemetry()
        if action == "audit":
            return self.audit(
                run_id,
                options["expected_writes"],
                options["expected_drafts"],
                options["expected_payouts"],
            )
        if action == "cleanup":
            self._guard_payouts_and_drafts(run_id, bank_id, action)
            self.reset_activity(run_id, bank_id)
        if action == "reset":
            if not BankSampah.objects.filter(pk=bank_id, is_active=True).exists():
                raise CommandError("Fixture bank is archived; refusing reset")
            self.reset_activity(run_id, bank_id)
            self.history(run_id)
            self.restore_team(run_id, bank_id)
            return self.audit(run_id, 0, 0, 0)
        Transaksi.objects.filter(bank_sampah_id=bank_id).delete()
        JadwalKegiatan.objects.filter(bank_sampah_id=bank_id).delete()
        Nasabah.objects.filter(bank_sampah_id=bank_id).delete()
        User.objects.filter(pk__in=self.user_ids(run_id)).delete()
        # Price versions are append-only and PROTECT their fixture bank/type.
        # Keep those rows with explicitly inactive archival parents.
        JenisSampah.objects.filter(bank_sampah_id=bank_id).update(is_active=False)
        BankSampah.objects.filter(pk=bank_id).update(is_active=False)
        retained_prices = HargaSampah.objects.filter(bank_sampah_id=bank_id).count()
        return {
            "run_id": run_id,
            "cleaned": True,
            "retained_immutable_prices": retained_prices,
            "archived_bank_id": str(bank_id),
        }

    def _guard_payouts_and_drafts(self, run_id: str, bank_id: UUID, action: str) -> None:
        if action != "cleanup":
            return
        user_ids = self.user_ids(run_id)
        foreign_payouts = Pencairan.objects.filter(
            Q(nasabah__bank_sampah_id=bank_id) | Q(dicatat_oleh_id__in=user_ids)
        ).exclude(bank_sampah_id=bank_id)
        foreign_revisions = PencairanRevisi.objects.filter(diubah_oleh_id__in=user_ids).exclude(
            pencairan__bank_sampah_id=bank_id
        )
        foreign_drafts = DraftPencairan.objects.filter(
            Q(dibuat_oleh_id__in=user_ids) | Q(diubah_oleh_id__in=user_ids)
        ).exclude(bank_sampah_id=bank_id)
        foreign_transactions = TransaksiRevisi.objects.filter(diubah_oleh_id__in=user_ids).exclude(
            transaksi__bank_sampah_id=bank_id
        )
        foreign_team_logs = PengurusDikeluarkan.objects.filter(
            Q(user_id__in=user_ids) | Q(dikeluarkan_oleh_id__in=user_ids)
        ).exclude(bank_sampah_id=bank_id)
        foreign_draft_items = DraftPencairanItem.objects.filter(
            nasabah__bank_sampah_id=bank_id
        ).exclude(draft__bank_sampah_id=bank_id)
        if any(
            query.exists()
            for query in (
                foreign_payouts,
                foreign_revisions,
                foreign_drafts,
                foreign_transactions,
                foreign_team_logs,
                foreign_draft_items,
            )
        ):
            raise CommandError(
                "Fixture bank has foreign financial or team records; refusing cleanup"
            )

    @staticmethod
    def user_ids(run_id: str) -> list[UUID]:
        return [fixture_id(run_id, "user", index) for index in range(30)]

    def check_owner(self, run_id: str) -> None:
        bank_id = fixture_id(run_id, "bank")
        bank = BankSampah.objects.filter(pk=bank_id, nama=f"PIL-393 LOAD {run_id}").first()
        if not bank:
            raise CommandError("Owned fixture bank not found")
        users = User.objects.filter(bank_sampah_id=bank_id)
        fixture_users = User.objects.filter(pk__in=self.user_ids(run_id))
        members = Nasabah.objects.filter(bank_sampah_id=bank_id)
        if (
            Transaksi.objects.filter(bank_sampah_id=bank_id)
            .exclude(dicatat_oleh_id__in=self.user_ids(run_id))
            .exists()
            or users.exclude(pk__in=self.user_ids(run_id)).exists()
            or fixture_users.count() != 30
            or fixture_users.exclude(bank_sampah__isnull=True)
            .exclude(bank_sampah_id=bank_id)
            .exists()
            or users.filter(is_staff=True).exists()
            or users.filter(is_superuser=True).exists()
            or users.exclude(email__endswith=f"@{run_id}.load.invalid").exists()
            or members.exclude(
                pk__in=[fixture_id(run_id, "nasabah", index) for index in range(CUSTOMERS)]
            ).exists()
        ):
            raise CommandError("Foreign data found in fixture bank; refusing changes")

    def seed(self, run_id: str) -> dict[str, Any]:
        bank = BankSampah.objects.create(
            id=fixture_id(run_id, "bank"),
            nama=f"PIL-393 LOAD {run_id}",
            no_hp_pic="",
            alamat="Synthetic load-test data only",
        )
        password = secrets.token_urlsafe(24)
        password_hash = make_password(password)
        accounts = []
        users = []
        for index in range(30):
            role = User.Role.PENGELOLA if index < 21 else User.Role.NASABAH
            email = f"user-{index:02d}@{run_id}.load.invalid"
            user = User(
                id=fixture_id(run_id, "user", index),
                email=email,
                nama=f"Load User {index:02d}",
                role=role,
                bank_sampah=bank,
                password=password_hash,
                email_verified=True,
                is_profile_complete=True,
                is_primary_pengelola=index == 0,
            )
            users.append(user)
            accounts.append(
                {
                    "id": str(user.id),
                    "email": email,
                    "password": password,
                    "role": role,
                    "nasabah_id": str(fixture_id(run_id, "nasabah", index - 21))
                    if index >= 21
                    else None,
                }
            )
        User.objects.bulk_create(users)
        members = [
            Nasabah(
                id=fixture_id(run_id, "nasabah", index),
                bank_sampah=bank,
                user=users[index + 21] if index < 9 else None,
                nomor=f"LOAD{index:04d}",
                nama=f"Load Nasabah {index:04d}",
                no_hp=f"+6280000{index:06d}",
                email=users[index + 21].email
                if index < 9
                else f"member-{index}@{run_id}.load.invalid",
                alamat="Synthetic test address",
            )
            for index in range(CUSTOMERS)
        ]
        Nasabah.objects.bulk_create(members)
        Saldo.objects.bulk_create([Saldo(nasabah=member) for member in members])
        jenis = JenisSampah.objects.create(
            id=fixture_id(run_id, "jenis"),
            bank_sampah=bank,
            nomor="LOAD01",
            nama_sampah="Load Plastik",
        )
        catat_harga(jenis, PRICE, timezone.now(), users[0])
        start = timezone.now() + timedelta(days=1)
        JadwalKegiatan.objects.create(
            bank_sampah=bank,
            dibuat_oleh=users[0],
            jenis_kegiatan=JadwalKegiatan.JenisKegiatan.PENIMBANGAN,
            mulai_pada=start,
            selesai_pada=start + timedelta(hours=2),
            lokasi="Synthetic load-test location",
            status=JadwalKegiatan.Status.DITERBITKAN,
        )
        self.history(run_id)
        return {
            "run_id": run_id,
            "bank_id": str(bank.id),
            "jenis_id": str(jenis.id),
            "price": int(PRICE),
            "customers": CUSTOMERS,
            "history": HISTORY,
            "recipient_ids": [str(member.id) for member in members],
            "staff_ids": [account["id"] for account in accounts if account["role"] == "pengelola"],
            "edit_transaction_ids": [str(fixture_id(run_id, "history", i)) for i in range(21)],
            "void_transaction_ids": [
                str(fixture_id(run_id, "history", 1000 + i)) for i in range(21)
            ],
            "accounts": accounts,
        }

    def reset_activity(self, run_id: str, bank_id: UUID) -> None:
        user_ids = self.user_ids(run_id)
        bank_payouts = Pencairan.objects.filter(bank_sampah_id=bank_id)
        if (
            bank_payouts.exclude(dicatat_oleh_id__in=user_ids).exists()
            or bank_payouts.exclude(nasabah__bank_sampah_id=bank_id).exists()
            or Pencairan.objects.filter(
                Q(nasabah__bank_sampah_id=bank_id) | Q(dicatat_oleh_id__in=user_ids)
            )
            .exclude(bank_sampah_id=bank_id)
            .exists()
        ):
            raise CommandError("Foreign payout found in fixture bank; refusing reset")
        drafts = DraftPencairan.objects.filter(bank_sampah_id=bank_id)
        if (
            drafts.exclude(dibuat_oleh_id__in=user_ids, diubah_oleh_id__in=user_ids).exists()
            or DraftPencairanItem.objects.filter(draft__bank_sampah_id=bank_id)
            .exclude(nasabah__bank_sampah_id=bank_id)
            .exists()
            or DraftPencairan.objects.filter(
                Q(dibuat_oleh_id__in=user_ids) | Q(diubah_oleh_id__in=user_ids)
            )
            .exclude(bank_sampah_id=bank_id)
            .exists()
        ):
            raise CommandError("Foreign payout draft found in fixture bank; refusing reset")
        if (
            TransaksiRevisi.objects.filter(transaksi__bank_sampah_id=bank_id)
            .exclude(diubah_oleh_id__in=user_ids)
            .exists()
        ):
            raise CommandError("Foreign setoran revision found in fixture bank; refusing reset")
        if (
            PencairanRevisi.objects.filter(pencairan__bank_sampah_id=bank_id)
            .exclude(diubah_oleh_id__in=user_ids)
            .exists()
            or PengurusDikeluarkan.objects.filter(bank_sampah_id=bank_id)
            .exclude(dikeluarkan_oleh_id__in=user_ids)
            .exists()
        ):
            raise CommandError("Foreign payout/team revision found in fixture bank; refusing reset")
        PencairanRevisi.objects.filter(pencairan__bank_sampah_id=bank_id).delete()
        bank_payouts.delete()
        drafts.delete()
        TransaksiRevisi.objects.filter(transaksi__bank_sampah_id=bank_id).delete()
        PengurusDikeluarkan.objects.filter(bank_sampah_id=bank_id).delete()

    def restore_team(self, run_id: str, bank_id: UUID) -> None:
        staff_ids = [fixture_id(run_id, "user", index) for index in range(21)]
        staff = User.objects.filter(pk__in=staff_ids, role=User.Role.PENGELOLA, is_active=True)
        if staff.count() != len(staff_ids):
            raise CommandError("Fixture team changed unexpectedly; refusing reset")
        staff.update(bank_sampah_id=bank_id, is_primary_pengelola=False)
        User.objects.filter(pk=staff_ids[0]).update(is_primary_pengelola=True)

    def history(self, run_id: str) -> None:
        bank_id = fixture_id(run_id, "bank")
        TransaksiRevisi.objects.filter(transaksi__bank_sampah_id=bank_id).delete()
        Transaksi.objects.filter(bank_sampah_id=bank_id).delete()
        now = timezone.now()
        transactions = [
            Transaksi(
                id=fixture_id(run_id, "history", index),
                bank_sampah_id=bank_id,
                nasabah_id=fixture_id(run_id, "nasabah", index % CUSTOMERS),
                dicatat_oleh_id=fixture_id(run_id, "user", index % 21),
                tanggal=now - timedelta(days=1 + index % 365),
                total_nilai=PRICE,
                catatan=f"PIL-393 baseline {run_id}",
            )
            for index in range(HISTORY)
        ]
        Transaksi.objects.bulk_create(transactions, batch_size=500)
        DetailTransaksi.objects.bulk_create(
            [
                DetailTransaksi(
                    transaksi=row,
                    jenis_sampah_id=fixture_id(run_id, "jenis"),
                    nama_sampah_snapshot="Load Plastik",
                    kategori_snapshot="plastik",
                    harga_snapshot=PRICE,
                    berat=Decimal(1),
                    subtotal=PRICE,
                )
                for row in transactions
            ],
            batch_size=500,
        )
        Saldo.objects.filter(nasabah__bank_sampah_id=bank_id).update(
            total_saldo=PRICE * (HISTORY // CUSTOMERS)
        )

    def audit(
        self,
        run_id: str,
        expected_writes: int | None,
        expected_drafts: int | None = None,
        expected_payouts: int | None = None,
    ) -> dict[str, Any]:
        bank_id = fixture_id(run_id, "bank")
        rows = Transaksi.objects.filter(bank_sampah_id=bank_id)
        members = Nasabah.objects.filter(bank_sampah_id=bank_id)
        draft_rows = DraftPencairan.objects.filter(bank_sampah_id=bank_id)
        payout_rows = Pencairan.objects.filter(bank_sampah_id=bank_id)
        writes, drafts, payouts = rows.count() - HISTORY, draft_rows.count(), payout_rows.count()
        errors: list[str] = []
        self._audit_counts(
            errors,
            bank_id,
            members,
            writes,
            drafts,
            payouts,
            expected_writes,
            expected_drafts,
            expected_payouts,
        )
        self._audit_integrity(errors, run_id, bank_id, rows, payout_rows)
        self._audit_balances(errors, bank_id, members, rows, payout_rows)
        if errors:
            raise CommandError("Integrity failure: " + "; ".join(errors))
        return {
            "run_id": run_id,
            "customers": members.count(),
            "history": HISTORY,
            "new_writes": writes,
            "payout_drafts": drafts,
            "payouts": payouts,
            "integrity_errors": 0,
        }

    @staticmethod
    def _audit_counts(
        errors: list[str],
        bank_id: UUID,
        members: Any,
        writes: int,
        drafts: int,
        payouts: int,
        expected_writes: int | None,
        expected_drafts: int | None,
        expected_payouts: int | None,
    ) -> None:
        if expected_writes is not None and writes != expected_writes:
            errors.append(f"Expected {expected_writes} new writes, found {writes}")
        if expected_drafts is not None and drafts != expected_drafts:
            errors.append(f"Expected {expected_drafts} payout drafts, found {drafts}")
        if expected_payouts is not None and payouts != expected_payouts:
            errors.append(f"Expected {expected_payouts} payouts, found {payouts}")
        if (
            members.count() != CUSTOMERS
            or User.objects.filter(bank_sampah_id=bank_id).count() != 30
        ):
            errors.append("Fixture account/customer count changed")

    @staticmethod
    def _audit_integrity(
        errors: list[str], run_id: str, bank_id: UUID, rows: Any, payout_rows: Any
    ) -> None:
        if (
            rows.annotate(items_total=Sum("items__subtotal"))
            .exclude(items_total=F("total_nilai"))
            .exists()
            or rows.filter(items__isnull=True).exists()
        ):
            errors.append("Transaction and item totals differ")
        if (
            DetailTransaksi.objects.filter(transaksi__bank_sampah_id=bank_id)
            .exclude(subtotal=Floor(F("berat") * F("harga_snapshot")))
            .exists()
        ):
            errors.append("Item amount differs from fixture price and weight")
        if rows.exclude(nasabah__bank_sampah_id=bank_id).exists():
            errors.append("Cross-bank recipient found")
        if (
            payout_rows.exclude(nasabah__bank_sampah_id=bank_id).exists()
            or DraftPencairanItem.objects.filter(draft__bank_sampah_id=bank_id)
            .exclude(nasabah__bank_sampah_id=bank_id)
            .exists()
        ):
            errors.append("Cross-bank payout recipient found")
        if (
            rows.exclude(catatan=f"PIL-393 baseline {run_id}")
            .filter(idempotency_key__isnull=True)
            .exclude(revisi__isnull=False)
            .exists()
        ):
            errors.append("A new write lacks an idempotency key")
        if (
            rows.exclude(idempotency_key=None)
            .values("idempotency_key")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
            .exists()
        ):
            errors.append("Duplicate idempotency key")

    @staticmethod
    def _audit_balances(
        errors: list[str], bank_id: UUID, members: Any, rows: Any, payout_rows: Any
    ) -> None:
        deposit_totals = dict(
            rows.filter(status=Transaksi.Status.TERCATAT)
            .values("nasabah_id")
            .annotate(total=Sum("total_nilai"))
            .values_list("nasabah_id", "total")
        )
        payout_totals = dict(
            payout_rows.values("nasabah_id")
            .annotate(total=Sum("nominal"))
            .values_list("nasabah_id", "total")
        )
        balances = dict(
            Saldo.objects.filter(nasabah__bank_sampah_id=bank_id).values_list(
                "nasabah_id", "total_saldo"
            )
        )
        for member_id in members.values_list("pk", flat=True):
            expected = deposit_totals.get(member_id, Decimal(0)) - payout_totals.get(
                member_id, Decimal(0)
            )
            if balances.get(member_id, Decimal(0)) != expected:
                errors.append(f"Incorrect balance for {member_id}")
                break

    @staticmethod
    def telemetry() -> dict[str, Any]:
        if connection.vendor != "postgresql":
            return {"database_metrics": "unavailable for non-PostgreSQL database"}
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*), count(*) FILTER (WHERE state = 'active'), "
                "count(*) FILTER (WHERE wait_event_type = 'Lock') "
                "FROM pg_stat_activity WHERE datname = current_database()"
            )
            connections, active, waiting = cursor.fetchone()
        return {"connections": connections, "active": active, "waiting_for_lock": waiting}
