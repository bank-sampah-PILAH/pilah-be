from decimal import Decimal
from typing import Any

from rest_framework.response import Response
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, Nasabah, Saldo, User


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
