from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from api.models import BankSampah, JadwalKegiatan, Nasabah, PushNotification, User


class SchedulePushTests(APITestCase):
    def test_publication_notifies_only_selected_active_members(self) -> None:
        bank = BankSampah.objects.create(nama="Melati", alamat="Depok", kota="Depok")
        manager = User.objects.create_user(
            email="manager@example.test", nama="Manager", bank_sampah=bank, is_profile_complete=True
        )
        selected = User.objects.create_user(
            email="selected@example.test", nama="Selected", role=User.Role.NASABAH
        )
        other = User.objects.create_user(
            email="other@example.test", nama="Other", role=User.Role.NASABAH
        )
        member = Nasabah.objects.create(
            bank_sampah=bank,
            user=selected,
            nomor="1",
            nama="Selected",
            email="selected@example.test",
            no_hp="08123",
        )
        Nasabah.objects.create(
            bank_sampah=bank,
            user=other,
            nomor="2",
            nama="Other",
            email="other@example.test",
            no_hp="08124",
        )
        start = timezone.now() + timedelta(days=1)
        schedule = JadwalKegiatan.objects.create(
            bank_sampah=bank,
            dibuat_oleh=manager,
            jenis_kegiatan="penimbangan",
            mulai_pada=start,
            selesai_pada=start + timedelta(hours=1),
            lokasi="Balai",
            cakupan_penerima="nasabah_terpilih",
        )
        schedule.penerima.add(member)
        self.client.force_authenticate(manager)
        response = self.client.post(f"/api/v1/jadwal/{schedule.pk}/terbitkan")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(PushNotification.objects.filter(user=selected).exists())
        self.assertFalse(PushNotification.objects.filter(user=other).exists())

        response = self.client.patch(
            f"/api/v1/jadwal/{schedule.pk}", {"lokasi": "Pasar"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(
            PushNotification.objects.filter(user=selected, title="Jadwal berubah").exists()
        )
        response = self.client.post(f"/api/v1/jadwal/{schedule.pk}/batalkan")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(
            PushNotification.objects.filter(user=selected, title="Jadwal dibatalkan").exists()
        )
        self.assertFalse(PushNotification.objects.filter(user=other).exists())

    def test_removed_recipient_is_not_asked_to_open_inaccessible_schedule(self) -> None:
        bank = BankSampah.objects.create(nama="Melati", alamat="Depok", kota="Depok")
        manager = User.objects.create_user(
            email="manager2@example.test",
            nama="Manager",
            bank_sampah=bank,
            is_profile_complete=True,
        )
        user = User.objects.create_user(
            email="removed@example.test", nama="User", role=User.Role.NASABAH
        )
        member = Nasabah.objects.create(
            bank_sampah=bank,
            user=user,
            nomor="1",
            nama="User",
            email="removed@example.test",
            no_hp="08123",
        )
        other = User.objects.create_user(
            email="new@example.test", nama="New", role=User.Role.NASABAH
        )
        other_member = Nasabah.objects.create(
            bank_sampah=bank,
            user=other,
            nomor="2",
            nama="New",
            email="new@example.test",
            no_hp="08124",
        )
        start = timezone.now() + timedelta(days=1)
        schedule = JadwalKegiatan.objects.create(
            bank_sampah=bank,
            dibuat_oleh=manager,
            jenis_kegiatan="penimbangan",
            mulai_pada=start,
            selesai_pada=start + timedelta(hours=1),
            lokasi="Balai",
            cakupan_penerima="nasabah_terpilih",
            status="diterbitkan",
        )
        schedule.penerima.add(member)
        self.client.force_authenticate(manager)
        response = self.client.patch(
            f"/api/v1/jadwal/{schedule.pk}", {"penerima_ids": [str(other_member.pk)]}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(
            PushNotification.objects.filter(
                user=user, title="Jadwal tidak lagi untuk Anda"
            ).exists()
        )
        self.assertTrue(
            PushNotification.objects.filter(user=other, title="Jadwal berubah").exists()
        )
