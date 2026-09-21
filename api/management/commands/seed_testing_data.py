import os
from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from api.models import (
    BankSampah,
    BankSampahApprovalLog,
    DetailTransaksi,
    JenisSampah,
    Nasabah,
    Saldo,
    Transaksi,
    User,
)
from api.services import DEFAULT_WA_TEMPLATE

CONFIRMATION = "SEED-PILAH-STAGING-DATA"

ACTIVE_BANK_ID = UUID("00000000-0000-4000-8000-000000000001")
PENDING_BANK_ID = UUID("00000000-0000-4000-8000-000000000002")
OPERATOR_ID = UUID("00000000-0000-4000-8000-000000000011")
PENDING_OPERATOR_ID = UUID("00000000-0000-4000-8000-000000000012")
SUPERADMIN_ID = UUID("00000000-0000-4000-8000-000000000013")
CUSTOMER_ONE_USER_ID = UUID("00000000-0000-4000-8000-000000000021")
CUSTOMER_TWO_USER_ID = UUID("00000000-0000-4000-8000-000000000022")
CUSTOMER_ONE_ID = UUID("00000000-0000-4000-8000-000000000031")
CUSTOMER_TWO_ID = UUID("00000000-0000-4000-8000-000000000032")

JENIS_PLASTIK_ID = UUID("00000000-0000-4000-8000-000000000041")
JENIS_KARDUS_ID = UUID("00000000-0000-4000-8000-000000000042")
JENIS_KACA_ID = UUID("00000000-0000-4000-8000-000000000043")
JENIS_LOGAM_ID = UUID("00000000-0000-4000-8000-000000000044")

TRANSACTION_ONE_ID = UUID("00000000-0000-4000-8000-000000000051")
TRANSACTION_TWO_ID = UUID("00000000-0000-4000-8000-000000000052")
TRANSACTION_THREE_ID = UUID("00000000-0000-4000-8000-000000000053")
DETAIL_ONE_ID = UUID("00000000-0000-4000-8000-000000000061")
DETAIL_TWO_ID = UUID("00000000-0000-4000-8000-000000000062")
DETAIL_THREE_ID = UUID("00000000-0000-4000-8000-000000000063")
DETAIL_FOUR_ID = UUID("00000000-0000-4000-8000-000000000064")
APPROVAL_LOG_ID = UUID("00000000-0000-4000-8000-000000000071")


@dataclass(frozen=True)
class SeedIdentities:
    operator_email: str
    customer_email: str
    customer_two_email: str
    superadmin_email: str
    pending_operator_email: str


class Command(BaseCommand):
    help = "Create or update deterministic local/staging data for end-to-end testing."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--environment", choices=("local", "staging"), default="local")
        parser.add_argument("--confirm")
        parser.add_argument(
            "--operator-email",
            default=os.getenv("PILAH_SEED_OPERATOR_EMAIL", "operator.demo@example.com"),
        )
        parser.add_argument(
            "--customer-email",
            default=os.getenv("PILAH_SEED_CUSTOMER_EMAIL", "customer.demo@example.com"),
        )
        parser.add_argument(
            "--customer-two-email",
            default=os.getenv("PILAH_SEED_CUSTOMER_TWO_EMAIL", "customer.two.demo@example.com"),
        )
        parser.add_argument(
            "--superadmin-email",
            default=os.getenv("PILAH_SEED_SUPERADMIN_EMAIL", "superadmin.demo@example.com"),
        )
        parser.add_argument(
            "--pending-operator-email",
            default=os.getenv(
                "PILAH_SEED_PENDING_OPERATOR_EMAIL", "pending.operator.demo@example.com"
            ),
        )

    def handle(self, *args: object, **options: object) -> None:
        environment = str(options["environment"])
        confirmation = str(options.get("confirm") or "")
        if environment == "local" and not settings.DEBUG:
            raise CommandError("Local testing data requires DJANGO_DEBUG=true")
        if environment == "staging" and confirmation != CONFIRMATION:
            raise CommandError(f"Pass --confirm={CONFIRMATION} to seed staging data")

        identities = SeedIdentities(
            operator_email=self._normalize_email(options["operator_email"]),
            customer_email=self._normalize_email(options["customer_email"]),
            customer_two_email=self._normalize_email(options["customer_two_email"]),
            superadmin_email=self._normalize_email(options["superadmin_email"]),
            pending_operator_email=self._normalize_email(options["pending_operator_email"]),
        )

        with transaction.atomic():
            self._seed(identities)

        self.stdout.write(self.style.SUCCESS(f"Seeded testing data for {environment} environment"))
        self.stdout.write(
            "Fixture includes 2 banks, 5 users, 2 customers, 4 waste types, "
            "3 transactions, and recalculated balances."
        )

    @staticmethod
    def _normalize_email(value: object) -> str:
        email = User.objects.normalize_email(str(value).strip())
        if not email or "@" not in email:
            raise CommandError(f"Invalid seed email: {value}")
        return email

    def _seed(self, identities: SeedIdentities) -> None:
        now = timezone.now()
        active_bank = BankSampah.objects.update_or_create(
            pk=ACTIVE_BANK_ID,
            defaults={
                "nama": "Bank Sampah PILAH E2E",
                "alamat": "Jl. E2E No. 1",
                "kota": "Depok",
                "no_hp_pic": "+628111111111",
                "jenis_organisasi": BankSampah.OrganizationType.MANDIRI,
                "parent": None,
                "status": BankSampah.Status.ACTIVE,
                "is_active": True,
                "wa_template": DEFAULT_WA_TEMPLATE,
                "invite_token": "SEED-PILAH-E2E-INVITE",
                "invite_token_expires": now + timedelta(days=7),
            },
        )[0]
        pending_bank = BankSampah.objects.update_or_create(
            pk=PENDING_BANK_ID,
            defaults={
                "nama": "Bank Sampah PILAH E2E Pending",
                "alamat": "Jl. E2E No. 2",
                "kota": "Depok",
                "no_hp_pic": "+628222222222",
                "jenis_organisasi": BankSampah.OrganizationType.MANDIRI,
                "parent": None,
                "status": BankSampah.Status.PENDING,
                "is_active": False,
                "wa_template": DEFAULT_WA_TEMPLATE,
                "invite_token": "",
                "invite_token_expires": None,
            },
        )[0]

        operator = self._upsert_user(
            user_id=OPERATOR_ID,
            email=identities.operator_email,
            name="Operator PILAH E2E",
            role=User.Role.PENGELOLA,
            bank=active_bank,
            is_primary=True,
        )
        self._upsert_user(
            user_id=PENDING_OPERATOR_ID,
            email=identities.pending_operator_email,
            name="Operator Pending PILAH E2E",
            role=User.Role.PENGELOLA,
            bank=pending_bank,
            is_primary=True,
        )
        superadmin = self._upsert_user(
            user_id=SUPERADMIN_ID,
            email=identities.superadmin_email,
            name="Superadmin PILAH E2E",
            role=User.Role.SUPERADMIN,
            bank=None,
            is_primary=False,
            is_staff=True,
            is_superuser=True,
        )
        BankSampahApprovalLog.objects.update_or_create(
            pk=APPROVAL_LOG_ID,
            defaults={
                "bank_sampah": active_bank,
                "superadmin": superadmin,
                "status": BankSampahApprovalLog.Status.APPROVED,
                "catatan": "Fixture approval untuk pengujian E2E",
            },
        )
        customer_one_user = self._upsert_user(
            user_id=CUSTOMER_ONE_USER_ID,
            email=identities.customer_email,
            name="Nasabah PILAH E2E",
            role=User.Role.NASABAH,
            bank=None,
            is_primary=False,
        )
        customer_two_user = self._upsert_user(
            user_id=CUSTOMER_TWO_USER_ID,
            email=identities.customer_two_email,
            name="Nasabah Kedua PILAH E2E",
            role=User.Role.NASABAH,
            bank=None,
            is_primary=False,
        )

        customer_one = self._upsert_customer(
            customer_id=CUSTOMER_ONE_ID,
            user=customer_one_user,
            bank=active_bank,
            number="NAS-0001",
            name="Nasabah PILAH E2E",
            gender=Nasabah.Gender.MALE,
            birth_date=date(1990, 1, 1),
            phone="+628333333331",
            address="Jl. Mawar E2E No. 1",
        )
        customer_two = self._upsert_customer(
            customer_id=CUSTOMER_TWO_ID,
            user=customer_two_user,
            bank=active_bank,
            number="NAS-0002",
            name="Nasabah Kedua PILAH E2E",
            gender=Nasabah.Gender.FEMALE,
            birth_date=date(1992, 2, 2),
            phone="+628333333332",
            address="Jl. Melati E2E No. 2",
        )

        jenis_plastik = self._upsert_waste_type(
            JENIS_PLASTIK_ID,
            active_bank,
            "JS-0001",
            "Plastik PET",
            JenisSampah.Kategori.PLASTIK,
            "Botol plastik bening",
            Decimal("3500.00"),
        )
        jenis_kardus = self._upsert_waste_type(
            JENIS_KARDUS_ID,
            active_bank,
            "JS-0002",
            "Kardus",
            JenisSampah.Kategori.KERTAS,
            "Kardus dan kertas tebal",
            Decimal("2000.00"),
        )
        jenis_kaca = self._upsert_waste_type(
            JENIS_KACA_ID,
            active_bank,
            "JS-0003",
            "Botol Kaca",
            JenisSampah.Kategori.KACA,
            "Botol kaca bersih",
            Decimal("1000.00"),
        )
        jenis_logam = self._upsert_waste_type(
            JENIS_LOGAM_ID,
            active_bank,
            "JS-0004",
            "Kaleng Aluminium",
            JenisSampah.Kategori.LOGAM,
            "Kaleng aluminium",
            Decimal("5000.00"),
        )

        self._upsert_transaction(
            transaction_id=TRANSACTION_ONE_ID,
            detail_ids=(DETAIL_ONE_ID, DETAIL_TWO_ID),
            bank=active_bank,
            operator=operator,
            customer=customer_one,
            transaction_time=now - timedelta(days=3),
            note="Setoran E2E pertama",
            items=(
                (jenis_plastik, Decimal("2.500")),
                (jenis_kardus, Decimal("1.000")),
            ),
        )
        self._upsert_transaction(
            transaction_id=TRANSACTION_TWO_ID,
            detail_ids=(DETAIL_THREE_ID,),
            bank=active_bank,
            operator=operator,
            customer=customer_one,
            transaction_time=now - timedelta(days=1),
            note="Setoran E2E kedua",
            items=((jenis_kaca, Decimal("3.000")),),
        )
        self._upsert_transaction(
            transaction_id=TRANSACTION_THREE_ID,
            detail_ids=(DETAIL_FOUR_ID,),
            bank=active_bank,
            operator=operator,
            customer=customer_two,
            transaction_time=now - timedelta(hours=4),
            note="Setoran E2E nasabah kedua",
            items=((jenis_logam, Decimal("1.500")),),
        )

        for customer in (customer_one, customer_two):
            total = Transaksi.objects.filter(nasabah=customer).aggregate(total=Sum("total_nilai"))[
                "total"
            ] or Decimal("0.00")
            Saldo.objects.update_or_create(nasabah=customer, defaults={"total_saldo": total})

    @staticmethod
    def _upsert_user(
        *,
        user_id: UUID,
        email: str,
        name: str,
        role: str,
        bank: BankSampah | None,
        is_primary: bool,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> User:
        user = User.objects.filter(pk=user_id).first()
        if user is None:
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User(
                    pk=user_id,
                    email=email,
                    nama=name,
                    role=role,
                    is_profile_complete=True,
                    bank_sampah=bank,
                    is_primary_pengelola=is_primary,
                    is_active=True,
                    is_staff=is_staff,
                    is_superuser=is_superuser,
                )
            else:
                same_fixture = (
                    user.nama == name
                    and user.role == role
                    and user.bank_sampah_id == (bank.pk if bank else None)
                    and user.is_primary_pengelola == is_primary
                    and user.is_staff == is_staff
                    and user.is_superuser == is_superuser
                )
                bare_account = (
                    not user.is_profile_complete
                    and user.bank_sampah_id is None
                    and not user.keanggotaan_nasabah.exists()
                    and not user.is_staff
                    and not user.is_superuser
                )
                if not same_fixture and not bare_account:
                    raise CommandError(
                        f"Seed email {email} belongs to an existing non-fixture account"
                    )
        user.email = email
        user.nama = name
        user.role = role
        user.is_profile_complete = True
        user.bank_sampah = bank
        user.is_primary_pengelola = is_primary
        user.is_active = True
        user.is_staff = is_staff
        user.is_superuser = is_superuser
        user.save(
            update_fields=[
                "email",
                "nama",
                "role",
                "is_profile_complete",
                "bank_sampah",
                "is_primary_pengelola",
                "is_active",
                "is_staff",
                "is_superuser",
                "updated_at",
            ]
        )
        return user

    @staticmethod
    def _upsert_customer(
        *,
        customer_id: UUID,
        user: User,
        bank: BankSampah,
        number: str,
        name: str,
        gender: str,
        birth_date: date,
        phone: str,
        address: str,
    ) -> Nasabah:
        customer, _ = Nasabah.objects.update_or_create(
            pk=customer_id,
            defaults={
                "user": user,
                "bank_sampah": bank,
                "nomor": number,
                "nama": name,
                "jenis_kelamin": gender,
                "tanggal_lahir": birth_date,
                "alamat": address,
                "no_hp": phone,
                "is_active": True,
            },
        )
        return customer

    @staticmethod
    def _upsert_waste_type(
        type_id: UUID,
        bank: BankSampah,
        number: str,
        name: str,
        category: str,
        description: str,
        price: Decimal,
    ) -> JenisSampah:
        jenis, _ = JenisSampah.objects.update_or_create(
            pk=type_id,
            defaults={
                "bank_sampah": bank,
                "nomor": number,
                "nama_sampah": name,
                "kategori": category,
                "deskripsi": description,
                "harga_per_kg": price,
                "is_active": True,
            },
        )
        return jenis

    @staticmethod
    def _upsert_transaction(
        *,
        transaction_id: UUID,
        detail_ids: tuple[UUID, ...],
        bank: BankSampah,
        operator: User,
        customer: Nasabah,
        transaction_time: datetime,
        note: str,
        items: tuple[tuple[JenisSampah, Decimal], ...],
    ) -> None:
        total = sum(
            (jenis.harga_per_kg * weight for jenis, weight in items),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))
        transaksi, created = Transaksi.objects.get_or_create(
            pk=transaction_id,
            defaults={
                "nasabah": customer,
                "bank_sampah": bank,
                "dicatat_oleh": operator,
                "tanggal": transaction_time,
                "total_nilai": total,
                "tipe": Transaksi.Tipe.SETORAN,
                "catatan": note,
                "status_wa": Transaksi.StatusWA.BELUM_DIKIRIM,
            },
        )
        if not created:
            transaksi.nasabah = customer
            transaksi.bank_sampah = bank
            transaksi.dicatat_oleh = operator
            transaksi.total_nilai = total
            transaksi.tipe = Transaksi.Tipe.SETORAN
            transaksi.catatan = note
            transaksi.status_wa = Transaksi.StatusWA.BELUM_DIKIRIM
            transaksi.save(
                update_fields=[
                    "nasabah",
                    "bank_sampah",
                    "dicatat_oleh",
                    "total_nilai",
                    "tipe",
                    "catatan",
                    "status_wa",
                    "updated_at",
                ]
            )
        for detail_id, (jenis, weight) in zip(detail_ids, items, strict=True):
            subtotal = (jenis.harga_per_kg * weight).quantize(Decimal("0.01"))
            DetailTransaksi.objects.update_or_create(
                pk=detail_id,
                defaults={
                    "transaksi": transaksi,
                    "jenis_sampah": jenis,
                    "nama_sampah_snapshot": jenis.nama_sampah,
                    "kategori_snapshot": jenis.kategori,
                    "harga_snapshot": jenis.harga_per_kg,
                    "berat": weight,
                    "subtotal": subtotal,
                },
            )
