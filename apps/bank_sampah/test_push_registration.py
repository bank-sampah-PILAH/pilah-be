from django.test import TestCase

from api.models import BankSampah, PushNotification, User
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

    def test_repeating_same_decision_does_not_send_duplicate_push(self) -> None:
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
        ApprovalService.approve(bank, admin)
        self.assertEqual(
            PushNotification.objects.filter(user=manager, title="Pendaftaran disetujui").count(), 1
        )

        rejected_bank = BankSampah.objects.create(nama="Anggrek", alamat="Bogor", kota="Bogor")
        rejected_manager = User.objects.create_user(
            email="rejected@example.test",
            nama="Manager",
            bank_sampah=rejected_bank,
            is_primary_pengelola=True,
        )
        ApprovalService.reject(rejected_bank, admin)
        ApprovalService.reject(rejected_bank, admin)
        self.assertEqual(
            PushNotification.objects.filter(
                user=rejected_manager, title="Pendaftaran perlu diperbaiki"
            ).count(),
            1,
        )

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
