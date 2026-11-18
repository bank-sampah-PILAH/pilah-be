"""Beranda summary tests (PIL-333): a three-item cap, the unread count over
the whole set, and the same visibility and scoping rules as the full list.
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, Pengumuman, PengumumanDibaca, User

URL = "/api/v1/nasabah/me/pengumuman/beranda"


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


class NasabahPengumumanBerandaTests(APITestCase):
    def setUp(self) -> None:
        self.bank = _bank()
        self.pengelola = _pengelola(self.bank, "pengelola@example.test")
        self.nasabah = _nasabah_user(self.bank, "nasabah@example.test", "NAS-0001")
        self.client.force_authenticate(self.nasabah)

    def test_caps_at_the_three_latest_in_terbit_order(self) -> None:
        for usia in (7, 5, 3, 1):
            _terbit(self.bank, self.pengelola, f"Pengumuman {usia}j", usia_jam=usia)

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["judul"] for item in response.data["items"]],
            ["Pengumuman 1j", "Pengumuman 3j", "Pengumuman 5j"],
        )
        self.assertEqual(response.data["unread_count"], 4)

    def test_unread_count_covers_all_active_not_just_the_three(self) -> None:
        for usia in (7, 5, 3, 1):
            _terbit(self.bank, self.pengelola, f"Pengumuman {usia}j", usia_jam=usia)
        terbaru = Pengumuman.objects.get(judul="Pengumuman 1j")
        PengumumanDibaca.objects.create(pengumuman=terbaru, user=self.nasabah)

        response = self.client.get(URL)

        self.assertEqual(response.data["unread_count"], 3)
        dibaca = [item for item in response.data["items"] if item["judul"] == "Pengumuman 1j"][0]
        self.assertTrue(dibaca["dibaca"])

    def test_visibility_rule_matches_the_full_list(self) -> None:
        _terbit(self.bank, self.pengelola, "Tetap tampil")
        # Draft: not visible either way.
        Pengumuman.objects.create(
            bank_sampah=self.bank, judul="Draft", isi=".", dibuat_oleh=self.pengelola
        )
        # Scheduled whose publish time has not arrived.
        Pengumuman.objects.create(
            bank_sampah=self.bank,
            judul="Belum saatnya",
            isi=".",
            status=Pengumuman.Status.TERBIT,
            terbit_pada=timezone.now() + timedelta(days=2),
            dibuat_oleh=self.pengelola,
        )
        # Withdrawn.
        Pengumuman.objects.create(
            bank_sampah=self.bank,
            judul="Ditarik",
            isi=".",
            status=Pengumuman.Status.DITARIK,
            terbit_pada=timezone.now() - timedelta(days=1),
            ditarik_oleh=self.pengelola,
            ditarik_pada=timezone.now(),
            dibuat_oleh=self.pengelola,
        )
        # Expired.
        Pengumuman.objects.create(
            bank_sampah=self.bank,
            judul="Kedaluwarsa",
            isi=".",
            status=Pengumuman.Status.TERBIT,
            terbit_pada=timezone.now() - timedelta(hours=2),
            masa_berlaku_hingga=timezone.now() - timedelta(hours=1),
            dibuat_oleh=self.pengelola,
        )

        response = self.client.get(URL)

        self.assertEqual([item["judul"] for item in response.data["items"]], ["Tetap tampil"])
        self.assertEqual(response.data["unread_count"], 1)

    def test_scoped_to_other_banks(self) -> None:
        lain = _bank("Bank Lain")
        other_pengelola = _pengelola(lain, "pengelola-lain@example.test")
        _terbit(lain, other_pengelola, "Punya bank lain")

        response = self.client.get(URL)

        self.assertEqual(response.data["items"], [])
        self.assertEqual(response.data["unread_count"], 0)
