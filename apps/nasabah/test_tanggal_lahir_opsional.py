"""PIL-478: tanggal lahir nasabah tidak lagi wajib.

Temuan UAT: tanggal lahir dianggap tidak terlalu diperlukan dan terlalu
sensitif untuk diminta dari nasabah. Kolomnya sudah ``null=True`` sejak awal,
jadi yang diuji di sini adalah lapisan serializer: menghilangkan field,
mengirimnya sebagai ``null``, dan mengosongkan tanggal yang sudah tersimpan.

Mengirim ``null`` adalah jalur yang paling mudah terlewat. DRF memanggil
``validate_<field>`` setiap kali kuncinya ada di payload, termasuk saat
nilainya ``None``, jadi pembanding tanggal harus menoleransi ``None`` alih-alih
melempar ``TypeError``.
"""

from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, User


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "kode": "NAS-0001",
        "nama": "Budi Santoso",
        "jenis_kelamin": "laki-laki",
        "tanggal_lahir": "1990-01-01",
        "no_hp": "081234567890",
        "alamat": "Jl. Anggrek No. 3",
        "email": "budi@example.com",
    }
    payload.update(overrides)
    return payload


class TanggalLahirOpsionalPengurusTests(APITestCase):
    """Pengurus menambah dan mengedit catatan nasabah tanpa tanggal lahir."""

    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(nama="Bank Nasabah", alamat="Depok", kota="Depok")
        self.pengelola = User.objects.create_user(
            email="pengurus@example.test",
            nama="Pengurus",
            bank_sampah=self.bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        self.client.force_authenticate(self.pengelola)

    def test_creates_a_nasabah_when_the_field_is_absent(self) -> None:
        body = _payload()
        del body["tanggal_lahir"]

        response = self.client.post("/api/v1/nasabah", body, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(response.data["tanggal_lahir"])
        self.assertIsNone(Nasabah.objects.get(email="budi@example.com").tanggal_lahir)

    def test_creates_a_nasabah_when_the_field_is_null(self) -> None:
        response = self.client.post("/api/v1/nasabah", _payload(tanggal_lahir=None), format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(response.data["tanggal_lahir"])
        self.assertIsNone(Nasabah.objects.get(email="budi@example.com").tanggal_lahir)

    def test_clears_a_tanggal_lahir_that_was_already_recorded(self) -> None:
        created = self.client.post("/api/v1/nasabah", _payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        nasabah_id = created.data["id"]

        response = self.client.patch(
            f"/api/v1/nasabah/{nasabah_id}", {"tanggal_lahir": None}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(response.data["tanggal_lahir"])
        self.assertIsNone(Nasabah.objects.get(pk=nasabah_id).tanggal_lahir)

    def test_a_future_tanggal_lahir_is_still_rejected(self) -> None:
        """Opsional bukan berarti bebas: tanggal yang mustahil tetap ditolak."""
        response = self.client.post(
            "/api/v1/nasabah", _payload(tanggal_lahir="2999-01-01"), format="json"
        )

        self.assertEqual(response.status_code, 422, response.data)
        self.assertEqual(
            response.data["errors"]["tanggal_lahir"],
            ["Tanggal lahir tidak boleh di masa depan"],
        )

    def test_detail_of_a_nasabah_without_tanggal_lahir_renders(self) -> None:
        """AC: tampilan tidak error saat tanggal lahir kosong."""
        nasabah = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-0009",
            nama="Tanpa Tanggal",
            no_hp="+628111111111",
            email="tanpa@example.test",
        )

        response = self.client.get(f"/api/v1/nasabah/{nasabah.id}")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(response.data["tanggal_lahir"])


class TanggalLahirOpsionalProfilAkunTests(APITestCase):
    """Nasabah menyimpan profil akunnya sendiri tanpa tanggal lahir."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="siti@example.test",
            nama="Siti Aminah",
            role=User.Role.NASABAH,
            alamat="Jl. Merdeka 10",
        )
        self.client.force_authenticate(self.user)
        self.url = "/api/v1/nasabah/me/profil"

    def test_saves_the_profile_when_tanggal_lahir_is_null(self) -> None:
        response = self.client.patch(self.url, {"tanggal_lahir": None}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(response.data["tanggal_lahir"])
        self.user.refresh_from_db()
        self.assertIsNone(self.user.tanggal_lahir)

    def test_clears_a_tanggal_lahir_the_nasabah_had_given_before(self) -> None:
        self.client.patch(self.url, {"tanggal_lahir": "1995-05-05"}, format="json")
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.tanggal_lahir)

        response = self.client.patch(self.url, {"tanggal_lahir": None}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.tanggal_lahir)

    def test_a_future_tanggal_lahir_is_still_rejected(self) -> None:
        response = self.client.patch(self.url, {"tanggal_lahir": "2999-01-01"}, format="json")

        self.assertEqual(response.status_code, 422, response.data)
