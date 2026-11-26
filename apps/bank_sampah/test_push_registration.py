from django.test import TestCase

from api.models import BankSampah, BankSampahApprovalLog, PushNotification, User
from apps.bank_sampah.services import ApprovalService


class RegistrationPushTests(TestCase):
    def test_approval_notifies_primary_manager(self) -> None:
        bank = BankSampah.objects.create(
            nama="Melati",
            alamat="Depok",
            kota="Depok",
            status=BankSampah.Status.PENDING,
            is_active=False,
        )
        manager = User.objects.create_user(
            email="manager@example.test",
            nama="Manager",
            bank_sampah=bank,
            is_primary_pengelola=True,
        )
        admin = User.objects.create_user(
            email="admin@example.test", nama="Admin", role=User.Role.SUPERADMIN
        )
        ApprovalService.approve(bank, admin)
        self.assertEqual(
            PushNotification.objects.filter(user=manager, title="Pendaftaran disetujui").count(), 1
        )

    def test_rejection_notifies_primary_manager(self) -> None:
        bank = BankSampah.objects.create(
            nama="Melati",
            alamat="Depok",
            kota="Depok",
            status=BankSampah.Status.PENDING,
            is_active=False,
        )
        manager = User.objects.create_user(
            email="manager@example.test",
            nama="Manager",
            bank_sampah=bank,
            is_primary_pengelola=True,
        )
        admin = User.objects.create_user(
            email="admin@example.test", nama="Admin", role=User.Role.SUPERADMIN
        )
        ApprovalService.reject(bank, admin)
        self.assertEqual(
            PushNotification.objects.filter(
                user=manager, title="Pendaftaran perlu diperbaiki"
            ).count(),
            1,
        )

    def test_stale_instance_cannot_decide_again(self) -> None:
        admin = User.objects.create_user(
            email="admin@example.test", nama="Admin", role=User.Role.SUPERADMIN
        )
        for decided_to, title, decide in (
            (BankSampah.Status.ACTIVE, "Pendaftaran disetujui", ApprovalService.approve),
            (BankSampah.Status.REJECTED, "Pendaftaran perlu diperbaiki", ApprovalService.reject),
        ):
            for stale_call in (ApprovalService.approve, ApprovalService.reject):
                with self.subTest(decided_to=decided_to, stale_call=stale_call.__name__):
                    bank = BankSampah.objects.create(
                        nama="Melati",
                        alamat="Depok",
                        kota="Depok",
                        status=BankSampah.Status.PENDING,
                        is_active=False,
                    )
                    manager = User.objects.create_user(
                        email=f"m-{bank.pk}@example.test",
                        nama="Manager",
                        bank_sampah=bank,
                        is_primary_pengelola=True,
                    )
                    stale = BankSampah.objects.get(pk=bank.pk)
                    self.assertEqual(stale.status, BankSampah.Status.PENDING)
                    decide(bank, admin)

                    with self.assertRaises(ValueError):
                        stale_call(stale, admin)

                    bank.refresh_from_db()
                    self.assertEqual(bank.status, decided_to)
                    self.assertEqual(
                        BankSampahApprovalLog.objects.filter(bank_sampah=bank).count(), 1
                    )
                    self.assertEqual(PushNotification.objects.filter(user=manager).count(), 1)
                    self.assertEqual(
                        PushNotification.objects.filter(user=manager, title=title).count(), 1
                    )

    def test_decision_refreshes_passed_instance(self) -> None:
        bank = BankSampah.objects.create(
            nama="Melati",
            alamat="Depok",
            kota="Depok",
            status=BankSampah.Status.PENDING,
            is_active=False,
        )
        admin = User.objects.create_user(
            email="admin@example.test", nama="Admin", role=User.Role.SUPERADMIN
        )
        stale = BankSampah.objects.get(pk=bank.pk)
        BankSampah.objects.filter(pk=bank.pk).update(nama="Melati Baru")
        ApprovalService.approve(stale, admin)
        self.assertEqual(stale.nama, "Melati Baru")
        self.assertEqual(stale.status, BankSampah.Status.ACTIVE)

    def test_application_notifies_active_superadmins(self) -> None:
        from apps.bank_sampah.services import BankOnboardingService

        manager = User.objects.create_user(email="applicant@example.test", nama="Manager")
        admin = User.objects.create_user(
            email="admin@example.test", nama="Admin", role=User.Role.SUPERADMIN
        )
        BankOnboardingService.register_bank_sampah(
            manager,
            {
                "nama": "Melati",
                "alamat": "Depok",
                "kota": "Depok",
                "no_hp_pic": "0812345",
                "foto_kegiatan": "test.jpg",
            },
        )
        self.assertTrue(
            PushNotification.objects.filter(
                user=admin, title="Pendaftaran bank sampah baru"
            ).exists()
        )
