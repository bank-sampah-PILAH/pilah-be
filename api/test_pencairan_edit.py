from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, JenisSampah, Nasabah, Saldo, User


class PencairanEditTests(APITestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(
            nama="Bank Sampah BTH",
            alamat="Depok",
            kota="Depok",
            no_hp_pic="+628123456789",
            status=BankSampah.Status.ACTIVE,
        )
        self.user = User.objects.create_user(
            email="sari@example.com",
            nama="Ibu Sari",
            bank_sampah=self.bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        self.nasabah = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-0001",
            nama="Ahmad Ridwan",
            no_hp="+628123456789",
            alamat="Jl. Mawar No. 12",
        )
        Saldo.objects.create(nasabah=self.nasabah, total_saldo=Decimal("465600.00"))
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def _catat(self, nominal: str = "200000", **extra: Any) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/pencairan",
            {"nasabah_id": str(self.nasabah.id), "nominal": nominal, "metode": "tunai", **extra},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return dict(response.data)

    def _edit(self, pencairan_id: str, payload: dict[str, Any]) -> Response:
        return self.client.patch(f"/api/v1/pencairan/{pencairan_id}", payload, format="json")

    def test_edit_metode_and_keterangan_marks_pencairan_diperbarui(self) -> None:
        pencairan = self._catat(keterangan="Diambil pagi")
        self.assertFalse(pencairan["diperbarui"])

        response = self._edit(
            pencairan["id"],
            {
                "metode": "transfer",
                "keterangan": "Ditransfer ke BRI",
                "alasan": "Salah pilih metode",
            },
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["metode"], "transfer")
        self.assertEqual(response.data["keterangan"], "Ditransfer ke BRI")
        self.assertEqual(response.data["nominal"], "200000.00")
        self.assertTrue(response.data["diperbarui"])
        detail = self.client.get(f"/api/v1/pencairan/{pencairan['id']}")
        self.assertTrue(detail.data["diperbarui"])

    def test_edit_requires_alasan(self) -> None:
        pencairan = self._catat()

        for payload in ({}, {"alasan": ""}, {"alasan": "   "}):
            with self.subTest(payload=payload):
                response = self._edit(pencairan["id"], {"metode": "transfer", **payload})

                self.assertEqual(response.status_code, 422, response.data)
                self.assertEqual(
                    response.data["errors"]["alasan"], ["Alasan perubahan wajib diisi"]
                )
        detail = self.client.get(f"/api/v1/pencairan/{pencairan['id']}")
        self.assertEqual(detail.data["metode"], "tunai")
        self.assertFalse(detail.data["diperbarui"])

    def _saldo(self) -> str:
        return str(self.client.get(f"/api/v1/nasabah/{self.nasabah.id}/saldo").data["total_saldo"])

    def test_edit_nominal_adjusts_saldo_and_snapshot(self) -> None:
        pencairan = self._catat("200000")
        self.assertEqual(self._saldo(), "265600.00")

        response = self._edit(pencairan["id"], {"nominal": "150000", "alasan": "Salah ketik"})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["nominal"], "150000.00")
        self.assertEqual(response.data["saldo_sebelum"], "465600.00")
        self.assertEqual(response.data["saldo_sesudah"], "315600.00")
        self.assertEqual(self._saldo(), "315600.00")

    def _setor(self, harga: str = "100000.00", berat: str = "1.000") -> None:
        jenis, _ = JenisSampah.objects.get_or_create(
            bank_sampah=self.bank,
            nomor="PLS-001",
            defaults={
                "nama_sampah": "Plastik PET",
                "kategori": JenisSampah.Kategori.PLASTIK,
                "harga_per_kg": Decimal(harga),
            },
        )
        response = self.client.post(
            "/api/v1/transaksi",
            {
                "nasabah_id": str(self.nasabah.id),
                "items": [{"jenis_sampah_id": str(jenis.id), "berat": berat}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def _detail(self, pencairan_id: str) -> dict[str, Any]:
        return dict(self.client.get(f"/api/v1/pencairan/{pencairan_id}").data)

    def test_edit_recomputes_later_pencairan_snapshots(self) -> None:
        pertama = self._catat("200000", tanggal=(timezone.now() - timedelta(hours=2)).isoformat())
        self._setor()
        kedua = self._catat("50000")
        self.assertEqual(self._detail(kedua["id"])["saldo_sebelum"], "365600.00")

        response = self._edit(pertama["id"], {"nominal": "150000", "alasan": "Salah ketik"})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["saldo_sesudah"], "315600.00")
        later = self._detail(kedua["id"])
        self.assertEqual(later["saldo_sebelum"], "415600.00")
        self.assertEqual(later["saldo_sesudah"], "365600.00")
        # Recomputing a later snapshot is not an edit of that pencairan.
        self.assertFalse(later["diperbarui"])
        self.assertEqual(self._saldo(), "365600.00")

    def test_edit_rejects_nominal_that_overdraws_a_later_pencairan(self) -> None:
        now = timezone.now()
        pertama = self._catat("200000", tanggal=(now - timedelta(hours=2)).isoformat())
        kedua = self._catat("250000", tanggal=(now - timedelta(hours=1)).isoformat())
        self._setor()
        # Today's saldo (Rp 115.600) would cover +Rp 20.000, but the second pencairan
        # would then be paid from Rp 245.600 < Rp 250.000.
        self.assertEqual(self._saldo(), "115600.00")

        response = self._edit(pertama["id"], {"nominal": "220000", "alasan": "Salah ketik"})

        self.assertEqual(response.status_code, 422, response.data)
        self.assertEqual(
            response.data["errors"]["nominal"],
            ["Saldo nasabah tidak mencukupi untuk perubahan ini"],
        )
        self.assertEqual(self._saldo(), "115600.00")
        self.assertEqual(self._detail(pertama["id"])["nominal"], "200000.00")
        self.assertFalse(self._detail(pertama["id"])["diperbarui"])
        self.assertEqual(self._detail(kedua["id"])["saldo_sebelum"], "265600.00")
