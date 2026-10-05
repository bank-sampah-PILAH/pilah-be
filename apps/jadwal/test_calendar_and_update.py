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
        bank_sampah=bank, nomor=nomor, nama=f"Nasabah {nomor}", no_hp=no_hp, alamat="Jl. A"
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

        self.assertIn("penerima_ids", caught.exception.detail)  # type: ignore[arg-type]
        self.assertNotEqual(outsider.bank_sampah_id, bank.id)
