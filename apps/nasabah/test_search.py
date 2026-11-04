"""PIL-441: searching the customer list by customer ID (`nomor`, shown as `kode`)."""

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

    def test_query_matching_several_fields_lists_each_customer_once(self) -> None:
        by_id = self.customer("BUDI-ID", "Rani Maharani", "081211110005", "rani@example.test")
        # Budi matches by name and email, Rani only by her ID.
        self.assert_search("budi", [self.budi, by_id])

    def test_two_character_id_fragment_is_searched(self) -> None:
        self.assert_search("ZX", [self.dewi])

    def test_unknown_or_special_input_returns_no_matches(self) -> None:
        for query in ("unknown-id", "' OR 1=1 --", "%%", "__"):
            with self.subTest(query=query):
                self.assert_search(query, [])

    def test_search_never_exposes_other_bank_even_with_same_id(self) -> None:
        other_bank = BankSampah.objects.create(nama="Other bank", no_hp_pic="081299990001")
        self.customer(
            "000123", "Other Budi", "081299990002", "other@example.test", bank_sampah=other_bank
        )
        self.assert_search("000123", [self.budi])

    def test_search_by_id_respects_selected_status(self) -> None:
        Nasabah.objects.filter(pk=self.budi.pk).update(is_active=False)
        self.assert_search("000123", [])
        self.assert_search("000123", [self.budi], status="tidak_aktif")

    def test_search_by_id_filters_before_pagination(self) -> None:
        self.assert_search("ZX-999", [self.dewi], page_size=1)

    def test_clear_search_restores_list_and_single_character_rule(self) -> None:
        for query in ("", "x"):
            with self.subTest(query=query):
                self.assert_search(query, [self.budi, self.siti, self.dewi])

    def test_search_by_longest_id(self) -> None:
        code = "MEMBER-" + "0" * 23  # `Nasabah.nomor` allows 30 characters
        customer = self.customer(code, "Long ID", "081211110004", "long@example.test")
        self.assert_search(code, [customer])
