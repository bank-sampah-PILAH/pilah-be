"""PIL-441: actions on the customer list search, including access boundaries."""

from typing import Any

from rest_framework.response import Response

from api.models import BankSampah, Nasabah, Saldo
from tests.regression.helpers import RegressionTestCase


class NasabahSearchTests(RegressionTestCase):
    url = "/api/v1/nasabah"

    def setUp(self) -> None:
        super().setUp()
        self.budi = self.customer("000123", "Budi Santoso", "081211110001", "budi@example.test")
        self.siti = self.customer("000124", "Siti Aminah", "081211110002", "siti@example.test")
        self.dewi = self.customer("ZX-999", "Dewi Lestari", "081211110003", "dewi@example.test")

    def customer(self, nomor: str, nama: str, phone: str, email: str, **overrides: Any) -> Nasabah:
        values = {
            "bank_sampah": self.bank,
            "nomor": nomor,
            "nama": nama,
            "no_hp": phone,
            "email": email,
            "alamat": "Jl. Melati No. 10",
            **overrides,
        }
        customer = Nasabah.objects.create(**values)
        Saldo.objects.create(nasabah=customer)
        return customer

    def assert_search(self, query: str, expected: list[Nasabah], **params: Any) -> Response:
        response = self.client.get(self.url, {"search": query, **params})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], len(expected))
        self.assertEqual(
            [row["id"] for row in response.data["results"]],
            [str(customer.id) for customer in expected],
        )
        return response

    def test_type_full_id_preserves_leading_zeroes(self) -> None:
        response = self.assert_search("000123", [self.budi])
        self.assertEqual(response.data["results"][0]["kode"], "000123")

    def test_type_partial_id_returns_every_match(self) -> None:
        self.assert_search("0012", [self.budi, self.siti])

    def test_type_id_with_different_case(self) -> None:
        self.assert_search("zx-999", [self.dewi])

    def test_type_name_phone_or_email_still_finds_customer(self) -> None:
        for query in ("bUdI", "11110001", "budi@example.test"):
            with self.subTest(query=query):
                self.assert_search(query, [self.budi])

    def test_type_unknown_or_special_input_returns_no_matches(self) -> None:
        for query in ("unknown-id", "' OR 1=1 --", "%%", "__", "x" * 1000):
            with self.subTest(query=query):
                self.assert_search(query, [])

    def test_search_id_never_exposes_other_bank_even_with_same_id(self) -> None:
        other_bank = BankSampah.objects.create(nama="Other bank", no_hp_pic="081299990001")
        self.customer(
            "000123", "Other Budi", "081299990002", "other@example.test", bank_sampah=other_bank
        )
        self.customer(
            "FOREIGN-ONLY",
            "Other Siti",
            "081299990003",
            "other2@example.test",
            bank_sampah=other_bank,
        )
        self.assert_search("000123", [self.budi])
        self.assert_search("FOREIGN-ONLY", [])

    def test_search_id_respects_selected_status(self) -> None:
        for selected, changes in (
            ("tidak_aktif", {"is_active": False}),
            ("menunggu", {"status": Nasabah.Status.PENDING}),
            ("ditolak", {"status": Nasabah.Status.REJECTED}),
        ):
            with self.subTest(selected=selected):
                Nasabah.objects.filter(pk=self.budi.pk).update(
                    is_active=True, status=Nasabah.Status.APPROVED
                )
                Nasabah.objects.filter(pk=self.budi.pk).update(**changes)
                self.assert_search("000123", [])
                self.assert_search("000123", [self.budi], status=selected)

    def test_search_id_filters_before_pagination(self) -> None:
        first_page = self.client.get(self.url, {"page_size": 1})
        self.assertEqual(first_page.status_code, 200)
        self.assertNotIn(str(self.dewi.id), [row["id"] for row in first_page.data["results"]])
        self.assert_search("ZX-999", [self.dewi], page_size=1)

    def test_clear_search_restores_list_and_single_character_rule(self) -> None:
        self.assert_search("000123", [self.budi])
        for query in ("", "x"):
            with self.subTest(query=query):
                self.assert_search(query, [self.budi, self.siti, self.dewi])

    def test_type_maximum_length_id(self) -> None:
        code = "MEMBER-" + "0" * 23
        customer = self.customer(code, "Long ID", "081211110004", "long@example.test")
        self.assert_search(code, [customer])
