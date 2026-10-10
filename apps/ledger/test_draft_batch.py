from decimal import Decimal
from typing import Any
from unittest import mock

from api.models import BankSampah, DraftPencairan, Nasabah, Saldo
from apps.ledger.draft_testing import URL, DraftTestBase


class KandidatPencairanTests(DraftTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.budi = self._nasabah("NAS-0002", "Budi Santoso", "50000")
        self.citra = self._nasabah("NAS-0003", "Citra Dewi", "250000")

    def _kandidat(self, **params: str) -> list[dict[str, str]]:
        response = self.client.get(f"{URL}/kandidat", params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data  # type: ignore[no-any-return]

    def test_kandidat_hanya_nasabah_layak_bank_sendiri_tanpa_paginasi(self) -> None:
        self._nasabah("NAS-0004", "Dedi Nonaktif", "90000", is_active=False)
        self._nasabah("NAS-0005", "Eka Menunggu", "90000", status=Nasabah.Status.PENDING)
        self._nasabah("NAS-0006", "Fani Kosong", "0")
        self._nasabah("NAS-0007", "Gita Receh", "0.50")
        lain = BankSampah.objects.create(
            nama="Bank Lain",
            alamat="Bogor",
            kota="Bogor",
            no_hp_pic="+628111111111",
            status=BankSampah.Status.ACTIVE,
        )
        self._nasabah("NAS-0008", "Hadi Asing", "90000", bank=lain)

        kandidat = self._kandidat()

        self.assertEqual(
            [(k["kode"], k["nama"], k["saldo"]) for k in kandidat],
            [
                ("NAS-0001", "Ahmad Ridwan", "465600.00"),
                ("NAS-0002", "Budi Santoso", "50000.00"),
                ("NAS-0003", "Citra Dewi", "250000.00"),
            ],
        )
        self.assertIn("id", kandidat[0])

    def test_kandidat_bisa_dicari_diurutkan_dan_disaring_saldo_minimum(self) -> None:
        def nama(**params: str) -> list[str]:
            return [k["nama"] for k in self._kandidat(**params)]

        self.assertEqual(nama(search="budi"), ["Budi Santoso"])
        self.assertEqual(nama(ordering="-nama"), ["Citra Dewi", "Budi Santoso", "Ahmad Ridwan"])
        self.assertEqual(nama(ordering="saldo"), ["Budi Santoso", "Citra Dewi", "Ahmad Ridwan"])
        self.assertEqual(nama(ordering="-saldo"), ["Ahmad Ridwan", "Citra Dewi", "Budi Santoso"])
        self.assertEqual(nama(saldo_min="250000"), ["Ahmad Ridwan", "Citra Dewi"])

    def test_kandidat_bisa_menyertakan_nasabah_bersaldo_kosong_untuk_ditampilkan(self) -> None:
        self._nasabah("NAS-0004", "Dedi Nonaktif", "90000", is_active=False)
        self._nasabah("NAS-0006", "Fani Kosong", "0")
        self._nasabah("NAS-0007", "Gita Receh", "0.50")

        def nama(**params: str) -> list[str]:
            return [k["nama"] for k in self._kandidat(**params)]

        self.assertEqual(
            nama(termasuk_kosong="true"),
            ["Ahmad Ridwan", "Budi Santoso", "Citra Dewi", "Fani Kosong", "Gita Receh"],
        )
        self.assertEqual(
            nama(termasuk_kosong="true", ordering="saldo")[:2], ["Fani Kosong", "Gita Receh"]
        )
        self.assertEqual(nama(termasuk_kosong="true", search="fani"), ["Fani Kosong"])
        self.assertEqual(
            nama(termasuk_kosong="true", saldo_min="250000"), ["Ahmad Ridwan", "Citra Dewi"]
        )
        saldo = {k["nama"]: k["saldo"] for k in self._kandidat(termasuk_kosong="true")}
        self.assertEqual(saldo["Fani Kosong"], "0.00")

    def test_nasabah_yang_belum_punya_saldo_sama_sekali_tampil_sebagai_nol(self) -> None:
        baru = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-0009",
            nama="Hana Baru",
            email="hana@example.com",
            no_hp="+628100090000",
            alamat="Jl. Melati",
        )
        self.assertFalse(Saldo.objects.filter(nasabah=baru).exists())

        kandidat = self._kandidat(termasuk_kosong="true", ordering="saldo")

        self.assertEqual(kandidat[0]["nama"], "Hana Baru")
        self.assertEqual(kandidat[0]["saldo"], "0.00")
        self.assertNotIn("Hana Baru", [k["nama"] for k in self._kandidat()])

    def test_tanpa_termasuk_kosong_kandidat_tetap_hanya_yang_bisa_dicairkan(self) -> None:
        self._nasabah("NAS-0006", "Fani Kosong", "0")

        names = [k["nama"] for k in self._kandidat(termasuk_kosong="false")]

        self.assertNotIn("Fani Kosong", names)

    def test_batch_semua_tidak_membawa_nasabah_bersaldo_kosong(self) -> None:
        self._nasabah("NAS-0006", "Fani Kosong", "0")

        response = self.client.post(f"{URL}/batch", {"semua": True}, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotIn("Fani Kosong", [i["nasabah_nama"] for i in response.data["items"]])


class BatchPencairanTests(DraftTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.budi = self._nasabah("NAS-0002", "Budi Santoso", "50000")
        self.citra = self._nasabah("NAS-0003", "Citra Dewi", "250000")

    def _batch(self, **body: Any) -> Any:
        return self.client.post(f"{URL}/batch", body, format="json")

    def test_batch_semua_nasabah_layak_dengan_metode_dan_potongan_massal(self) -> None:
        response = self._batch(
            semua=True, metode="transfer", potongan_jenis="persen", potongan_nilai="10"
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["dilewati"], [])
        self.assertEqual(
            [(i["nasabah_nama"], i["nominal"], i["metode"]) for i in response.data["items"]],
            [
                ("Ahmad Ridwan", "465600.00", "transfer"),
                ("Budi Santoso", "50000.00", "transfer"),
                ("Citra Dewi", "250000.00", "transfer"),
            ],
        )
        self.assertEqual(response.data["total_nominal"], "765600.00")
        self.assertEqual(response.data["total_potongan"], "76560.00")
        self.assertEqual(response.data["total_dibayar"], "689040.00")
        self.assertEqual(Saldo.objects.get(nasabah=self.budi).total_saldo, Decimal(50000))

    def test_batch_pilihan_manual_hanya_memuat_yang_dipilih(self) -> None:
        response = self._batch(
            nasabah_ids=[str(self.citra.id), str(self.budi.id)], nama="Cair Pilihan"
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["nama"], "Cair Pilihan")
        self.assertEqual(
            sorted(i["nasabah_nama"] for i in response.data["items"]),
            ["Budi Santoso", "Citra Dewi"],
        )

    def test_nasabah_tidak_layak_dilewati_dengan_alasan_dan_tidak_menggagalkan_lainnya(
        self,
    ) -> None:
        nonaktif = self._nasabah("NAS-0004", "Dedi Nonaktif", "90000", is_active=False)
        kosong = self._nasabah("NAS-0005", "Eka Kosong", "0")
        kecil = self._nasabah("NAS-0006", "Fani Kecil", "5000")
        hilang = "5b2c8a54-0000-4000-8000-000000000000"

        response = self._batch(
            nasabah_ids=[str(i) for i in (self.budi.id, nonaktif.id, kosong.id, kecil.id, hilang)],
            potongan_jenis="rupiah",
            potongan_nilai="6000",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual([i["nasabah_nama"] for i in response.data["items"]], ["Budi Santoso"])
        alasan = {d["nasabah_id"]: d["alasan"] for d in response.data["dilewati"]}
        self.assertEqual(
            alasan,
            {
                str(nonaktif.id): "Nasabah tidak ditemukan atau tidak aktif",
                str(kosong.id): "Saldo nasabah kosong",
                str(kecil.id): "Potongan melebihi nominal pencairan",
                hilang: "Nasabah tidak ditemukan atau tidak aktif",
            },
        )

    def test_batch_tanpa_nasabah_yang_layak_ditolak(self) -> None:
        kosong = self._nasabah("NAS-0005", "Eka Kosong", "0")

        response = self._batch(nasabah_ids=[str(kosong.id)])

        self.assertEqual(response.status_code, 422, response.data)
        self.assertIn("nasabah_ids", response.data["errors"])
        self.assertFalse(DraftPencairan.objects.exists())

    def test_batch_harus_memilih_semua_atau_daftar_nasabah_tepat_satu(self) -> None:
        for body in ({}, {"semua": True, "nasabah_ids": [str(self.budi.id)]}, {"semua": False}):
            with self.subTest(body=body):
                self.assertEqual(self._batch(**body).status_code, 422)

    def test_batch_melebihi_batas_item_ditolak_baik_semua_maupun_daftar(self) -> None:
        # Three nasabah are eligible and the limit is two.
        with mock.patch.object(DraftPencairan, "MAKSIMAL_ITEM", 2):
            semua = self._batch(semua=True)
            daftar = self._batch(
                nasabah_ids=[str(n.id) for n in (self.nasabah, self.budi, self.citra)]
            )

        for response in (semua, daftar):
            self.assertEqual(response.status_code, 422, response.data)
            self.assertIn("2", str(response.data["errors"]["nasabah_ids"]))
        self.assertFalse(DraftPencairan.objects.exists())
