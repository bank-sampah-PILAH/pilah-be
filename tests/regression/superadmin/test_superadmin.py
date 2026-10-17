"""Superadmin contracts: bank queue, approvals, and role gating."""

from uuid import UUID

from django.test import override_settings

from api.models import BankSampah, User
from tests.regression.helpers import RegressionTestCase

REVIEW_BANK_ID = UUID("00000000-0000-4000-8000-000000000364")
REVIEW_SUPERADMIN_EMAIL = "reviewer@example.com"


class SuperadminRegressionTests(RegressionTestCase):
    def _as_superadmin(self) -> None:
        superadmin = User.objects.create_user(
            email="admin@example.com", nama="Admin", role=User.Role.SUPERADMIN
        )
        self.auth_as(superadmin)

    def _pending_bank(self, nama: str, *, bank_id: UUID | None = None) -> BankSampah:
        bank = BankSampah(
            id=bank_id,
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

    @override_settings(
        PILAH_SUPERADMIN_EMAILS=(),
        PILAH_REVIEW_SUPERADMIN_EMAILS=(REVIEW_SUPERADMIN_EMAIL,),
    )
    def test_review_superadmin_can_approve_only_the_pending_review_bank(self) -> None:
        reviewer = User.objects.create_user(
            email=REVIEW_SUPERADMIN_EMAIL,
            nama="Review Superadmin",
            role=User.Role.SUPERADMIN,
        )
        self._pending_bank("Synthetic Review Bank", bank_id=REVIEW_BANK_ID)
        real_bank = self._pending_bank("Unrelated Real Bank")
        self.auth_as(reviewer)

        queue = self.client.get("/api/v1/superadmin/bank-sampah?status=pending")
        active = self.client.get("/api/v1/superadmin/bank-sampah?status=active")
        real_detail = self.client.get(f"/api/v1/superadmin/bank-sampah/{real_bank.id}")
        real_approval = self.client.post(
            f"/api/v1/superadmin/bank-sampah/{real_bank.id}/approve", {}, format="json"
        )
        review_approval = self.client.post(
            f"/api/v1/superadmin/bank-sampah/{REVIEW_BANK_ID}/approve", {}, format="json"
        )

        self.assertEqual(queue.status_code, 200, queue.data)
        self.assertEqual([row["id"] for row in queue.data["results"]], [str(REVIEW_BANK_ID)])
        self.assertEqual(active.data["count"], 0)
        self.assertEqual(real_detail.status_code, 404)
        self.assertEqual(real_approval.status_code, 404)
        self.assertEqual(review_approval.status_code, 200, review_approval.data)

    @override_settings(
        PILAH_SUPERADMIN_EMAILS=(),
        PILAH_REVIEW_SUPERADMIN_EMAILS=(REVIEW_SUPERADMIN_EMAIL,),
    )
    def test_review_superadmin_can_reject_only_the_pending_review_bank(self) -> None:
        reviewer = User.objects.create_user(
            email=REVIEW_SUPERADMIN_EMAIL,
            nama="Review Superadmin",
            role=User.Role.SUPERADMIN,
        )
        self._pending_bank("Synthetic Review Bank", bank_id=REVIEW_BANK_ID)
        real_bank = self._pending_bank("Unrelated Real Bank")
        self.auth_as(reviewer)

        real_rejection = self.client.post(
            f"/api/v1/superadmin/bank-sampah/{real_bank.id}/reject", {}, format="json"
        )
        review_rejection = self.client.post(
            f"/api/v1/superadmin/bank-sampah/{REVIEW_BANK_ID}/reject", {}, format="json"
        )

        self.assertEqual(real_rejection.status_code, 404)
        self.assertEqual(review_rejection.status_code, 200, review_rejection.data)

    @override_settings(
        PILAH_SUPERADMIN_EMAILS=(REVIEW_SUPERADMIN_EMAIL,),
        PILAH_REVIEW_SUPERADMIN_EMAILS=(),
    )
    def test_global_superadmin_still_sees_the_full_approval_queue(self) -> None:
        admin = User.objects.create_user(
            email=REVIEW_SUPERADMIN_EMAIL,
            nama="Global Superadmin",
            role=User.Role.SUPERADMIN,
            is_staff=True,
            is_superuser=True,
        )
        first = self._pending_bank("First Pending")
        second = self._pending_bank("Second Pending")
        self.auth_as(admin)

        response = self.client.get("/api/v1/superadmin/bank-sampah?status=pending")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            {row["id"] for row in response.data["results"]}, {str(first.id), str(second.id)}
        )
