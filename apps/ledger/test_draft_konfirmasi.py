from decimal import Decimal
from typing import Any
from unittest import mock

from api.models import DraftPencairan, Nasabah, Pencairan, Saldo, User
from apps.ledger.draft_testing import URL, DraftTestBase


class KonfirmasiDraftTests(DraftTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.budi = self._nasabah("NAS-0002", "Budi Santoso", "50000")

    def _draft(self, **extra: Any) -> dict[str, Any]:
        response = self._buat(
            [
                {"nasabah_id": str(self.nasabah.id), "nominal": "100000", "metode": "transfer"},
                {"nasabah_id": str(self.budi.id)},
            ],
            **extra,
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data  # type: ignore[no-any-return]

    def _konfirmasi(self, draft_id: str) -> Any:
        return self.client.post(f"{URL}/{draft_id}/konfirmasi")

    def _saldo(self, nasabah: Nasabah) -> Decimal:
        return Saldo.objects.get(nasabah=nasabah).total_saldo

    def test_konfirmasi_mengurangi_saldo_dan_menulis_riwayat_satu_kali(self) -> None:
        draft = self._draft(potongan_jenis="persen", potongan_nilai="10")

        response = self._konfirmasi(draft["id"])

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "dikonfirmasi")
        self.assertEqual(self._saldo(self.nasabah), Decimal(365600))
        self.assertEqual(self._saldo(self.budi), Decimal(0))
        riwayat = {p.nasabah.nama: p for p in Pencairan.objects.select_related("nasabah")}
        ahmad = riwayat["Ahmad Ridwan"]
        self.assertEqual(
            (ahmad.nominal, ahmad.potongan, ahmad.metode, ahmad.dicatat_oleh),
            (Decimal(100000), Decimal(10000), "transfer", self.user),
        )
        self.assertEqual(
            (ahmad.saldo_sebelum, ahmad.saldo_sesudah), (Decimal(465600), Decimal(365600))
        )
        self.assertEqual(ahmad.draft_id, DraftPencairan.objects.get().id)
        self.assertEqual(riwayat["Budi Santoso"].nominal, Decimal(50000))
        self.assertEqual(riwayat["Budi Santoso"].potongan, Decimal(5000))

    def test_draft_terkonfirmasi_menyimpan_saldo_awal_sebelum_dibayar(self) -> None:
        draft = self._draft()
        self._konfirmasi(draft["id"])

        detail = self.client.get(f"{URL}/{draft['id']}")

        saldo_awal = {i["nasabah_nama"]: i["saldo_saat_ini"] for i in detail.data["items"]}
        self.assertEqual(saldo_awal["Ahmad Ridwan"], "465600.00")
        self.assertEqual(saldo_awal["Budi Santoso"], "50000.00")
        self.assertEqual(self._saldo(self.budi), Decimal(0), "the live saldo did go down")

    def test_saldo_awal_tetap_walau_saldo_nasabah_berubah_lagi(self) -> None:
        draft = self._draft()
        self._konfirmasi(draft["id"])
        Saldo.objects.filter(nasabah=self.nasabah).update(total_saldo=Decimal(1))

        detail = self.client.get(f"{URL}/{draft['id']}")

        saldo_awal = {i["nasabah_nama"]: i["saldo_saat_ini"] for i in detail.data["items"]}
        self.assertEqual(saldo_awal["Ahmad Ridwan"], "465600.00")

    def test_draft_yang_masih_draft_tetap_menunjukkan_saldo_terkini(self) -> None:
        draft = self._draft()
        Saldo.objects.filter(nasabah=self.nasabah).update(total_saldo=Decimal(777))

        detail = self.client.get(f"{URL}/{draft['id']}")

        saldo = {i["nasabah_nama"]: i["saldo_saat_ini"] for i in detail.data["items"]}
        self.assertEqual(saldo["Ahmad Ridwan"], "777.00")

    def test_riwayat_pengurus_menampilkan_potongan_dan_nominal_dibayar(self) -> None:
        self._konfirmasi(self._draft(potongan_jenis="persen", potongan_nilai="10")["id"])

        hasil = self.client.get("/api/v1/pencairan").data["results"]

        ahmad = next(p for p in hasil if p["nasabah_nama"] == "Ahmad Ridwan")
        self.assertEqual(ahmad["nominal"], "100000.00")
        self.assertEqual(ahmad["potongan"], "10000.00")
        self.assertEqual(ahmad["dibayar"], "90000.00")

    def test_konfirmasi_kedua_kali_ditolak_tanpa_mengubah_saldo_lagi(self) -> None:
        draft = self._draft()
        self._konfirmasi(draft["id"])

        ulang = self._konfirmasi(draft["id"])

        self.assertEqual(ulang.status_code, 409, ulang.data)
        self.assertEqual(Pencairan.objects.count(), 2)
        self.assertEqual(self._saldo(self.nasabah), Decimal(365600))

    def test_saldo_berubah_sejak_draft_menggagalkan_seluruh_konfirmasi(self) -> None:
        draft = self._draft()
        Saldo.objects.filter(nasabah=self.budi).update(total_saldo=Decimal(20000))

        response = self._konfirmasi(draft["id"])

        self.assertEqual(response.status_code, 422, response.data)
        self.assertEqual(list(response.data["errors"]), ["items[1].nominal"])
        self.assertEqual(self._saldo(self.nasabah), Decimal(465600))
        self.assertFalse(Pencairan.objects.exists())
        self.assertEqual(DraftPencairan.objects.get().status, "draft")

    def test_nasabah_dinonaktifkan_sejak_draft_menggagalkan_konfirmasi(self) -> None:
        draft = self._draft()
        Nasabah.objects.filter(id=self.budi.id).update(is_active=False)

        response = self._konfirmasi(draft["id"])

        self.assertEqual(response.status_code, 422, response.data)
        self.assertIn("items[1].nasabah_id", response.data["errors"])
        self.assertFalse(Pencairan.objects.exists())

    def test_kegagalan_di_tengah_proses_tidak_meninggalkan_saldo_atau_riwayat(self) -> None:
        draft = self._draft()
        asli = Pencairan.objects.create

        def gagal_pada_kedua(**kwargs: Any) -> Pencairan:
            if Pencairan.objects.exists():
                raise RuntimeError("database putus")
            return asli(**kwargs)

        with (
            mock.patch.object(Pencairan.objects, "create", side_effect=gagal_pada_kedua),
            self.assertRaises(RuntimeError),
        ):
            self._konfirmasi(draft["id"])

        self.assertEqual(self._saldo(self.nasabah), Decimal(465600))
        self.assertEqual(self._saldo(self.budi), Decimal(50000))
        self.assertFalse(Pencairan.objects.exists())
        self.assertEqual(DraftPencairan.objects.get().status, "draft")

    def test_draft_dibatalkan_tidak_bisa_dikonfirmasi(self) -> None:
        draft = self._draft()
        self.client.post(f"{URL}/{draft['id']}/batalkan")

        response = self._konfirmasi(draft["id"])

        self.assertEqual(response.status_code, 409, response.data)
        self.assertFalse(Pencairan.objects.exists())

    def test_konfirmasi_draft_bank_lain_atau_oleh_nasabah_ditolak(self) -> None:
        asing = self._draft_bank_lain()
        self.assertEqual(self._konfirmasi(str(asing.id)).status_code, 404)
        draft = self._draft()
        self._login(
            User.objects.create_user(email="n@example.test", nama="N", role=User.Role.NASABAH)
        )

        self.assertEqual(self._konfirmasi(draft["id"]).status_code, 403)

    def test_pencairan_berpotongan_hanya_boleh_ubah_metode_dan_keterangan(self) -> None:
        self._konfirmasi(self._draft(potongan_jenis="persen", potongan_nilai="10")["id"])
        pencairan = Pencairan.objects.get(nasabah=self.nasabah)
        url = f"/api/v1/pencairan/{pencairan.id}"

        nominal = self.client.patch(url, {"nominal": "90000", "alasan": "salah"}, format="json")
        metode = self.client.patch(
            url, {"metode": "tunai", "alasan": "dibayar tunai"}, format="json"
        )

        self.assertEqual(nominal.status_code, 422, nominal.data)
        self.assertIn("nominal", nominal.data["errors"])
        self.assertEqual(metode.status_code, 200, metode.data)
        self.assertEqual(metode.data["metode"], "tunai")

    def test_edit_metode_dengan_semua_field_dan_tanggal_dibulatkan_milidetik_diterima(
        self,
    ) -> None:
        # The app sends every field back; on the web a DateTime keeps only
        # milliseconds, so the tanggal it returns is a hair off the stored one.
        self._konfirmasi(self._draft(potongan_jenis="persen", potongan_nilai="10")["id"])
        pencairan = Pencairan.objects.get(nasabah=self.nasabah)
        tanggal = pencairan.tanggal.replace(
            microsecond=pencairan.tanggal.microsecond // 1000 * 1000
        )

        response = self.client.patch(
            f"/api/v1/pencairan/{pencairan.id}",
            {
                "nominal": str(int(pencairan.nominal)),
                "tanggal": tanggal.isoformat(),
                "metode": "tunai",
                "keterangan": pencairan.keterangan,
                "alasan": "dibayar tunai",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["metode"], "tunai")
        pencairan.refresh_from_db()
        self.assertEqual(pencairan.nominal, Decimal(100000))
