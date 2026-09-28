"""Public port of the membership context.

Read/write access to Nasabah rows from other contexts goes through here so
the locking and eligibility rules live in one place. Callers needing the
row lock must already be inside @transaction.atomic.
"""

from uuid import UUID

from django.db import IntegrityError, transaction

from api.models import BankSampah, Nasabah, User


def get_locked_nasabah(bank: BankSampah, nasabah_id: UUID) -> Nasabah | None:
    return (
        Nasabah.objects.select_for_update()
        .filter(
            id=nasabah_id,
            bank_sampah=bank,
            is_active=True,
            status=Nasabah.Status.APPROVED,
        )
        .first()
    )


def next_nasabah_number(bank_sampah: BankSampah) -> str:
    count = Nasabah.objects.filter(bank_sampah=bank_sampah).count() + 1
    return f"NAS-{count:04d}"


def propagate_profile_to_memberships(user: User) -> None:
    """Write the user's own profile onto every linked Nasabah row.

    The user's profile is authoritative (PIL-154 revised): whatever the
    account holds now overrides pengurus-entered data on the membership.
    Lives here so both authentication onboarding and the nasabah profile
    PATCH route through one implementation.
    """
    for nasabah in user.keanggotaan_nasabah.all():
        nasabah.nama = user.nama
        nasabah.jenis_kelamin = user.jenis_kelamin
        nasabah.tanggal_lahir = user.tanggal_lahir
        nasabah.alamat = user.alamat
        nasabah.no_hp = user.no_hp
        try:
            with transaction.atomic():
                nasabah.save(
                    update_fields=[
                        "nama",
                        "jenis_kelamin",
                        "tanggal_lahir",
                        "alamat",
                        "no_hp",
                        "updated_at",
                    ]
                )
        except IntegrityError as exc:
            raise ValueError(
                "Nomor HP ini sudah terdaftar di bank sampah ini, hubungi pengurus"
            ) from exc
