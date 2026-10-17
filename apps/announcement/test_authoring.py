"""Authoring tests for Pengumuman (PIL-243): ownership, derived status, and
publish-schedule validation.
"""

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, Pengumuman, User

URL = "/api/v1/pengumuman"


def _bank_with_pengelola(nama: str = "Bank Pengumuman") -> tuple[BankSampah, User]:
    bank = BankSampah.objects.create(nama=nama, alamat="Depok", kota="Depok")
    pengelola = User.objects.create_user(
        email=f"{nama.replace(' ', '').lower()}@example.test",
        nama="Pengelola",
        bank_sampah=bank,
        is_profile_complete=True,
        is_primary_pengelola=True,
    )
    return bank, pengelola


def _draft(bank: BankSampah, oleh: User, judul: str = "Kerja bakti") -> Pengumuman:
    return Pengumuman.objects.create(
        bank_sampah=bank, judul=judul, isi="Isi pengumuman.", dibuat_oleh=oleh
    )


class PengumumanAuthoringTests(APITestCase):
    def setUp(self) -> None:
        self.bank, self.pengelola = _bank_with_pengelola()
        self.client.force_authenticate(self.pengelola)

    def test_create_uses_the_callers_bank_and_never_the_input(self) -> None:
        other_bank, _ = _bank_with_pengelola("Bank Lain")

        response = self.client.post(
            URL,
            {"judul": "Pengumuman", "isi": "Isi.", "bank_sampah_id": str(other_bank.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["bank_sampah_id"], str(self.bank.id))
        self.assertEqual(response.data["status"], "draft")
        self.assertEqual(response.data["dibuat_oleh_id"], str(self.pengelola.id))

    def test_creating_a_draft_with_a_past_publish_time_is_rejected(self) -> None:
        response = self.client.post(
            URL,
            {
                "judul": "Pengumuman",
                "isi": "Isi.",
                "terbit_pada": (timezone.now() - timedelta(hours=1)).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 422, response.data)
        self.assertIn("terbit_pada", response.data["errors"])

    def test_creating_a_draft_with_expiry_before_publish_time_is_rejected(self) -> None:
        nanti = timezone.now() + timedelta(days=3)
        response = self.client.post(
            URL,
            {
                "judul": "Pengumuman",
                "isi": "Isi.",
                "terbit_pada": nanti.isoformat(),
                "masa_berlaku_hingga": (nanti - timedelta(days=1)).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 422, response.data)
        self.assertIn("masa_berlaku_hingga", response.data["errors"])

    def test_created_draft_is_not_visible_via_aktif(self) -> None:
        created = self.client.post(URL, {"judul": "Pengumuman", "isi": "Isi."}, format="json")
        self.assertEqual(created.status_code, 201, created.data)

        self.assertFalse(Pengumuman.aktif().exists())

    def test_list_shows_only_own_bank(self) -> None:
        other_bank, other_pengelola = _bank_with_pengelola("Bank Lain")
        _draft(self.bank, self.pengelola, "Punya saya")
        _draft(other_bank, other_pengelola, "Punya orang lain")

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["judul"] for item in response.data["results"]], ["Punya saya"])

    def test_unknown_status_filter_is_rejected(self) -> None:
        response = self.client.get(URL, {"status": "aneh"})

        self.assertEqual(response.status_code, 422)
        self.assertIn("status", response.data["errors"])

    def test_delete_only_allows_draft(self) -> None:
        created = self.client.post(URL, {"judul": "Pengumuman", "isi": "Isi."}, format="json")
        pengumuman_id = created.data["id"]

        deleted = self.client.delete(f"{URL}/{pengumuman_id}")
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(Pengumuman.objects.filter(pk=pengumuman_id).exists())


class PengumumanDerivedStatusTests(APITestCase):
    def setUp(self) -> None:
        self.bank, self.pengelola = _bank_with_pengelola()
        self.client.force_authenticate(self.pengelola)

    def _terbitkan(self, pengumuman_id: str, terbit_pada: str | datetime | None = None) -> Response:
        payload: dict[str, Any] = {}
        if terbit_pada is not None:
            payload["terbit_pada"] = (
                terbit_pada.isoformat() if isinstance(terbit_pada, datetime) else terbit_pada
            )
        return self.client.post(f"{URL}/{pengumuman_id}/terbitkan", payload, format="json")

    def test_publish_now_becomes_terbit(self) -> None:
        created = self.client.post(URL, {"judul": "Pengumuman", "isi": "Isi."}, format="json")
        pengumuman_id = created.data["id"]

        response = self._terbitkan(pengumuman_id)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "terbit")
        self.assertEqual(response.data["diterbitkan_oleh_id"], str(self.pengelola.id))
        self.assertIsNotNone(response.data["terbit_pada"])

    def test_future_publish_time_is_terjadwal(self) -> None:
        created = self.client.post(URL, {"judul": "Pengumuman", "isi": "Isi."}, format="json")
        pengumuman_id = created.data["id"]
        nanti = timezone.now() + timedelta(days=3)

        response = self._terbitkan(pengumuman_id, nanti)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "terjadwal")
        self.assertEqual(datetime.fromisoformat(str(response.data["terbit_pada"])), nanti)

    def test_past_expiry_becomes_kedaluwarsa(self) -> None:
        created = self.client.post(URL, {"judul": "Pengumuman", "isi": "Isi."}, format="json")
        pengumuman_id = created.data["id"]
        response = self._terbitkan(pengumuman_id)
        self.assertEqual(response.status_code, 200, response.data)
        # kedaluwarsa is derived at query time: force the times backwards.
        Pengumuman.objects.filter(pk=pengumuman_id).update(
            terbit_pada=timezone.now() - timedelta(hours=2),
            masa_berlaku_hingga=timezone.now() - timedelta(hours=1),
        )

        detail = self.client.get(f"{URL}/{pengumuman_id}")

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["status"], "kedaluwarsa")
        self.assertFalse(Pengumuman.aktif().filter(pk=pengumuman_id).exists())

    def test_publishing_a_past_schedule_time_is_rejected(self) -> None:
        created = self.client.post(URL, {"judul": "Pengumuman", "isi": "Isi."}, format="json")
        pengumuman_id = created.data["id"]
        lampau = (timezone.now() - timedelta(hours=1)).isoformat()

        response = self._terbitkan(pengumuman_id, lampau)

        self.assertEqual(response.status_code, 422)
        self.assertIn("terbit_pada", response.data["errors"])

    def test_expiry_before_publish_time_is_rejected(self) -> None:
        created = self.client.post(URL, {"judul": "Pengumuman", "isi": "Isi."}, format="json")
        pengumuman_id = created.data["id"]
        nanti = timezone.now() + timedelta(days=3)

        response = self.client.post(
            f"{URL}/{pengumuman_id}/terbitkan",
            {
                "terbit_pada": nanti.isoformat(),
                "masa_berlaku_hingga": (nanti - timedelta(days=1)).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("masa_berlaku_hingga", response.data["errors"])

    def test_withdrawing_publish_makes_it_ditarik_and_invisible(self) -> None:
        created = self.client.post(URL, {"judul": "Pengumuman", "isi": "Isi."}, format="json")
        pengumuman_id = created.data["id"]
        self._terbitkan(pengumuman_id)

        response = self.client.post(f"{URL}/{pengumuman_id}/tarik")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "ditarik")
        self.assertEqual(response.data["ditarik_oleh_id"], str(self.pengelola.id))
        self.assertIsNotNone(response.data["ditarik_pada"])
        self.assertFalse(Pengumuman.aktif().filter(pk=pengumuman_id).exists())

    def test_publishing_twice_is_rejected(self) -> None:
        created = self.client.post(URL, {"judul": "Pengumuman", "isi": "Isi."}, format="json")
        pengumuman_id = created.data["id"]
        self._terbitkan(pengumuman_id)

        response = self._terbitkan(pengumuman_id)

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.data)

    def test_withdrawing_a_draft_is_rejected(self) -> None:
        created = self.client.post(URL, {"judul": "Pengumuman", "isi": "Isi."}, format="json")
        pengumuman_id = created.data["id"]

        response = self.client.post(f"{URL}/{pengumuman_id}/tarik")

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.data)

    def test_editing_a_published_announcement_is_rejected(self) -> None:
        created = self.client.post(URL, {"judul": "Pengumuman", "isi": "Isi."}, format="json")
        pengumuman_id = created.data["id"]
        self._terbitkan(pengumuman_id)

        response = self.client.patch(f"{URL}/{pengumuman_id}", {"judul": "Baru"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.data)

    def test_editing_a_scheduled_announcement_is_allowed(self) -> None:
        created = self.client.post(URL, {"judul": "Pengumuman", "isi": "Isi."}, format="json")
        pengumuman_id = created.data["id"]
        self._terbitkan(pengumuman_id, (timezone.now() + timedelta(days=3)).isoformat())

        response = self.client.patch(
            f"{URL}/{pengumuman_id}", {"judul": "Judul Baru"}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["judul"], "Judul Baru")

    def test_canceling_a_schedule_returns_to_draft(self) -> None:
        created = self.client.post(URL, {"judul": "Pengumuman", "isi": "Isi."}, format="json")
        pengumuman_id = created.data["id"]
        self._terbitkan(pengumuman_id, (timezone.now() + timedelta(days=3)).isoformat())

        response = self.client.patch(f"{URL}/{pengumuman_id}", {"terbit_pada": None}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "draft")
        self.assertIsNone(response.data["terbit_pada"])


class PengumumanAccessTests(APITestCase):
    def test_nasabah_role_cannot_author(self) -> None:
        bank, _ = _bank_with_pengelola()
        nasabah_user = User.objects.create_user(
            email="nasabah@example.test", nama="Nasabah", role=User.Role.NASABAH
        )
        Nasabah.objects.create(
            bank_sampah=bank,
            nomor="NAS-0001",
            nama="Nasabah",
            no_hp="+628111111111",
            alamat="Jl. A",
            user=nasabah_user,
            status=Nasabah.Status.APPROVED,
            is_active=True,
        )
        self.client.force_authenticate(nasabah_user)

        response = self.client.post(URL, {"judul": "Pengumuman", "isi": "Isi."}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_cross_bank_pengelola_cannot_reach_other_bank_rows(self) -> None:
        bank, pengelola = _bank_with_pengelola()
        other_bank, other_pengelola = _bank_with_pengelola("Bank Lain")
        pengumuman = _draft(bank, pengelola)
        self.client.force_authenticate(other_pengelola)

        detail = self.client.get(f"{URL}/{pengumuman.id}")
        deleted = self.client.delete(f"{URL}/{pengumuman.id}")

        self.assertEqual(detail.status_code, 404)
        self.assertEqual(deleted.status_code, 404)
