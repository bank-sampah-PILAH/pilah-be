from decimal import Decimal
from typing import Any

from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, DraftPencairan, Nasabah, Saldo, User

URL = "/api/v1/draft-pencairan"


class DraftTestBase(APITestCase):
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

    def _patch(self, draft_id: str, **body: Any) -> Any:
        return self.client.patch(f"{URL}/{draft_id}", body, format="json")
