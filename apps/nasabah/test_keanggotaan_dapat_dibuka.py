"""`dapat_dibuka` pada daftar keanggotaan milik nasabah sendiri (PIL-236).

`GET /nasabah/me` menampilkan semua keanggotaan, termasuk yang ditolak
endpoint beranda. Tanpa penanda ini aplikasi tidak dapat membedakan
keanggotaan yang benar-benar bisa dibuka dari yang sudah mati, sehingga layar
"Bank sampah saya" menawarkan bank yang justru dijawab 403 pada ketukan
berikutnya.
"""

from typing import Any

from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, User


class KeanggotaanDapatDibukaTests(APITestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(nama="Melati", no_hp_pic="08123456789")
        self.user = User.objects.create_user(
            email="siti@example.test", nama="Siti", role=User.Role.NASABAH
        )
        self.member = Nasabah.objects.create(
            email="siti@example.test",
            user=self.user,
            bank_sampah=self.bank,
            nomor="NAS-001",
            nama="Siti",
            alamat="Depok",
            no_hp="08123456789",
        )
        self.client.force_authenticate(self.user)
        self.url = "/api/v1/nasabah/me"

    def _baris(self) -> dict[str, Any]:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return {baris["id"]: baris for baris in response.data}[str(self.member.id)]

    def test_keanggotaan_disetujui_dan_aktif_dapat_dibuka(self) -> None:
        self.assertIs(self._baris()["dapat_dibuka"], True)

    def test_keanggotaan_yang_belum_disetujui_atau_nonaktif_tidak_dapat_dibuka(self) -> None:
        for status in (Nasabah.Status.PENDING, Nasabah.Status.REJECTED):
            with self.subTest(status=status):
                self.member.status = status
                self.member.save()
                self.assertIs(self._baris()["dapat_dibuka"], False)
        self.member.status = Nasabah.Status.APPROVED
        self.member.is_active = False
        self.member.save()
        self.assertIs(self._baris()["dapat_dibuka"], False)

    def test_keanggotaan_di_bank_yang_mati_tidak_dapat_dibuka(self) -> None:
        """Syarat sisi bank sama dengan yang dipakai endpoint beranda.

        Bank yang dinonaktifkan atau belum disetujui membuat keanggotaan yang
        statusnya sendiri sehat tetap tidak bisa dibuka, dan inilah kasus yang
        tidak terlihat dari baris keanggotaan saja.
        """
        for status, is_active in (
            (BankSampah.Status.ACTIVE, False),
            (BankSampah.Status.PENDING, True),
            (BankSampah.Status.REJECTED, True),
        ):
            with self.subTest(bank_status=status, bank_is_active=is_active):
                self.bank.status, self.bank.is_active = status, is_active
                self.bank.save()
                self.assertIs(self._baris()["dapat_dibuka"], False)
