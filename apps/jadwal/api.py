"""Public notification operations for schedule events."""

from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from api.models import BankSampah, JadwalKegiatan, Nasabah, User
from apps.notification.api import queue_push_bulk


def schedule_recipients(jadwal: JadwalKegiatan, now: datetime | None = None) -> set[User]:
    now = now or timezone.now()
    if jadwal.selesai_pada < now:
        return set()
    members = Nasabah.objects.filter(
        bank_sampah=jadwal.bank_sampah,
        bank_sampah__status=BankSampah.Status.ACTIVE,
        bank_sampah__is_active=True,
        status=Nasabah.Status.APPROVED,
        is_active=True,
        user__is_active=True,
    )
    if jadwal.cakupan_penerima == JadwalKegiatan.CakupanPenerima.NASABAH_TERPILIH:
        members = members.filter(jadwal_kegiatan=jadwal)
    return set(User.objects.filter(pk__in=members.values("user_id")))


def queue_due_schedule_reminders(now: datetime | None = None) -> int:
    now = now or timezone.now()
    schedule_ids = list(
        JadwalKegiatan.objects.filter(
            status=JadwalKegiatan.Status.DITERBITKAN,
            reminder_queued_at__isnull=True,
            mulai_pada__gt=now,
            mulai_pada__lte=now + timedelta(hours=2),
        )
        .order_by("mulai_pada", "pk")
        .values_list("pk", flat=True)
    )
    queued = 0
    for schedule_id in schedule_ids:
        with transaction.atomic():
            jadwal = (
                JadwalKegiatan.objects.select_for_update(skip_locked=True)
                .select_related("bank_sampah")
                .filter(
                    pk=schedule_id,
                    status=JadwalKegiatan.Status.DITERBITKAN,
                    reminder_queued_at__isnull=True,
                    mulai_pada__gt=now,
                    mulai_pada__lte=now + timedelta(hours=2),
                )
                .first()
            )
            if jadwal is None:
                continue
            recipients = schedule_recipients(jadwal, now)
            if recipients:
                start = timezone.localtime(jadwal.mulai_pada)
                notifications = queue_push_bulk(
                    recipients,
                    title="Pengingat jadwal",
                    body=(
                        f"{jadwal.get_jenis_kegiatan_display()} di {jadwal.bank_sampah.nama} "
                        f"dimulai 2 jam lagi, pukul {start:%H:%M} WIB. Lokasi: {jadwal.lokasi}."
                    ),
                )
                if notifications is None:
                    continue
                queued += len(notifications)
            jadwal.reminder_queued_at = now
            jadwal.save(update_fields=["reminder_queued_at", "updated_at"])
    return queued
