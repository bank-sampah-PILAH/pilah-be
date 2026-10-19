from datetime import datetime, timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from api.models import BankSampah, JadwalKegiatan, User


def _pengelola() -> User:
    bank = BankSampah.objects.create(nama="Bank Rentang", alamat="Depok", kota="Depok")
    return User.objects.create_user(
        email="rentang@example.test",
        nama="Pengelola",
        bank_sampah=bank,
        is_profile_complete=True,
        is_primary_pengelola=True,
    )


def _jadwal(pengelola: User, tanggal: str, jam: int = 9, lokasi: str = "Balai") -> JadwalKegiatan:
    mulai = timezone.make_aware(datetime.fromisoformat(f"{tanggal}T{jam:02d}:00:00"))
    return JadwalKegiatan.objects.create(
        bank_sampah=pengelola.bank_sampah,
        dibuat_oleh=pengelola,
        jenis_kegiatan="penimbangan",
        mulai_pada=mulai,
        selesai_pada=mulai + timedelta(hours=2),
        lokasi=lokasi,
    )


class JadwalDateRangeFilterTests(APITestCase):
    def setUp(self) -> None:
        self.pengelola = _pengelola()
        self.client.force_authenticate(self.pengelola)
        self.url = "/api/v1/jadwal"
        for tanggal in ["2026-10-18", "2026-10-19", "2026-10-23", "2026-10-31", "2026-11-02"]:
            _jadwal(self.pengelola, tanggal)

    def _tanggal(self, response) -> list[str]:
        return [item["mulai_pada"][:10] for item in response.data["results"]]

    def test_range_returns_schedules_between_both_dates_inclusive(self) -> None:
        response = self.client.get(self.url, {"date_from": "2026-10-19", "date_to": "2026-10-31"})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._tanggal(response), ["2026-10-19", "2026-10-23", "2026-10-31"])

    def test_date_from_alone_is_open_ended(self) -> None:
        response = self.client.get(self.url, {"date_from": "2026-10-23"})

        self.assertEqual(self._tanggal(response), ["2026-10-23", "2026-10-31", "2026-11-02"])

    def test_date_to_alone_is_open_at_the_start(self) -> None:
        response = self.client.get(self.url, {"date_to": "2026-10-19"})

        self.assertEqual(self._tanggal(response), ["2026-10-18", "2026-10-19"])

    def test_schedules_on_the_same_day_keep_start_time_order(self) -> None:
        _jadwal(self.pengelola, "2026-10-23", jam=7, lokasi="Pagi")

        response = self.client.get(self.url, {"date_from": "2026-10-23", "date_to": "2026-10-23"})

        self.assertEqual([item["lokasi"] for item in response.data["results"]], ["Pagi", "Balai"])

    def test_a_range_with_nothing_in_it_is_an_empty_page(self) -> None:
        response = self.client.get(self.url, {"date_from": "2027-01-01", "date_to": "2027-01-31"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])

    def test_the_exact_date_filter_still_works(self) -> None:
        response = self.client.get(self.url, {"date": "2026-10-23"})

        self.assertEqual(self._tanggal(response), ["2026-10-23"])

    def test_malformed_dates_are_rejected_by_name(self) -> None:
        for name in ("date_from", "date_to"):
            with self.subTest(name=name):
                response = self.client.get(self.url, {name: "23-10-2026"})

                self.assertEqual(response.status_code, 422)
                self.assertIn(name, response.data["errors"])

    def test_an_end_before_the_start_is_rejected(self) -> None:
        response = self.client.get(self.url, {"date_from": "2026-10-31", "date_to": "2026-10-19"})

        self.assertEqual(response.status_code, 422)
        self.assertIn("date_to", response.data["errors"])

    def test_another_banks_schedules_never_appear(self) -> None:
        lain = BankSampah.objects.create(nama="Bank Lain", alamat="Bogor", kota="Bogor")
        orang_lain = User.objects.create_user(
            email="lain@example.test",
            nama="Lain",
            bank_sampah=lain,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        _jadwal(orang_lain, "2026-10-23", lokasi="Bank Lain")

        response = self.client.get(self.url, {"date_from": "2026-10-23", "date_to": "2026-10-23"})

        self.assertEqual([item["lokasi"] for item in response.data["results"]], ["Balai"])
