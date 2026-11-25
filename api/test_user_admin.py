from django.contrib import admin
from django.test import RequestFactory, TestCase

from api.models import User


class UserAdminFormTests(TestCase):
    def setUp(self) -> None:
        self.request = RequestFactory().get("/admin/api/user/add/")
        self.request.user = User.objects.create_superuser(email="admin@example.com")
        self.user_admin = admin.site._registry[User]

    def test_registered_add_form_initializes_assigned_roles_before_model_validation(self) -> None:
        form_class = self.user_admin.get_form(self.request)
        form = form_class(
            data={
                "email": "new-admin-user@example.com",
                "nama": "New User",
                "role": User.Role.NASABAH,
                "password1": "A-strong-test-password-472!",
                "password2": "A-strong-test-password-472!",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.NASABAH)
        self.assertEqual(user.roles, [User.Role.NASABAH])
        self.assertTrue(user.check_password("A-strong-test-password-472!"))

    def test_registered_change_form_preserves_assignments_when_editing_primary_role(self) -> None:
        for roles in ([User.Role.NASABAH], [User.Role.NASABAH, User.Role.PENGELOLA]):
            with self.subTest(roles=roles):
                user = User.objects.create_user(
                    email=f"edit-{len(roles)}@example.com",
                    nama="Existing",
                    role=User.Role.NASABAH,
                    roles=roles,
                )
                form_class = self.user_admin.get_form(self.request, obj=user)
                form = form_class(
                    instance=user,
                    data={
                        "email": user.email,
                        "nama": user.nama,
                        "role": User.Role.PENGELOLA,
                        "is_active": True,
                    },
                )
                self.assertTrue(form.is_valid(), form.errors)
                form.save()
                user.refresh_from_db()
                self.assertEqual(user.role, User.Role.PENGELOLA)
                self.assertEqual(user.roles, [User.Role.NASABAH, User.Role.PENGELOLA])

    def test_registered_add_form_rejects_invalid_primary_role_without_server_error(self) -> None:
        form_class = self.user_admin.get_form(self.request)
        form = form_class(
            data={
                "email": "invalid-admin-user@example.com",
                "nama": "Invalid",
                "role": "unknown",
                "password1": "A-strong-test-password-472!",
                "password2": "A-strong-test-password-472!",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("role", form.errors)
        self.assertFalse(User.objects.filter(email="invalid-admin-user@example.com").exists())
