from api.models import BankSampah, Nasabah
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
