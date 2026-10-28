"""Pengurus manage-surface tests (PIL-332): the derived-status filter buckets
and the draft-only delete rule on rows that already left draft.
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from api.models import BankSampah, Pengumuman, User

URL = "/api/v1/pengumuman"


def _pengelola(nama: str = "Bank Pengumuman") -> tuple[BankSampah, User]:
    bank = BankSampah.objects.create(nama=nama, alamat="Depok", kota="Depok")
    pengelola = User.objects.create_user(
        email=f"{nama.replace(' ', '').lower()}@example.test",
        nama="Pengelola",
        bank_sampah=bank,
        is_profile_complete=True,
        is_primary_pengelola=True,
    )
    return bank, pengelola


class PengumumanStatusFilterTests(APITestCase):
    def setUp(self) -> None:
        self.bank, self.pengelola = _pengelola()
        self.client.force_authenticate(self.pengelola)
        self.rows: dict[str, Pengumuman] = {}

        def row(judul: str) -> Pengumuman:
            return Pengumuman.objects.create(
                bank_sampah=self.bank,
                judul=judul,
                isi="Isi pengumuman.",
                dibuat_oleh=self.pengelola,
            )

        # One row per effective status, forced via update() because kedaluwarsa
        # and terjadwal are derived at query time, not persisted.
        draft = row("Masih konsep")
        self.rows["draft"] = draft

        terjadwal = row("Menunggu jadwal")
        Pengumuman.objects.filter(pk=terjadwal.pk).update(
            status=Pengumuman.Status.TERBIT,
            terbit_pada=timezone.now() + timedelta(days=3),
            diterbitkan_oleh=self.pengelola,
        )
        self.rows["terjadwal"] = terjadwal

        terbit = row("Sedang berjalan")
        Pengumuman.objects.filter(pk=terbit.pk).update(
            status=Pengumuman.Status.TERBIT,
            terbit_pada=timezone.now(),
            diterbitkan_oleh=self.pengelola,
        )
        self.rows["terbit"] = terbit

        kedaluwarsa = row("Sudah berlalu")
        Pengumuman.objects.filter(pk=kedaluwarsa.pk).update(
            status=Pengumuman.Status.TERBIT,
            terbit_pada=timezone.now() - timedelta(hours=2),
            masa_berlaku_hingga=timezone.now() - timedelta(hours=1),
            diterbitkan_oleh=self.pengelola,
        )
        self.rows["kedaluwarsa"] = kedaluwarsa

        ditarik = row("Sudah ditarik")
        Pengumuman.objects.filter(pk=ditarik.pk).update(
            status=Pengumuman.Status.DITARIK,
            terbit_pada=timezone.now() - timedelta(days=1),
            ditarik_oleh=self.pengelola,
            ditarik_pada=timezone.now(),
        )
        self.rows["ditarik"] = ditarik

    def test_list_without_a_filter_shows_all_rows(self) -> None:
        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 5)

    def test_each_status_bucket_returns_its_own_row(self) -> None:
        for nama, pengumuman in self.rows.items():
            with self.subTest(status=nama):
                response = self.client.get(URL, {"status": nama})

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [item["judul"] for item in response.data["results"]],
                    [pengumuman.judul],
                )

    def test_kedaluwarsa_is_not_glued_onto_terbit(self) -> None:
        # A past-masa_berlaku row is a terbit row in the database, so the filter
        # must rely on the annotation, not on the persisted status.
        terbit_response = self.client.get(URL, {"status": "terbit"})
        self.assertEqual(
            [item["judul"] for item in terbit_response.data["results"]],
            ["Sedang berjalan"],
        )

    def test_published_and_withdrawn_rows_cannot_be_deleted(self) -> None:
        for status in ("terbit", "ditarik"):
            with self.subTest(status=status):
                response = self.client.delete(f"{URL}/{self.rows[status].id}")

                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.data)
                self.assertTrue(Pengumuman.objects.filter(pk=self.rows[status].pk).exists())
