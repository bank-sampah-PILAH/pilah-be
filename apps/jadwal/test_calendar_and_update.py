from datetime import timedelta
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone
from rest_framework import serializers
from rest_framework.test import APITestCase

from api.models import BankSampah, JadwalKegiatan, Nasabah, User
from apps.jadwal.serializers import JadwalKegiatanSerializer


def _bank_with_pengelola(nama: str = "Bank Jadwal") -> tuple[BankSampah, User]:
    bank = BankSampah.objects.create(nama=nama, alamat="Depok", kota="Depok")
    pengelola = User.objects.create_user(
        email=f"{nama.replace(' ', '').lower()}@example.test",
        nama="Pengelola",
        bank_sampah=bank,
        is_profile_complete=True,
        is_primary_pengelola=True,
    )
    return bank, pengelola


def _nasabah(bank: BankSampah, nomor: str, no_hp: str) -> Nasabah:
    return Nasabah.objects.create(
        bank_sampah=bank,
        nomor=nomor,
        nama=f"Nasabah {nomor}",
        email=f"{nomor.lower()}@example.test",
        no_hp=no_hp,
        alamat="Jl. A",
    )


class JadwalCalendarDatesTests(APITestCase):
    def setUp(self) -> None:
        _, pengelola = _bank_with_pengelola()
        self.client.force_authenticate(pengelola)
        self.url = "/api/v1/jadwal/calendar-dates"

    def test_both_dates_are_required_in_iso_format(self) -> None:
        response = self.client.get(self.url, {"start_date": "2026-01-01"})

        self.assertEqual(response.status_code, 422)
        self.assertIn("date_range", response.data["errors"])

    def test_range_is_limited_to_sixty_three_days(self) -> None:
        response = self.client.get(self.url, {"start_date": "2026-01-01", "end_date": "2026-03-10"})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            str(response.data["errors"]["date_range"]), "Rentang kalender maksimal 63 hari"
        )


class JadwalNasabahListTests(APITestCase):
    def setUp(self) -> None:
        self.bank, self.manager = _bank_with_pengelola("Bank Jadwal Satu")
        self.other_bank, self.other_manager = _bank_with_pengelola("Bank Jadwal Dua")
        self.user = User.objects.create_user(
            email="nasabah@example.test", nama="Nasabah", role=User.Role.NASABAH
        )
        self.member = _nasabah(self.bank, "NAS-1001", "+628111111111")
        self.member.user = self.user
        self.member.status = Nasabah.Status.APPROVED
        self.member.save()
        self.other_member = _nasabah(self.other_bank, "NAS-2001", "+628222222222")
        self.other_member.user = self.user
        self.other_member.status = Nasabah.Status.APPROVED
        self.other_member.save()
        self.unselected_member = _nasabah(self.bank, "NAS-1002", "+628333333333")
        self.unselected_member.status = Nasabah.Status.APPROVED
        self.unselected_member.save()
        self.client.force_authenticate(self.user)
        starts_at = timezone.now() + timedelta(days=2)
        self.own_schedule = self._schedule(
            self.bank, self.manager, starts_at, JadwalKegiatan.CakupanPenerima.SEMUA_NASABAH
        )
        self.targeted_schedule = self._schedule(
            self.bank,
            self.manager,
            starts_at + timedelta(days=1),
            JadwalKegiatan.CakupanPenerima.NASABAH_TERPILIH,
            [self.member],
        )
        self.other_targeted_schedule = self._schedule(
            self.bank,
            self.manager,
            starts_at + timedelta(days=2),
            JadwalKegiatan.CakupanPenerima.NASABAH_TERPILIH,
            [self.unselected_member],
        )
        self.other_schedule = self._schedule(
            self.other_bank,
            self.other_manager,
            starts_at + timedelta(days=4),
            JadwalKegiatan.CakupanPenerima.SEMUA_NASABAH,
        )

    @staticmethod
    def _schedule(bank, manager, starts_at, coverage, recipients=()):
        schedule = JadwalKegiatan.objects.create(
            bank_sampah=bank,
            dibuat_oleh=manager,
            jenis_kegiatan=JadwalKegiatan.JenisKegiatan.PENIMBANGAN,
            mulai_pada=starts_at,
            selesai_pada=starts_at + timedelta(hours=1),
            lokasi="Balai Warga",
            cakupan_penerima=coverage,
            status=JadwalKegiatan.Status.DITERBITKAN,
        )
        schedule.penerima.set(recipients)
        return schedule

    def test_list_is_scoped_to_selected_membership_bank_and_exact_recipients(self) -> None:
        response = self.client.get("/api/v1/jadwal", {"keanggotaan_id": str(self.member.id)})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            {item["id"] for item in response.data["results"]},
            {str(self.own_schedule.id), str(self.targeted_schedule.id)},
        )

    def test_membership_selection_errors_follow_nasabah_contract(self) -> None:
        for query, expected in (({}, 422), ({"keanggotaan_id": "bad"}, 422)):
            with self.subTest(query=query):
                response = self.client.get("/api/v1/jadwal", query)
                self.assertEqual(response.status_code, expected)
        foreign = _nasabah(self.bank, "NAS-1003", "+628444444444")
        response = self.client.get("/api/v1/jadwal", {"keanggotaan_id": str(foreign.id)})
        self.assertEqual(response.status_code, 404)

    def test_ineligible_selected_membership_is_forbidden(self) -> None:
        self.member.is_active = False
        self.member.save()

        response = self.client.get("/api/v1/jadwal", {"keanggotaan_id": str(self.member.id)})

        self.assertEqual(response.status_code, 403)

    def test_calendar_dates_are_scoped_to_selected_membership_bank_and_recipients(self) -> None:
        start = (timezone.now() + timedelta(days=2)).date()
        response = self.client.get(
            "/api/v1/jadwal/calendar-dates",
            {
                "start_date": start.isoformat(),
                "end_date": (start + timedelta(days=5)).isoformat(),
                "keanggotaan_id": str(self.member.id),
            },
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["dates"],
            [start.isoformat(), (start + timedelta(days=1)).isoformat()],
        )


class JadwalUpdateTests(APITestCase):
    def test_editing_a_targeted_schedule_keeps_its_selected_recipients(self) -> None:
        bank, pengelola = _bank_with_pengelola()
        nasabah = _nasabah(bank, "NAS-0001", "+628111111111")
        self.client.force_authenticate(pengelola)
        starts_at = timezone.now() + timedelta(days=2)
        created = self.client.post(
            "/api/v1/jadwal",
            {
                "jenis_kegiatan": "penimbangan",
                "mulai_pada": starts_at.isoformat(),
                "selesai_pada": (starts_at + timedelta(hours=2)).isoformat(),
                "lokasi": "Balai Warga",
                "cakupan_penerima": "nasabah_terpilih",
                "penerima_ids": [str(nasabah.id)],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)

        response = self.client.patch(
            f"/api/v1/jadwal/{created.data['id']}", {"lokasi": "Kantor"}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["lokasi"], "Kantor")
        self.assertEqual([str(pk) for pk in response.data["penerima_ids"]], [str(nasabah.id)])


class JadwalRecipientBoundaryTests(TestCase):
    def test_recipients_from_another_bank_are_refused(self) -> None:
        bank, pengelola = _bank_with_pengelola("Bank Satu")
        other_bank, _ = _bank_with_pengelola("Bank Dua")
        outsider = _nasabah(other_bank, "NAS-0001", "+628222222222")
        serializer = JadwalKegiatanSerializer(context={"request": SimpleNamespace(user=pengelola)})

        # The recipient field already narrows choices to the caller's bank;
        # validate() repeats the check for values that bypass the field.
        with self.assertRaises(serializers.ValidationError) as caught:
            serializer.validate(
                {
                    "cakupan_penerima": JadwalKegiatan.CakupanPenerima.NASABAH_TERPILIH,
                    "penerima": [outsider],
                }
            )

        self.assertIn("penerima_ids", caught.exception.detail)
        self.assertNotEqual(outsider.bank_sampah_id, bank.id)
