from django.db import models
from django.test import TestCase

from api.models import User


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
