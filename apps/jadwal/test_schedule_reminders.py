from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import BankSampah, JadwalKegiatan, Nasabah, PushNotification, User
from apps.jadwal.api import queue_due_schedule_reminders


class ScheduleReminderTests(TestCase):
    def setUp(self) -> None:
        self.now = timezone.now()
        self.bank = BankSampah.objects.create(nama="Melati", alamat="Depok", kota="Depok")
        self.manager = User.objects.create_user(
            email="reminder-manager@example.test",
            nama="Manager",
            bank_sampah=self.bank,
            is_profile_complete=True,
        )
        self.member = self.add_member("reminder-member@example.test", "1")

    def add_member(self, email: str, number: str) -> Nasabah:
        user = User.objects.create_user(email=email, nama=number, role=User.Role.NASABAH)
        return Nasabah.objects.create(
            bank_sampah=self.bank,
            user=user,
            nomor=number,
            nama=number,
            email=email,
            no_hp=f"08123{number}",
        )

    def make_schedule(
        self,
        *,
        start: timedelta = timedelta(hours=2),
        scope: str = JadwalKegiatan.CakupanPenerima.SEMUA_NASABAH,
        status: str = JadwalKegiatan.Status.DITERBITKAN,
        reminder_queued_at: datetime | None = None,
    ) -> JadwalKegiatan:
        mulai_pada = self.now + start
        return JadwalKegiatan.objects.create(
            bank_sampah=self.bank,
            dibuat_oleh=self.manager,
            jenis_kegiatan=JadwalKegiatan.JenisKegiatan.PENIMBANGAN,
            mulai_pada=mulai_pada,
            selesai_pada=mulai_pada + timedelta(hours=1),
            lokasi="Balai",
            cakupan_penerima=scope,
            status=status,
            reminder_queued_at=reminder_queued_at,
        )

    def test_reminder_uses_actual_start_time_when_worker_runs_late(self) -> None:
        schedule = self.make_schedule(
            scope=JadwalKegiatan.CakupanPenerima.NASABAH_TERPILIH,
            start=timedelta(minutes=20),
        )
        schedule.penerima.add(self.member)
        other = self.add_member("reminder-other@example.test", "2")

        self.assertEqual(queue_due_schedule_reminders(self.now), 1)
        self.assertEqual(queue_due_schedule_reminders(self.now), 0)
        self.assertEqual(
            PushNotification.objects.filter(
                user=self.member.user, title="Pengingat jadwal"
            ).count(),
            1,
        )
        self.assertFalse(
            PushNotification.objects.filter(user=other.user, title="Pengingat jadwal").exists()
        )
        schedule.refresh_from_db()
        self.assertEqual(schedule.reminder_queued_at, self.now)
        notification = PushNotification.objects.get(user=self.member.user, title="Pengingat jadwal")
        self.assertIn(
            f"dimulai pukul {timezone.localtime(schedule.mulai_pada):%H:%M} WIB",
            notification.body,
        )
        self.assertNotIn("2 jam lagi", notification.body)

    def test_default_scope_reminds_all_eligible_members(self) -> None:
        other = self.add_member("reminder-all@example.test", "3")
        pending = self.add_member("reminder-pending@example.test", "4")
        pending.status = Nasabah.Status.PENDING
        pending.save(update_fields=["status"])
        self.make_schedule()

        self.assertEqual(queue_due_schedule_reminders(self.now), 2)
        self.assertEqual(
            set(
                PushNotification.objects.filter(title="Pengingat jadwal").values_list(
                    "user_id", flat=True
                )
            ),
            {self.member.user_id, other.user_id},
        )
        self.assertFalse(
            PushNotification.objects.filter(user=pending.user, title="Pengingat jadwal").exists()
        )

    def test_late_draft_and_not_yet_due_schedules_are_skipped(self) -> None:
        self.make_schedule(start=timedelta(hours=1), status=JadwalKegiatan.Status.DRAFT)
        self.make_schedule(start=timedelta(minutes=-1))
        self.make_schedule(start=timedelta(hours=3))

        self.assertEqual(queue_due_schedule_reminders(self.now), 0)
        self.assertFalse(PushNotification.objects.filter(title="Pengingat jadwal").exists())

    def test_enqueue_failure_leaves_reminder_due_for_retry(self) -> None:
        schedule = self.make_schedule()
        with patch("apps.jadwal.api.queue_push_bulk", return_value=None):
            self.assertEqual(queue_due_schedule_reminders(self.now), 0)
        schedule.refresh_from_db()
        self.assertIsNone(schedule.reminder_queued_at)

        self.assertEqual(queue_due_schedule_reminders(self.now), 1)
        schedule.refresh_from_db()
        self.assertEqual(schedule.reminder_queued_at, self.now)

    def test_no_eligible_recipients_marks_due_reminder_as_skipped(self) -> None:
        self.member.status = Nasabah.Status.REJECTED
        self.member.save(update_fields=["status"])
        schedule = self.make_schedule()

        self.assertEqual(queue_due_schedule_reminders(self.now), 0)
        schedule.refresh_from_db()
        self.assertEqual(schedule.reminder_queued_at, self.now)
        self.assertFalse(PushNotification.objects.filter(title="Pengingat jadwal").exists())

    def test_schedule_locked_by_another_worker_is_left_for_that_worker(self) -> None:
        from unittest.mock import patch

        schedule = self.make_schedule()
        with patch("apps.jadwal.api.JadwalKegiatan.objects.select_for_update") as lock_query:
            lock_query.return_value.select_related.return_value.filter.return_value.first.return_value = None
            self.assertEqual(queue_due_schedule_reminders(self.now), 0)
        schedule.refresh_from_db()
        self.assertIsNone(schedule.reminder_queued_at)

    def test_rescheduling_to_a_future_reminder_window_resets_marker(self) -> None:
        schedule = self.make_schedule(start=timedelta(hours=1), reminder_queued_at=self.now)
        client = APIClient()
        client.force_authenticate(self.manager)
        new_start = self.now + timedelta(hours=5)

        response = client.patch(
            f"/api/v1/jadwal/{schedule.pk}",
            {
                "mulai_pada": new_start.isoformat(),
                "selesai_pada": (new_start + timedelta(hours=1)).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        schedule.refresh_from_db()
        self.assertIsNone(schedule.reminder_queued_at)
        self.assertEqual(queue_due_schedule_reminders(self.now + timedelta(hours=3)), 1)
