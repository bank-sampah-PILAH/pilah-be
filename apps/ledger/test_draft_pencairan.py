from decimal import Decimal
from typing import Any

from django.utils import timezone
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

    def test_potongan_item_menimpa_default_draft(self) -> None:
        budi = self._nasabah("NAS-0002", "Budi Santoso", "200000")
        citra = self._nasabah("NAS-0003", "Citra Dewi", "200000")

        response = self._buat(
            [
                {"nasabah_id": str(self.nasabah.id), "nominal": "100000"},
                {
                    "nasabah_id": str(budi.id),
                    "potongan_jenis": "rupiah",
                    "potongan_nilai": "1000",
                },
                {"nasabah_id": str(citra.id), "potongan_jenis": "persen", "potongan_nilai": "0"},
            ],
            potongan_jenis="persen",
            potongan_nilai="10",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["potongan_jenis"], "persen")
        self.assertEqual(response.data["potongan_nilai"], "10.00")
        potongan = {item["nasabah_nama"]: item["potongan"] for item in response.data["items"]}
        self.assertEqual(
            potongan,
            {"Ahmad Ridwan": "10000.00", "Budi Santoso": "1000.00", "Citra Dewi": "0.00"},
        )
        self.assertEqual(response.data["total_potongan"], "11000.00")

    def test_default_potongan_rupiah_melebihi_nominal_salah_satu_item_ditolak(self) -> None:
        kecil = self._nasabah("NAS-0002", "Budi Kecil", "5000")

        response = self._buat(
            [
                {"nasabah_id": str(self.nasabah.id), "nominal": "100000"},
                {"nasabah_id": str(kecil.id)},
            ],
            potongan_jenis="rupiah",
            potongan_nilai="6000",
        )

        self.assertEqual(response.status_code, 422, response.data)
        self.assertIn("items[1].potongan_nilai", response.data["errors"])
        self.assertFalse(DraftPencairan.objects.exists())

    def test_default_potongan_tidak_valid_ditolak(self) -> None:
        response = self._buat(
            [{"nasabah_id": str(self.nasabah.id)}], potongan_jenis="persen", potongan_nilai="101"
        )

        self.assertEqual(response.status_code, 422, response.data)

    def test_galat_item_memakai_urutan_permintaan_bukan_urutan_nama(self) -> None:
        kecil = self._nasabah("NAS-0002", "Zed Kecil", "5000")

        response = self._buat(
            [
                {"nasabah_id": str(kecil.id)},
                {"nasabah_id": str(self.nasabah.id), "nominal": "100000"},
            ],
            potongan_jenis="rupiah",
            potongan_nilai="6000",
        )

        self.assertEqual(response.status_code, 422, response.data)
        self.assertEqual(list(response.data["errors"]), ["items[0].potongan_nilai"])

    def test_nasabah_tidak_memenuhi_syarat_ditolak(self) -> None:
        nonaktif = self._nasabah("NAS-0002", "Budi Nonaktif", "50000", is_active=False)
        menunggu = self._nasabah(
            "NAS-0003", "Citra Menunggu", "50000", status=Nasabah.Status.PENDING
        )
        bank_lain = BankSampah.objects.create(
            nama="Bank Lain",
            alamat="Bogor",
            kota="Bogor",
            no_hp_pic="+628111111111",
            status=BankSampah.Status.ACTIVE,
        )
        asing = self._nasabah("NAS-0004", "Dewi Asing", "50000", bank=bank_lain)

        for nasabah_id in (
            nonaktif.id,
            menunggu.id,
            asing.id,
            "5b2c8a54-0000-4000-8000-000000000000",
        ):
            with self.subTest(nasabah_id=str(nasabah_id)):
                response = self._buat([{"nasabah_id": str(nasabah_id)}])

                self.assertEqual(response.status_code, 422, response.data)
                self.assertIn("items[0].nasabah_id", response.data["errors"])
        self.assertFalse(DraftPencairan.objects.exists())

    def test_draft_berisi_banyak_nasabah_dan_nasabah_ganda_ditolak(self) -> None:
        budi = self._nasabah("NAS-0002", "Budi Santoso", "50000")

        response = self._buat([{"nasabah_id": str(self.nasabah.id)}, {"nasabah_id": str(budi.id)}])

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["total_nominal"], "515600.00")
        duplikat = self._buat([{"nasabah_id": str(budi.id)}, {"nasabah_id": str(budi.id)}])
        self.assertEqual(duplikat.status_code, 422, duplikat.data)
        self.assertEqual(DraftPencairan.objects.count(), 1)

    def _draft_bank_lain(self) -> DraftPencairan:
        bank_lain = BankSampah.objects.create(
            nama="Bank Lain",
            alamat="Bogor",
            kota="Bogor",
            no_hp_pic="+628111111111",
            status=BankSampah.Status.ACTIVE,
        )
        pengurus = User.objects.create_user(
            email="lain@example.com",
            nama="Pak Lain",
            bank_sampah=bank_lain,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        return DraftPencairan.objects.create(
            bank_sampah=bank_lain, dibuat_oleh=pengurus, diubah_oleh=pengurus
        )

    def test_daftar_dan_detail_hanya_draft_bank_sendiri(self) -> None:
        sendiri = self._buat([{"nasabah_id": str(self.nasabah.id)}]).data["id"]
        asing = self._draft_bank_lain()

        daftar = self.client.get(URL)
        detail = self.client.get(f"{URL}/{sendiri}")
        detail_asing = self.client.get(f"{URL}/{asing.id}")

        self.assertEqual(daftar.status_code, 200, daftar.data)
        self.assertEqual([draft["id"] for draft in daftar.data["results"]], [sendiri])
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["items"][0]["nasabah_nama"], "Ahmad Ridwan")
        self.assertEqual(detail.data["total_dibayar"], "465600.00")
        self.assertEqual(detail_asing.status_code, 404)

    def test_daftar_draft_memuat_ringkasan_tanpa_rincian_item(self) -> None:
        self._buat([{"nasabah_id": str(self.nasabah.id)}])

        draft = self.client.get(URL).data["results"][0]

        self.assertEqual(draft["jumlah_item"], 1)
        self.assertEqual(draft["total_dibayar"], "465600.00")
        self.assertNotIn("items", draft)

    def test_nama_default_otomatis_dan_bisa_diberi_nama(self) -> None:
        bulan = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
        hari = timezone.localdate()
        item = [{"nasabah_id": str(self.nasabah.id)}]

        otomatis = self._buat(item)
        bernama = self._buat(item, nama="Cair Lebaran")

        self.assertEqual(
            otomatis.data["nama"], f"Pencairan {hari.day} {bulan[hari.month - 1]} {hari.year}"
        )
        self.assertEqual(bernama.data["nama"], "Cair Lebaran")

    def test_draft_memuat_pembuat_dan_waktu(self) -> None:
        response = self._buat([{"nasabah_id": str(self.nasabah.id)}])

        self.assertEqual(response.data["dibuat_oleh_nama"], "Ibu Sari")
        self.assertEqual(response.data["diubah_oleh_nama"], "Ibu Sari")
        self.assertIn("created_at", response.data)
        self.assertIn("updated_at", response.data)
        daftar = self.client.get(URL).data["results"][0]
        self.assertEqual(daftar["nama"], response.data["nama"])
        self.assertEqual(daftar["diubah_oleh_nama"], "Ibu Sari")
