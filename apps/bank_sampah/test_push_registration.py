from django.test import TestCase

from api.models import BankSampah, PushNotification, User
from apps.bank_sampah.services import ApprovalService


class RegistrationPushTests(TestCase):
    def test_approval_notifies_primary_manager(self):
        bank = BankSampah.objects.create(nama="Melati", alamat="Depok", kota="Depok")
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
        self.assertTrue(
            PushNotification.objects.filter(user=manager, title="Pendaftaran disetujui").exists()
        )

    def test_rejection_notifies_primary_manager(self):
        bank = BankSampah.objects.create(nama="Melati", alamat="Depok", kota="Depok")
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
        self.assertTrue(
            PushNotification.objects.filter(
                user=manager, title="Pendaftaran perlu diperbaiki"
            ).exists()
        )

    def test_application_notifies_active_superadmins(self):
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
