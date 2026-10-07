from decimal import Decimal
from typing import Any

from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, DraftPencairan, Nasabah, Pencairan, Saldo, User

URL = "/api/v1/draft-pencairan"


class DraftPencairanTests(APITestCase):
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
        self.nasabah = self._nasabah("NAS-0001", "Ahmad Ridwan", "465600")
        self._login(self.user)

    def _login(self, user: User) -> None:
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def _nasabah(
        self, nomor: str, nama: str, saldo: str, bank: BankSampah | None = None, **extra: Any
    ) -> Nasabah:
        nasabah = Nasabah.objects.create(
            bank_sampah=bank or self.bank,
            nomor=nomor,
            nama=nama,
            email=f"{nomor.lower()}@example.com",
            no_hp=f"+6281{nomor[-4:]}00000",
            alamat="Jl. Mawar No. 12",
            **extra,
        )
        Saldo.objects.create(nasabah=nasabah, total_saldo=Decimal(saldo))
        return nasabah

    def _buat(self, items: list[dict[str, Any]], **extra: Any) -> Any:
        return self.client.post(URL, {"items": items, **extra}, format="json")

    def test_buat_draft_satu_nasabah_nominal_default_seluruh_saldo(self) -> None:
        response = self._buat([{"nasabah_id": str(self.nasabah.id)}])

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "draft")
        self.assertEqual(len(response.data["items"]), 1)
        self.assertEqual(response.data["items"][0]["nominal"], "465600.00")
        self.assertEqual(response.data["items"][0]["metode"], "tunai")
        self.assertEqual(Saldo.objects.get(nasabah=self.nasabah).total_saldo, Decimal(465600))
        self.assertFalse(Pencairan.objects.exists())

    def test_nominal_sebagian_dipakai_apa_adanya(self) -> None:
        response = self._buat([{"nasabah_id": str(self.nasabah.id), "nominal": "100000"}])

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["items"][0]["nominal"], "100000.00")

    def test_nominal_melebihi_saldo_ditolak_dan_tidak_membuat_draft(self) -> None:
        response = self._buat([{"nasabah_id": str(self.nasabah.id), "nominal": "465601"}])

        self.assertEqual(response.status_code, 422, response.data)
        self.assertIn("items[0].nominal", response.data["errors"])
        self.assertFalse(DraftPencairan.objects.exists())

    def test_nominal_nol_atau_tidak_bulat_ditolak(self) -> None:
        for nominal in ("0", "-5", "1000.50"):
            with self.subTest(nominal=nominal):
                response = self._buat([{"nasabah_id": str(self.nasabah.id), "nominal": nominal}])

                self.assertEqual(response.status_code, 422, response.data)

    def test_saldo_kosong_tanpa_nominal_ditolak(self) -> None:
        kosong = self._nasabah("NAS-0002", "Budi Kosong", "0")

        response = self._buat([{"nasabah_id": str(kosong.id)}])

        self.assertEqual(response.status_code, 422, response.data)
        self.assertIn("items[0].nominal", response.data["errors"])

    def test_potongan_persen_dibulatkan_ke_bawah_per_item_dan_total_adalah_jumlah_item(
        self,
    ) -> None:
        budi = self._nasabah("NAS-0002", "Budi Santoso", "10001")
        persen = {"potongan_jenis": "persen", "potongan_nilai": "5"}

        response = self._buat(
            [
                {"nasabah_id": str(self.nasabah.id), "nominal": "10001", **persen},
                {"nasabah_id": str(budi.id), **persen},
            ]
        )

        self.assertEqual(response.status_code, 201, response.data)
        for item in response.data["items"]:
            self.assertEqual(item["potongan"], "500.00")
            self.assertEqual(item["dibayar"], "9501.00")
        self.assertEqual(response.data["total_nominal"], "20002.00")
        self.assertEqual(response.data["total_potongan"], "1000.00")
        self.assertEqual(response.data["total_dibayar"], "19002.00")

    def test_potongan_rupiah_dipotong_dari_nominal(self) -> None:
        response = self._buat(
            [
                {
                    "nasabah_id": str(self.nasabah.id),
                    "nominal": "100000",
                    "potongan_jenis": "rupiah",
                    "potongan_nilai": "2500",
                }
            ]
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["items"][0]["potongan"], "2500.00")
        self.assertEqual(response.data["items"][0]["dibayar"], "97500.00")

    def test_potongan_tidak_valid_ditolak(self) -> None:
        kasus = {
            "rupiah melebihi nominal": ("rupiah", "100001"),
            "persen lebih dari 100": ("persen", "100.5"),
            "nilai negatif": ("rupiah", "-1"),
            "rupiah pecahan": ("rupiah", "10.5"),
        }
        for nama, (jenis, nilai) in kasus.items():
            with self.subTest(nama):
                response = self._buat(
                    [
                        {
                            "nasabah_id": str(self.nasabah.id),
                            "nominal": "100000",
                            "potongan_jenis": jenis,
                            "potongan_nilai": nilai,
                        }
                    ]
                )

                self.assertEqual(response.status_code, 422, response.data)
                self.assertFalse(DraftPencairan.objects.exists())

    def test_jenis_potongan_tanpa_nilai_ditolak(self) -> None:
        response = self._buat([{"nasabah_id": str(self.nasabah.id), "potongan_jenis": "persen"}])

        self.assertEqual(response.status_code, 422, response.data)
