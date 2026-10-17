"""Nasabah-facing pengumuman endpoint tests (PIL-244): visibility rule,
cross-bank isolation, and read receipts.
"""

from datetime import timedelta
from typing import Any

from django.utils import timezone
from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, Pengumuman, PengumumanDibaca, User

LIST_URL = "/api/v1/nasabah/me/pengumuman"


def _bank(nama: str = "Bank Pengumuman") -> BankSampah:
    return BankSampah.objects.create(nama=nama, alamat="Depok", kota="Depok")


def _pengelola(bank: BankSampah, email: str) -> User:
    return User.objects.create_user(
        email=email,
        nama="Pengelola",
        bank_sampah=bank,
        is_profile_complete=True,
        is_primary_pengelola=True,
    )


def _nasabah_user(bank: BankSampah, email: str, nomor: str, no_hp: str = "+628111111111") -> User:
    user = User.objects.create_user(email=email, nama="Nasabah", role=User.Role.NASABAH)
    Nasabah.objects.create(
        bank_sampah=bank,
        nomor=nomor,
        nama="Nasabah",
        no_hp=no_hp,
        alamat="Jl. A",
        email=email,
        user=user,
        status=Nasabah.Status.APPROVED,
        is_active=True,
    )
    return user


def _terbit(bank: BankSampah, oleh: User, judul: str, *, usia_jam: int = 1) -> Pengumuman:
    now = timezone.now()
    return Pengumuman.objects.create(
        bank_sampah=bank,
        judul=judul,
        isi="Isi pengumuman.",
        status=Pengumuman.Status.TERBIT,
        terbit_pada=now - timedelta(hours=usia_jam),
        dibuat_oleh=oleh,
        diterbitkan_oleh=oleh,
    )


class NasabahPengumumanListTests(APITestCase):
    def setUp(self) -> None:
        self.bank = _bank()
        self.pengelola = _pengelola(self.bank, "pengelola@example.test")
        self.nasabah = _nasabah_user(self.bank, "nasabah@example.test", "NAS-0001")
        self.client.force_authenticate(self.nasabah)

    def test_lists_only_active_announcements_of_own_bank(self) -> None:
        _terbit(self.bank, self.pengelola, "Aktif")
        # Scheduled whose publish time has not arrived.
        Pengumuman.objects.create(
            bank_sampah=self.bank,
            judul="Belum terbit",
            isi=".",
            status=Pengumuman.Status.TERBIT,
            terbit_pada=timezone.now() + timedelta(days=2),
            dibuat_oleh=self.pengelola,
            diterbitkan_oleh=self.pengelola,
        )
        # Expired.
        kedaluwarsa = _terbit(self.bank, self.pengelola, "Kedaluwarsa", usia_jam=48)
        Pengumuman.objects.filter(pk=kedaluwarsa.pk).update(
            masa_berlaku_hingga=timezone.now() - timedelta(hours=24)
        )
        # Withdrawn.
        ditarik = _terbit(self.bank, self.pengelola, "Ditarik")
        Pengumuman.objects.filter(pk=ditarik.pk).update(
            status=Pengumuman.Status.DITARIK, ditarik_pada=timezone.now()
        )
        # A plain draft.
        Pengumuman.objects.create(
            bank_sampah=self.bank, judul="Draft", isi=".", dibuat_oleh=self.pengelola
        )
        # Another bank's active announcement.
        other_bank = _bank("Bank Lain")
        other_pengelola = _pengelola(other_bank, "pengelola2@example.test")
        _terbit(other_bank, other_pengelola, "Bank lain")

        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["judul"] for row in response.data["results"]], ["Aktif"])

    def test_read_flag_and_timestamp_follow_the_receipt(self) -> None:
        pengumuman = _terbit(self.bank, self.pengelola, "Aktif")
        PengumumanDibaca.objects.create(pengumuman=pengumuman, user=self.nasabah)

        response = self.client.get(LIST_URL)

        row = response.data["results"][0]
        self.assertTrue(row["dibaca"])
        self.assertIsNotNone(row["dibaca_pada"])

    def test_requires_an_active_membership(self) -> None:
        Nasabah.objects.filter(user=self.nasabah).update(is_active=False)

        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, 403)


class NasabahPengumumanDetailTests(APITestCase):
    def setUp(self) -> None:
        self.bank = _bank()
        self.pengelola = _pengelola(self.bank, "pengelola@example.test")
        self.nasabah = _nasabah_user(self.bank, "nasabah@example.test", "NAS-0001")
        self.client.force_authenticate(self.nasabah)

    def test_detail_of_own_bank_announcement_is_visible(self) -> None:
        pengumuman = _terbit(self.bank, self.pengelola, "Aktif")

        response = self.client.get(f"{LIST_URL}/{pengumuman.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["judul"], "Aktif")

    def test_detail_of_another_bank_is_404(self) -> None:
        other_bank = _bank("Bank Lain")
        other_pengelola = _pengelola(other_bank, "pengelola2@example.test")
        pengumuman = _terbit(other_bank, other_pengelola, "Bank lain")

        response = self.client.get(f"{LIST_URL}/{pengumuman.id}")

        self.assertEqual(response.status_code, 404)

    def test_detail_of_expired_or_withdrawn_is_404(self) -> None:
        kedaluwarsa = _terbit(self.bank, self.pengelola, "Kedaluwarsa", usia_jam=48)
        Pengumuman.objects.filter(pk=kedaluwarsa.pk).update(
            masa_berlaku_hingga=timezone.now() - timedelta(hours=24)
        )
        ditarik = _terbit(self.bank, self.pengelola, "Ditarik")
        Pengumuman.objects.filter(pk=ditarik.pk).update(
            status=Pengumuman.Status.DITARIK, ditarik_pada=timezone.now()
        )

        self.assertEqual(self.client.get(f"{LIST_URL}/{kedaluwarsa.id}").status_code, 404)
        self.assertEqual(self.client.get(f"{LIST_URL}/{ditarik.id}").status_code, 404)


class NasabahPengumumanBacaTests(APITestCase):
    def setUp(self) -> None:
        self.bank = _bank()
        self.pengelola = _pengelola(self.bank, "pengelola@example.test")
        self.nasabah = _nasabah_user(self.bank, "nasabah@example.test", "NAS-0001")
        self.client.force_authenticate(self.nasabah)
        self.pengumuman = _terbit(self.bank, self.pengelola, "Aktif")

    def _baca(self) -> dict[str, Any]:
        response = self.client.post(f"{LIST_URL}/{self.pengumuman.id}/baca")
        self.assertEqual(response.status_code, 200, response.data)
        return dict(response.data)

    def test_marking_read_creates_a_single_receipt(self) -> None:
        first = self._baca()
        second = self._baca()

        self.assertTrue(first["dibaca"])
        self.assertTrue(second["dibaca"])
        self.assertEqual(PengumumanDibaca.objects.count(), 1)
        self.assertEqual(first["dibaca_pada"], second["dibaca_pada"])

    def test_receipts_are_per_user(self) -> None:
        other_user = _nasabah_user(
            self.bank, "nasabah2@example.test", "NAS-0002", no_hp="+628122222222"
        )
        self._baca()
        self.client.force_authenticate(other_user)
        response = self.client.get(LIST_URL)

        self.assertFalse(response.data["results"][0]["dibaca"])
