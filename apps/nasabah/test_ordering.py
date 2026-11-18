"""PIL-442: choose an order, search/change status, and scroll the same query."""

from datetime import date
from decimal import Decimal
from typing import ClassVar

from django.urls import path
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from api.models import BankSampah, Nasabah, Saldo, User
from apps.nasabah.views import NasabahViewSet


class NasabahOrderingTests(APITestCase):
    bank: ClassVar[BankSampah]
    pengurus: ClassVar[User]
    expected: ClassVar[dict[str, list[int]]] = {
        "nomor": [1, 2, 3, 4, 5, 6],
        "nama": [3, 4, 5, 2, 6, 1],
        "terbaru": [2, 6, 3, 4, 5, 1],
        "saldo_terbesar": [1, 6, 2, 3, 4, 5],
        "saldo_terkecil": [4, 5, 2, 3, 1, 6],
    }

    @classmethod
    def setUpTestData(cls) -> None:
        cls.bank = BankSampah.objects.create(nama="Bank Urutan", alamat="Depok", kota="Depok")
        cls.pengurus = User.objects.create_user(
            email="urutan@example.test",
            nama="Pengurus",
            bank_sampah=cls.bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        # Mixed primary keys exercise each ordering independently.
        for number, name, month, balance in (
            (6, "Budi", 3, 500),
            (5, "adi", 2, None),
            (4, "Adi", 2, 0),
            (3, "adi", 2, 100),
            (2, "Budi", 3, 100),
            (1, "Zaki", 1, 500),
        ):
            customer = Nasabah.objects.create(
                bank_sampah=cls.bank,
                nomor=f"NAS-{number:04}",
                nama=name,
                no_hp=f"+62812345000{number}",
                email=f"nasabah{number}@example.test",
                alamat="Jl. Mawar No. 10",
                tanggal_daftar=date(2026, month, 1),
            )
            if balance is not None:
                Saldo.objects.create(nasabah=customer, total_saldo=Decimal(balance))

        other_bank = BankSampah.objects.create(nama="Bank Lain", alamat="Bogor", kota="Bogor")
        outsider = Nasabah.objects.create(
            bank_sampah=other_bank,
            nomor="NAS-0001",
            nama="Aaa Outsider",
            no_hp="+628123456789",
            email="outsider@example.test",
            tanggal_daftar=date(2026, 12, 1),
        )
        Saldo.objects.create(nasabah=outsider, total_saldo=Decimal(999999))

    def setUp(self) -> None:
        self.client.force_authenticate(self.pengurus)

    def assert_order(self, numbers: list[int], **params: str | int) -> None:
        response = self.client.get("/api/v1/nasabah", params)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], len(numbers))
        self.assertEqual(
            [row["kode"] for row in response.data["results"]],
            [f"NAS-{number:04}" for number in numbers],
        )

    def test_open_defaults_to_member_number(self) -> None:
        self.assert_order(self.expected["nomor"])

    def test_each_order_pins_member_number_as_the_last_query_key(self) -> None:
        # Result-only assertions can accidentally pass without a tie-break on
        # PostgreSQL's heap order. Pin the total-order contract as well.
        expected = {
            "nomor": ("nomor",),
            "nama": ("_nama_urutan", "nomor"),
            "terbaru": ("-tanggal_daftar", "nomor"),
            "saldo_terbesar": ("-_saldo_urutan", "nomor"),
            "saldo_terkecil": ("_saldo_urutan", "nomor"),
        }
        for order, keys in expected.items():
            with self.subTest(order=order):
                request = APIRequestFactory().get("/api/v1/nasabah", {"urutan": order})
                force_authenticate(request, self.pengurus)
                view = NasabahViewSet()
                view.action_map = {"get": "list"}
                view.request = view.initialize_request(request)
                self.assertEqual(view.get_queryset().query.order_by, keys)

    def test_large_tie_group_keeps_member_number_order_across_pages(self) -> None:
        Nasabah.objects.filter(bank_sampah=self.bank).delete()
        for number in reversed(range(1, 49)):
            customer = Nasabah.objects.create(
                bank_sampah=self.bank,
                nomor=f"NAS-{number:04}",
                nama="Same name",
                no_hp=f"+6281234{number:06}",
                email=f"tie{number}@example.test",
                tanggal_daftar=date(2026, 1, 1),
            )
            Saldo.objects.create(nasabah=customer, total_saldo=Decimal(100))
        for order in self.expected:
            with self.subTest(order=order):
                actual: list[str] = []
                for page in range(1, 6):
                    params: dict[str, str | int] = {"urutan": order, "page_size": 10, "page": page}
                    response = self.client.get("/api/v1/nasabah", params)
                    self.assertEqual(response.status_code, 200, response.data)
                    actual.extend(row["kode"] for row in response.data["results"])
                self.assertEqual(actual, [f"NAS-{n:04}" for n in range(1, 49)])

    def test_schema_lists_order_choices_without_rejecting_unknown_order(self) -> None:
        generator = SchemaGenerator(  # type: ignore[no-untyped-call]
            patterns=[path("api/v1/nasabah", NasabahViewSet.as_view({"get": "list"}))]
        )
        schema = generator.get_schema(public=True)  # type: ignore[no-untyped-call]
        parameters = schema["paths"]["/api/v1/nasabah"]["get"]["parameters"]
        order = next(item for item in parameters if item["name"] == "urutan")
        self.assertEqual(order["schema"]["enum"], sorted(self.expected))

    def test_choose_each_order_with_member_number_ties_and_bank_isolation(self) -> None:
        for order, expected in self.expected.items():
            with self.subTest(order=order):
                self.assert_order(expected, urutan=order)

    def test_unknown_or_blank_order_safely_falls_back_to_member_number(self) -> None:
        for order in ("", "unknown", "-nama", "saldo__total_saldo", "nama; DROP TABLE nasabah"):
            with self.subTest(order=order):
                self.assert_order(self.expected["nomor"], urutan=order)

    def test_search_keeps_each_selected_order(self) -> None:
        for order, expected in self.expected.items():
            with self.subTest(order=order):
                self.assert_order([n for n in expected if n != 1], urutan=order, search="di")

    def test_empty_search_result_accepts_each_order(self) -> None:
        for order in self.expected:
            with self.subTest(order=order):
                self.assert_order([], urutan=order, search="not found")

    def test_change_status_preserves_each_selected_order(self) -> None:
        Nasabah.objects.filter(bank_sampah=self.bank, nomor__in=["NAS-0001", "NAS-0002"]).update(
            is_active=False
        )
        Nasabah.objects.filter(bank_sampah=self.bank, nomor__in=["NAS-0003", "NAS-0004"]).update(
            status=Nasabah.Status.PENDING
        )
        for status, members in (("aktif", [5, 6]), ("tidak_aktif", [1, 2]), ("menunggu", [3, 4])):
            for order, expected in self.expected.items():
                with self.subTest(status=status, order=order):
                    self.assert_order(
                        [n for n in expected if n in members], status=status, urutan=order
                    )

    def test_reset_query_returns_default_order_without_changing_status(self) -> None:
        for status, values in (
            ("aktif", {"is_active": True, "status": Nasabah.Status.APPROVED}),
            ("tidak_aktif", {"is_active": False, "status": Nasabah.Status.APPROVED}),
            ("menunggu", {"is_active": True, "status": Nasabah.Status.PENDING}),
        ):
            with self.subTest(status=status):
                Nasabah.objects.filter(bank_sampah=self.bank).update(**values)
                self.assert_order([3, 4, 5, 2, 6], urutan="nama", search="di", status=status)
                self.assert_order(self.expected["nomor"], urutan="nomor", status=status)

    def test_scroll_each_order_is_stable_without_duplicates_or_missing_members(self) -> None:
        for order, expected in self.expected.items():
            with self.subTest(order=order):
                actual: list[str] = []
                # One row per page forces every equal-value group across pages.
                for page in range(1, 7):
                    params: dict[str, str | int] = {"urutan": order, "page_size": 1, "page": page}
                    response = self.client.get("/api/v1/nasabah", params)
                    self.assertEqual(response.status_code, 200, response.data)
                    self.assertEqual(response.data["count"], 6)
                    actual.extend(row["kode"] for row in response.data["results"])
                    self.assertEqual(response.data["next"] is None, page == 6)
                self.assertEqual(actual, [f"NAS-{number:04}" for number in expected])
                self.assertEqual(len(set(actual)), 6)

    def test_single_member_and_missing_balance_sort_as_displayed_zero(self) -> None:
        Nasabah.objects.filter(bank_sampah=self.bank).exclude(nomor="NAS-0005").delete()
        for order in self.expected:
            with self.subTest(order=order):
                self.assert_order([5], urutan=order)
                response = self.client.get("/api/v1/nasabah", {"urutan": order})
                self.assertEqual(response.data["results"][0]["total_saldo"], Decimal(0))

    def test_empty_status_tab_accepts_each_order(self) -> None:
        for order in self.expected:
            with self.subTest(order=order):
                self.assert_order([], urutan=order, status="menunggu")

    def test_anonymous_user_cannot_choose_an_order(self) -> None:
        self.client.force_authenticate(None)
        response = self.client.get("/api/v1/nasabah", {"urutan": "saldo_terbesar"})
        self.assertEqual(response.status_code, 401)
