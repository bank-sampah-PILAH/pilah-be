from django.db import models
from django.test import TestCase

from api.models import BankSampah, Nasabah, User


class AssignedRolesTest(TestCase):
    def test_roles_are_json_and_preserve_single_and_dual_role_accounts(self):
        self.assertIsInstance(User._meta.get_field("roles"), models.JSONField)
        for role in User.Role.values:
            with self.subTest(role=role):
                user = User.objects.create_user(email=f"{role}@example.com", role=role)
                user.refresh_from_db()
                self.assertEqual(user.roles, [role])
                self.assertEqual(user.role, role)
        dual = User.objects.create_user(
            email="dual@example.com",
            role=User.Role.PENGELOLA,
            roles=[User.Role.PENGELOLA, User.Role.NASABAH],
        )
        dual.refresh_from_db()
        self.assertEqual(dual.roles, [User.Role.PENGELOLA, User.Role.NASABAH])
        self.assertEqual(dual.role, User.Role.PENGELOLA)

    def test_pengelola_with_nasabah_role_can_keep_membership_when_primary_role_changes(self):
        user = User.objects.create_user(
            email="member@example.com", role=User.Role.PENGELOLA,
            roles=[User.Role.PENGELOLA, User.Role.NASABAH],
        )
        bank = BankSampah.objects.create(nama="Bank A", no_hp_pic="+628123456789")
        member = Nasabah.objects.create(
            user=user, bank_sampah=bank, nomor="NAS-001", nama="Member",
            alamat="Jl. Test", no_hp="+628123456789", email=user.email,
        )
        user.role = User.Role.NASABAH
        user.save(update_fields=["role"])
        user.role = User.Role.PENGELOLA
        user.save(update_fields=["role"])
        user.refresh_from_db()
        member.refresh_from_db()
        self.assertEqual(member.user_id, user.pk)
        self.assertEqual(user.role, User.Role.PENGELOLA)
        self.assertIn(User.Role.NASABAH, user.roles)
