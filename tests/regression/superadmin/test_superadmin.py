"""Superadmin contracts: bank queue, approvals, and role gating."""

from api.models import BankSampah, User
from tests.regression.helpers import RegressionTestCase


class SuperadminRegressionTests(RegressionTestCase):
    def _as_superadmin(self) -> None:
        superadmin = User.objects.create_user(
            email="admin@example.com", nama="Admin", role=User.Role.SUPERADMIN
        )
        self.auth_as(superadmin)

    def _pending_bank(self, nama: str) -> BankSampah:
        bank = BankSampah(
            nama=nama, alamat="Jl. Panjang Sekali No. 1", kota="Depok", no_hp_pic="+628100000001"
        )
        bank.status = BankSampah.Status.PENDING
        bank.save()
        return bank

    def test_queue_access_contract(self) -> None:
        self._as_superadmin()
        response = self.client.get("/api/v1/superadmin/bank-sampah")
        self.assertEqual(response.status_code, 200)
        self.auth_as(self.user)
        self.assertEqual(self.client.get("/api/v1/superadmin/bank-sampah").status_code, 403)

    def test_queue_filters_and_invalid_ignored(self) -> None:
        self._as_superadmin()
        self._pending_bank("Antrean")
        for params in ("?status=pending", "?status=active", "?status=rejected", "?status=bogus"):
            with self.subTest(params=params):
                response = self.client.get(f"/api/v1/superadmin/bank-sampah{params}")
                self.assertEqual(response.status_code, 200)
                self.assertIn("count", response.data)

    def test_approve_and_reject_bank(self) -> None:
        self._as_superadmin()
        pending = self._pending_bank("Calon Bank")
        approved = self.client.post(
            f"/api/v1/superadmin/bank-sampah/{pending.id}/approve", {"catatan": "ok"}, format="json"
        )
        self.assertEqual(approved.status_code, 200)
        self.assertIn("bank_sampah", approved.data)
        self.assertIn("approval_log", approved.data)
        pending.refresh_from_db()
        self.assertEqual(pending.status, BankSampah.Status.ACTIVE)

        rejected_bank = self._pending_bank("Calon Buruk")
        rejected = self.client.post(
            f"/api/v1/superadmin/bank-sampah/{rejected_bank.id}/reject",
            {"catatan": "tidak"},
            format="json",
        )
        self.assertEqual(rejected.status_code, 200)
        rejected_bank.refresh_from_db()
        self.assertEqual(rejected_bank.status, BankSampah.Status.REJECTED)

    def test_retrieve_bank(self) -> None:
        self._as_superadmin()
        response = self.client.get(f"/api/v1/superadmin/bank-sampah/{self.bank.id}")
        self.assertEqual(response.status_code, 200)
