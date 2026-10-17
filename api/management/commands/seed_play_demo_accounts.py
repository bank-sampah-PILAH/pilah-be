from argparse import ArgumentParser
from datetime import datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from api.models import (
    BankSampah,
    DetailTransaksi,
    JadwalKegiatan,
    JenisSampah,
    Nasabah,
    Pencairan,
    Saldo,
    Transaksi,
    User,
)
from apps.bank_sampah.constants import REVIEW_BANK_ID
from shared_kernel.kalkulasi import hitung_subtotal, total_setoran
from shared_kernel.permissions import review_superadmin_allowlist, superadmin_allowlist

DEMO_BANK_ID = UUID("00000000-0000-4000-8000-000000000362")
DEMO_NASABAH_ID = UUID("00000000-0000-4000-8000-000000000363")
REVIEW_OWNER_ID = UUID("00000000-0000-4000-8000-000000000365")
WASTE_TYPE_IDS = tuple(
    UUID(f"00000000-0000-4000-8000-000000000{value}") for value in range(366, 370)
)
TRANSACTION_IDS = tuple(
    UUID(f"00000000-0000-4000-8000-000000000{value}") for value in range(370, 373)
)
DETAIL_IDS = tuple(UUID(f"00000000-0000-4000-8000-000000000{value}") for value in range(373, 377))
SCHEDULE_IDS = tuple(UUID(f"00000000-0000-4000-8000-000000000{value}") for value in range(377, 379))
DEMO_BANK_NAME = "Bank Sampah PILAH Demo"
REVIEW_BANK_NAME = "Bank Sampah PILAH Review Pending"
DEMO_NASABAH_NUMBER = "DEMO-0001"
DEMO_NASABAH_EMAIL = "pilah.nasabah@gmail.com"
SUPERADMIN_EMAIL = "pilah.superadmin@gmail.com"
REVIEW_OWNER_EMAIL = "pilah.review-owner@example.test"
DEMO_NASABAH_ADDRESS = "Alamat demo untuk akun nasabah PILAH"

WASTE_TYPE_FIXTURES = (
    (
        "JS-0001",
        "Plastik PET",
        JenisSampah.Kategori.PLASTIK,
        "Botol plastik bening",
        Decimal("3500.00"),
    ),
    (
        "JS-0002",
        "Kardus",
        JenisSampah.Kategori.KERTAS,
        "Kardus dan kertas tebal",
        Decimal("2000.00"),
    ),
    ("JS-0003", "Botol Kaca", JenisSampah.Kategori.KACA, "Botol kaca bersih", Decimal("1000.00")),
    (
        "JS-0004",
        "Kaleng Aluminium",
        JenisSampah.Kategori.LOGAM,
        "Kaleng aluminium",
        Decimal("5000.00"),
    ),
)

ACCOUNTS = {
    "owner": ("pilah.pengelola@gmail.com", "Demo Pengelola PILAH", User.Role.PENGELOLA),
    "pengurus": ("pilah.pengurus@gmail.com", "Demo Pengurus PILAH", User.Role.PENGELOLA),
    "nasabah": (DEMO_NASABAH_EMAIL, "Demo Nasabah PILAH", User.Role.NASABAH),
    "superadmin": (SUPERADMIN_EMAIL, "SuperAdmin PILAH", User.Role.SUPERADMIN),
}


class Command(BaseCommand):
    help = "Create the explicit production Google demo accounts and their minimal sample data."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--confirm-production", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        dry_run = bool(options.get("dry_run"))
        self._validate_runtime(dry_run, bool(options.get("confirm_production")))

        with transaction.atomic():
            bank = self._existing_bank()
            review_bank = self._existing_review_bank()
            users = {
                name: self._existing_user(email, role)
                for name, (email, _display_name, role) in ACCOUNTS.items()
            }
            membership = self._existing_membership(users["nasabah"])
            review_owner = self._existing_review_owner()
            self._validate_seed_owned_rows()

            if dry_run:
                self.stdout.write(
                    "Dry run: validated production target; would ensure one demo bank, "
                    "4 Google accounts, an approved nasabah membership, synthetic catalog, "
                    "setoran history, published schedules, and a pending review bank."
                )
                return

            bank = bank or self._create_bank()
            review_bank = review_bank or self._create_review_bank()
            for name, (email, display_name, role) in ACCOUNTS.items():
                users[name] = self._ensure_user(
                    users[name],
                    email=email,
                    display_name=display_name,
                    role=role,
                    bank=bank,
                    primary=name == "owner",
                )
            self._ensure_user(
                review_owner,
                email=REVIEW_OWNER_EMAIL,
                display_name="Pemilik Bank Sampah PILAH Review",
                role=User.Role.PENGELOLA,
                bank=review_bank,
                primary=True,
                user_id=REVIEW_OWNER_ID,
            )

            nasabah_user = users["nasabah"]
            pengurus = users["pengurus"]
            if nasabah_user is None or pengurus is None:
                raise CommandError("Production demo accounts could not be created")
            membership = membership or self._create_membership(bank, nasabah_user)
            if membership.user_id is None:
                membership.user = nasabah_user
                membership.save(update_fields=["user", "updated_at"])

            waste_types = self._ensure_waste_types(bank)
            self._ensure_transactions(bank, pengurus, membership, waste_types)
            self._ensure_schedules(bank, pengurus)
            self._recalculate_balance(membership)

        self.stdout.write(self.style.SUCCESS("Production Google demo accounts are ready."))

    @staticmethod
    def _validate_runtime(dry_run: bool, confirmed: bool) -> None:
        if settings.PILAH_ENVIRONMENT != "production" or settings.DEBUG:
            raise CommandError("Demo accounts can only be seeded in production with DEBUG=false")
        if SUPERADMIN_EMAIL in superadmin_allowlist():
            raise CommandError("pilah.superadmin@gmail.com must not be in PILAH_SUPERADMIN_EMAILS")
        if SUPERADMIN_EMAIL not in review_superadmin_allowlist():
            raise CommandError(
                "pilah.superadmin@gmail.com must be in PILAH_REVIEW_SUPERADMIN_EMAILS"
            )
        if not dry_run and not confirmed:
            raise CommandError("Pass --confirm-production before writing production demo data")

    @staticmethod
    def _existing_bank() -> BankSampah | None:
        bank = BankSampah.objects.select_for_update().filter(pk=DEMO_BANK_ID).first()
        if bank is not None and (
            bank.nama != DEMO_BANK_NAME
            or bank.jenis_organisasi != BankSampah.OrganizationType.MANDIRI
            or bank.parent_id is not None
            or bank.status != BankSampah.Status.ACTIVE
            or not bank.is_active
        ):
            raise CommandError("Production demo bank identity conflicts with existing data")
        return bank

    @staticmethod
    def _existing_review_bank() -> BankSampah | None:
        bank = BankSampah.objects.select_for_update().filter(pk=REVIEW_BANK_ID).first()
        if bank is not None and (
            bank.nama != REVIEW_BANK_NAME
            or bank.jenis_organisasi != BankSampah.OrganizationType.MANDIRI
            or bank.parent_id is not None
            or bank.status not in BankSampah.Status.values
            or bank.is_active != (bank.status == BankSampah.Status.ACTIVE)
        ):
            raise CommandError("Production review bank identity conflicts with existing data")
        return bank

    @staticmethod
    def _existing_review_owner() -> User | None:
        matches = list(
            User.objects.select_for_update().filter(
                Q(pk=REVIEW_OWNER_ID) | Q(email__iexact=REVIEW_OWNER_EMAIL)
            )[:2]
        )
        if len(matches) > 1:
            raise CommandError("Production review owner identity conflicts with existing data")
        if not matches:
            return None

        user = matches[0]
        if (
            user.pk != REVIEW_OWNER_ID
            or user.email.lower() != REVIEW_OWNER_EMAIL
            or user.role != User.Role.PENGELOLA
            or not user.is_active
            or user.bank_sampah_id not in (None, REVIEW_BANK_ID)
            or user.google_id is not None
            or user.has_usable_password()
            or user.is_staff
            or user.is_superuser
        ):
            raise CommandError("Production review owner identity conflicts with existing data")
        return user

    @staticmethod
    def _validate_seed_owned_rows() -> None:
        Command._validate_waste_type_rows()
        Command._validate_transaction_rows()
        Command._validate_schedule_rows()

    @staticmethod
    def _validate_waste_type_rows() -> None:
        for type_id, (number, _name, _category, _description, _price) in zip(
            WASTE_TYPE_IDS, WASTE_TYPE_FIXTURES, strict=True
        ):
            jenis = JenisSampah.objects.select_for_update().filter(pk=type_id).first()
            number_match = (
                JenisSampah.objects.select_for_update()
                .filter(bank_sampah_id=DEMO_BANK_ID, nomor=number)
                .first()
            )
            if jenis and (jenis.bank_sampah_id != DEMO_BANK_ID or jenis.nomor != number):
                raise CommandError(
                    "Production demo waste type identity conflicts with existing data"
                )
            if number_match and number_match.pk != type_id:
                raise CommandError("Production demo waste type number is already used")

    @staticmethod
    def _validate_transaction_rows() -> None:
        detail_transaction_ids = (
            TRANSACTION_IDS[0],
            TRANSACTION_IDS[0],
            TRANSACTION_IDS[1],
            TRANSACTION_IDS[2],
        )
        for transaction_id in TRANSACTION_IDS:
            item = Transaksi.objects.select_for_update().filter(pk=transaction_id).first()
            if item and (
                item.bank_sampah_id != DEMO_BANK_ID
                or item.nasabah_id != DEMO_NASABAH_ID
                or item.tipe != Transaksi.Tipe.SETORAN
                or item.idempotency_key is not None
            ):
                raise CommandError(
                    "Production demo transaction identity conflicts with existing data"
                )
        for detail_id, transaction_id in zip(DETAIL_IDS, detail_transaction_ids, strict=True):
            detail = DetailTransaksi.objects.select_for_update().filter(pk=detail_id).first()
            if detail and detail.transaksi_id != transaction_id:
                raise CommandError(
                    "Production demo transaction detail identity conflicts with existing data"
                )

    @staticmethod
    def _validate_schedule_rows() -> None:
        for schedule_id, activity in zip(
            SCHEDULE_IDS,
            (JadwalKegiatan.JenisKegiatan.PENIMBANGAN, JadwalKegiatan.JenisKegiatan.PENCAIRAN),
            strict=True,
        ):
            schedule = JadwalKegiatan.objects.select_for_update().filter(pk=schedule_id).first()
            if schedule and (
                schedule.bank_sampah_id != DEMO_BANK_ID or schedule.jenis_kegiatan != activity
            ):
                raise CommandError("Production demo schedule identity conflicts with existing data")

    @staticmethod
    def _existing_user(email: str, role: str) -> User | None:
        matches = list(User.objects.select_for_update().filter(email__iexact=email)[:2])
        if len(matches) > 1:
            raise CommandError(f"Production demo account conflict: {email} matches multiple users")
        if not matches:
            return None

        user = matches[0]
        if user.role != role or not user.is_active:
            raise CommandError(
                f"Production demo account conflict for {email}: role or active state"
            )
        if role == User.Role.SUPERADMIN:
            if user.bank_sampah_id is not None:
                raise CommandError(f"Production demo account conflict for {email}: bank assignment")
        elif role == User.Role.NASABAH:
            if user.bank_sampah_id is not None or user.is_primary_pengelola:
                raise CommandError(f"Production demo account conflict for {email}: bank assignment")
        elif user.bank_sampah_id not in (None, DEMO_BANK_ID):
            raise CommandError(f"Production demo account conflict for {email}: another bank")
        return user

    @staticmethod
    def _existing_membership(user: User | None) -> Nasabah | None:
        query = Q(email__iexact=DEMO_NASABAH_EMAIL)
        if user is not None:
            query |= Q(user=user)
        matches = list(Nasabah.objects.select_for_update().filter(query).order_by("pk")[:2])
        if len(matches) > 1:
            raise CommandError("Production demo nasabah email matches multiple memberships")
        membership = matches[0] if matches else None
        if membership is not None and membership.bank_sampah_id != DEMO_BANK_ID:
            raise CommandError("Production demo nasabah email is already used by another bank")
        if (
            membership is not None
            and user is not None
            and membership.user_id not in (None, user.pk)
        ):
            raise CommandError("Production demo nasabah membership belongs to another account")
        if membership is not None and user is None and membership.user_id is not None:
            raise CommandError("Production demo nasabah membership belongs to another account")
        if membership is not None and membership.email.lower() != DEMO_NASABAH_EMAIL:
            raise CommandError("Production demo nasabah account has a conflicting membership email")
        if membership is not None and membership.nomor != DEMO_NASABAH_NUMBER:
            raise CommandError("Production demo nasabah account has a conflicting member number")
        if membership is not None and (
            not membership.is_active or membership.status != Nasabah.Status.APPROVED
        ):
            raise CommandError("Production demo nasabah membership is inactive or unapproved")
        if (
            user is not None
            and Nasabah.objects.select_for_update()
            .filter(user=user)
            .exclude(bank_sampah_id=DEMO_BANK_ID)
            .exists()
        ):
            raise CommandError("Production demo nasabah account already belongs to another bank")
        if (
            membership is None
            and Nasabah.objects.select_for_update().filter(pk=DEMO_NASABAH_ID).exists()
        ):
            raise CommandError("Production demo nasabah identity conflicts with existing data")
        number_matches = Nasabah.objects.select_for_update().filter(
            bank_sampah_id=DEMO_BANK_ID,
            nomor=DEMO_NASABAH_NUMBER,
        )
        if membership is not None:
            number_matches = number_matches.exclude(pk=membership.pk)
        if number_matches.exists():
            raise CommandError("Production demo nasabah number is already used")
        return membership

    @staticmethod
    def _create_bank() -> BankSampah:
        return BankSampah.objects.create(
            id=DEMO_BANK_ID,
            nama=DEMO_BANK_NAME,
            alamat="Alamat data demo PILAH",
            kota="Depok",
            no_hp_pic="",
            jenis_organisasi=BankSampah.OrganizationType.MANDIRI,
            status=BankSampah.Status.ACTIVE,
            is_active=True,
        )

    @staticmethod
    def _create_review_bank() -> BankSampah:
        return BankSampah.objects.create(
            id=REVIEW_BANK_ID,
            nama=REVIEW_BANK_NAME,
            alamat="Alamat sintetis untuk peninjauan PILAH",
            kota="Depok",
            no_hp_pic="",
            jenis_organisasi=BankSampah.OrganizationType.MANDIRI,
            status=BankSampah.Status.PENDING,
            is_active=False,
        )

    @staticmethod
    def _ensure_user(
        user: User | None,
        *,
        email: str,
        display_name: str,
        role: str,
        bank: BankSampah,
        primary: bool,
        user_id: UUID | None = None,
    ) -> User:
        if user is None:
            if user_id is not None:
                user = User(
                    id=user_id,
                    email=email,
                    nama=display_name,
                    role=role,
                    is_profile_complete=True,
                    bank_sampah=bank if role == User.Role.PENGELOLA else None,
                    is_primary_pengelola=primary,
                )
                user.set_unusable_password()
                user.save()
                return user
            return User.objects.create_user(
                email=email,
                nama=display_name,
                role=role,
                is_profile_complete=True,
                bank_sampah=bank if role == User.Role.PENGELOLA else None,
                is_primary_pengelola=primary,
                **({"alamat": DEMO_NASABAH_ADDRESS} if role == User.Role.NASABAH else {}),
            )

        target_bank = bank if role == User.Role.PENGELOLA else None
        fields = []
        if user.bank_sampah_id != (target_bank.pk if target_bank else None):
            user.bank_sampah = target_bank
            fields.append("bank_sampah")
        if user.is_primary_pengelola != primary:
            user.is_primary_pengelola = primary
            fields.append("is_primary_pengelola")
        if not user.is_profile_complete:
            user.is_profile_complete = True
            fields.append("is_profile_complete")
        if not user.nama:
            user.nama = display_name
            fields.append("nama")
        if role == User.Role.SUPERADMIN and (user.is_staff or user.is_superuser):
            user.is_staff = False
            user.is_superuser = False
            fields.extend(("is_staff", "is_superuser"))
        if role == User.Role.NASABAH and not user.alamat:
            user.alamat = DEMO_NASABAH_ADDRESS
            fields.append("alamat")
        if fields:
            user.save(update_fields=[*fields, "updated_at"])
        return user

    @staticmethod
    def _create_membership(bank: BankSampah, user: User) -> Nasabah:
        membership = Nasabah.objects.create(
            id=DEMO_NASABAH_ID,
            user=user,
            bank_sampah=bank,
            nomor=DEMO_NASABAH_NUMBER,
            nama=user.nama or "Demo Nasabah PILAH",
            jenis_kelamin=user.jenis_kelamin,
            tanggal_lahir=user.tanggal_lahir,
            alamat=user.alamat or DEMO_NASABAH_ADDRESS,
            no_hp=user.no_hp,
            email=DEMO_NASABAH_EMAIL,
            is_active=True,
            status=Nasabah.Status.APPROVED,
        )
        return membership

    @staticmethod
    def _ensure_waste_types(bank: BankSampah) -> dict[str, JenisSampah]:
        result = {}
        for type_id, fixture in zip(WASTE_TYPE_IDS, WASTE_TYPE_FIXTURES, strict=True):
            number, name, category, description, price = fixture
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
            result[name] = jenis
        return result

    @staticmethod
    def _ensure_transactions(
        bank: BankSampah,
        pengurus: User,
        membership: Nasabah,
        waste_types: dict[str, JenisSampah],
    ) -> None:
        now = timezone.now()
        fixtures = (
            (
                TRANSACTION_IDS[0],
                (DETAIL_IDS[0], DETAIL_IDS[1]),
                now - timedelta(days=3),
                "Setoran demo PET dan Kardus",
                (("Plastik PET", Decimal("2.500")), ("Kardus", Decimal("1.000"))),
            ),
            (
                TRANSACTION_IDS[1],
                (DETAIL_IDS[2],),
                now - timedelta(days=1),
                "Setoran demo Botol Kaca",
                (("Botol Kaca", Decimal("3.000")),),
            ),
            (
                TRANSACTION_IDS[2],
                (DETAIL_IDS[3],),
                now - timedelta(hours=4),
                "Setoran demo Kaleng Aluminium",
                (("Kaleng Aluminium", Decimal("1.500")),),
            ),
        )
        for transaction_id, detail_ids, date, note, items in fixtures:
            priced_items = tuple((waste_types[name], weight) for name, weight in items)
            subtotals = tuple(
                hitung_subtotal(jenis.harga_per_kg, weight) for jenis, weight in priced_items
            )
            total = total_setoran(subtotals)
            transaksi, created = Transaksi.objects.get_or_create(
                pk=transaction_id,
                defaults={
                    "nasabah": membership,
                    "bank_sampah": bank,
                    "dicatat_oleh": pengurus,
                    "tanggal": date,
                    "total_nilai": total,
                    "tipe": Transaksi.Tipe.SETORAN,
                    "catatan": note,
                },
            )
            if not created:
                transaksi.nasabah = membership
                transaksi.bank_sampah = bank
                transaksi.dicatat_oleh = pengurus
                transaksi.total_nilai = total
                transaksi.tipe = Transaksi.Tipe.SETORAN
                transaksi.catatan = note
                transaksi.save(
                    update_fields=[
                        "nasabah",
                        "bank_sampah",
                        "dicatat_oleh",
                        "total_nilai",
                        "tipe",
                        "catatan",
                        "updated_at",
                    ]
                )
            for detail_id, (jenis, weight), subtotal in zip(
                detail_ids, priced_items, subtotals, strict=True
            ):
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

    @staticmethod
    def _ensure_schedules(bank: BankSampah, pengurus: User) -> None:
        today = timezone.localdate()
        fixtures = (
            (SCHEDULE_IDS[0], JadwalKegiatan.JenisKegiatan.PENIMBANGAN, 7),
            (SCHEDULE_IDS[1], JadwalKegiatan.JenisKegiatan.PENCAIRAN, 14),
        )
        tz = timezone.get_current_timezone()
        for schedule_id, activity, days in fixtures:
            date = today + timedelta(days=days)
            starts_at = timezone.make_aware(datetime.combine(date, time(9, 0)), tz)
            ends_at = timezone.make_aware(datetime.combine(date, time(11, 0)), tz)
            JadwalKegiatan.objects.update_or_create(
                pk=schedule_id,
                defaults={
                    "bank_sampah": bank,
                    "dibuat_oleh": pengurus,
                    "jenis_kegiatan": activity,
                    "mulai_pada": starts_at,
                    "selesai_pada": ends_at,
                    "lokasi": "Bank Sampah PILAH Demo",
                    "keterangan": "Jadwal sintetis untuk akun review PILAH",
                    "cakupan_penerima": JadwalKegiatan.CakupanPenerima.SEMUA_NASABAH,
                    "status": JadwalKegiatan.Status.DITERBITKAN,
                },
            )

    @staticmethod
    def _recalculate_balance(membership: Nasabah) -> None:
        setoran = Transaksi.objects.filter(
            nasabah=membership, tipe=Transaksi.Tipe.SETORAN
        ).aggregate(total=Sum("total_nilai"))["total"] or Decimal("0.00")
        pencairan = Pencairan.objects.filter(nasabah=membership).aggregate(
            total=Sum(F("saldo_sebelum") - F("saldo_sesudah"))
        )["total"] or Decimal("0.00")
        saldo, _ = Saldo.objects.get_or_create(
            nasabah=membership, defaults={"total_saldo": Decimal("0.00")}
        )
        total_saldo = setoran - pencairan
        if saldo.total_saldo != total_saldo:
            saldo.total_saldo = total_saldo
            saldo.save(update_fields=["total_saldo", "updated_at"])
