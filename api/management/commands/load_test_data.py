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
from django.db.models import Count, F, Sum
from django.db.models.functions import Floor
from django.utils import timezone

from api.models import (
    BankSampah,
    DetailTransaksi,
    HargaSampah,
    JadwalKegiatan,
    JenisSampah,
    Nasabah,
    Saldo,
    Transaksi,
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
        host = database["HOST"]
        local = settings.DEBUG and settings.PILAH_ENVIRONMENT in ("", "local")
        staging = settings.PILAH_ENVIRONMENT == "staging"
        # Production uses a Cloud SQL socket. Fly staging uses its separate Neon DB.
        if not (local or staging) or (
            staging and (not isinstance(host, str) or not host.endswith(".neon.tech"))
        ):
            raise CommandError("Only a local database or staging's separate Neon DB is allowed")
        action = options["action"]
        manifest_path = options["manifest"]
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

        self.check_owner(run_id)
        if action == "telemetry":
            return self.telemetry()
        if action == "audit":
            return self.audit(run_id, options["expected_writes"])
        if action == "reset":
            self.history(run_id)
            return self.audit(run_id, 0)
        Transaksi.objects.filter(bank_sampah_id=bank_id).delete()
        HargaSampah.objects.filter(bank_sampah_id=bank_id).delete()
        JadwalKegiatan.objects.filter(bank_sampah_id=bank_id).delete()
        Nasabah.objects.filter(bank_sampah_id=bank_id).delete()
        User.objects.filter(pk__in=self.user_ids(run_id)).delete()
        BankSampah.objects.get(pk=bank_id).delete()
        return {"run_id": run_id, "cleaned": True}

    @staticmethod
    def user_ids(run_id: str) -> list[UUID]:
        return [fixture_id(run_id, "user", index) for index in range(30)]

    def check_owner(self, run_id: str) -> None:
        bank_id = fixture_id(run_id, "bank")
        bank = BankSampah.objects.filter(pk=bank_id, nama=f"PIL-393 LOAD {run_id}").first()
        if not bank:
            raise CommandError("Owned fixture bank not found")
        users = User.objects.filter(bank_sampah_id=bank_id)
        members = Nasabah.objects.filter(bank_sampah_id=bank_id)
        if (
            Transaksi.objects.filter(bank_sampah_id=bank_id)
            .exclude(dicatat_oleh_id__in=self.user_ids(run_id))
            .exists()
            or users.exclude(pk__in=self.user_ids(run_id)).exists()
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
        catat_harga(jenis, PRICE, timezone.now() - timedelta(days=400), users[0])
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
            "accounts": accounts,
        }

    def history(self, run_id: str) -> None:
        bank_id = fixture_id(run_id, "bank")
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

    def audit(self, run_id: str, expected_writes: int | None) -> dict[str, Any]:
        bank_id = fixture_id(run_id, "bank")
        rows = Transaksi.objects.filter(bank_sampah_id=bank_id)
        members = Nasabah.objects.filter(bank_sampah_id=bank_id)
        errors = []
        writes = rows.count() - HISTORY
        if expected_writes is not None and writes != expected_writes:
            errors.append(f"Expected {expected_writes} new writes, found {writes}")
        if (
            members.count() != CUSTOMERS
            or User.objects.filter(bank_sampah_id=bank_id).count() != 30
        ):
            errors.append("Fixture account/customer count changed")
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
            rows.exclude(catatan=f"PIL-393 baseline {run_id}")
            .filter(idempotency_key__isnull=True)
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
        for member in members.annotate(expected=Sum("transaksi__total_nilai")).select_related(
            "saldo"
        ):
            if member.saldo.total_saldo != member.expected:
                errors.append(f"Incorrect balance for {member.id}")
                break
        if errors:
            raise CommandError("Integrity failure: " + "; ".join(errors))
        return {
            "run_id": run_id,
            "customers": members.count(),
            "history": HISTORY,
            "new_writes": writes,
            "integrity_errors": 0,
        }

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
