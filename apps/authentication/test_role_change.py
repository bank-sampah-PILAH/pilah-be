"""PIL-451: a Google account that picked the wrong role can pick again until
onboarding has committed anything for that role."""

from unittest.mock import Mock, patch

from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from api.models import BankSampah, Nasabah, User
from apps.authentication.services import AuthService, AuthServiceError

URL = "/api/v1/onboarding/role"


class RoleChangeTests(APITestCase):
    def _fresh(self, role: str = User.Role.PENGELOLA) -> User:
        return User.objects.create_user(email=f"{role}@example.com", nama="Baru", role=role)

    def test_an_unfinished_account_switches_role_and_gets_a_session_for_it(self) -> None:
        user = self._fresh(User.Role.PENGELOLA)
        self.client.force_authenticate(user)

        response = self.client.patch(URL, {"role": User.Role.NASABAH}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["user"]["role"], User.Role.NASABAH)
        self.assertEqual(response.data["next_step"], "complete_profile")
        self.assertEqual(AccessToken(response.data["access_token"])["role"], User.Role.NASABAH)
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.NASABAH)

    def test_every_registration_role_can_be_switched_to(self) -> None:
        # PIL-451: "Ganti peran berhasil sebelum onboarding selesai, untuk tiap
        # peran Google." Each target is reached from a different role.
        for start, target in (
            (User.Role.NASABAH, User.Role.PENGELOLA),
            (User.Role.PENGELOLA, User.Role.PENGELOLA_INDUK),
            (User.Role.PENGELOLA_INDUK, User.Role.NASABAH),
        ):
            with self.subTest(start=start, target=target):
                user = User.objects.create_user(
                    email=f"{start}-to-{target}@example.com", nama="Baru", role=start
                )
                self.client.force_authenticate(user)

                response = self.client.patch(URL, {"role": target}, format="json")

                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["user"]["role"], target)
                self.assertEqual(response.data["next_step"], "complete_profile")
                self.assertEqual(AccessToken(response.data["access_token"])["role"], target)
                user.refresh_from_db()
                self.assertEqual(user.role, target)
                self.assertEqual(
                    list(user.role_change_logs.values_list("from_role", "to_role")),
                    [(start, target)],
                )

    def test_the_role_is_kept_once_onboarding_has_committed_anything_for_it(self) -> None:
        bank = BankSampah.objects.create(
            nama="Bank Pending",
            alamat="Depok",
            no_hp_pic="+628111111111",
            status=BankSampah.Status.PENDING,
        )
        profiled = User.objects.create_user(
            email="profiled@example.com",
            nama="Lengkap",
            role=User.Role.PENGELOLA,
            is_profile_complete=True,
        )
        registered = User.objects.create_user(
            email="registered@example.com", nama="Daftar", role=User.Role.PENGELOLA
        )
        registered.bank_sampah = bank
        registered.save(update_fields=["bank_sampah"])
        # Linked on first login to a membership a pengurus entered for this email.
        member = self._fresh(User.Role.NASABAH)
        Nasabah.objects.create(
            user=member,
            bank_sampah=bank,
            nomor="NAS-001",
            nama="Anggota",
            alamat="Depok",
            no_hp="+628111111112",
        )

        for user, role in (
            (profiled, User.Role.NASABAH),
            (registered, User.Role.NASABAH),
            (member, User.Role.PENGELOLA),
        ):
            with self.subTest(user=user.email):
                previous = user.role
                self.client.force_authenticate(user)

                response = self.client.patch(URL, {"role": role}, format="json")

                self.assertEqual(response.status_code, 409, response.data)
                self.assertEqual(response.data["code"], "role_locked")
                user.refresh_from_db()
                self.assertEqual(user.role, previous)

    def test_only_a_registering_account_may_pick_and_only_a_registration_role(self) -> None:
        anonymous = self.client.patch(URL, {"role": User.Role.NASABAH}, format="json")
        self.assertEqual(anonymous.status_code, 401, anonymous.data)

        admin = self._fresh(User.Role.SUPERADMIN)
        self.client.force_authenticate(admin)
        demoted = self.client.patch(URL, {"role": User.Role.NASABAH}, format="json")
        self.assertEqual(demoted.status_code, 403, demoted.data)

        user = self._fresh(User.Role.NASABAH)
        self.client.force_authenticate(user)
        escalated = self.client.patch(URL, {"role": User.Role.SUPERADMIN}, format="json")
        self.assertEqual(escalated.status_code, 422, escalated.data)
        self.assertIn("role", escalated.data["errors"])

        admin.refresh_from_db()
        user.refresh_from_db()
        self.assertEqual(admin.role, User.Role.SUPERADMIN)
        self.assertEqual(user.role, User.Role.NASABAH)

    def test_a_bank_registered_after_the_account_was_loaded_still_keeps_the_role(self) -> None:
        user = self._fresh(User.Role.PENGELOLA)
        # Loaded by this request before a parallel one registered a bank sampah.
        stale = User.objects.get(pk=user.pk)
        bank = BankSampah.objects.create(
            nama="Bank Baru",
            alamat="Depok",
            no_hp_pic="+628111111111",
            status=BankSampah.Status.PENDING,
        )
        User.objects.filter(pk=user.pk).update(bank_sampah=bank)

        with self.assertRaises(AuthServiceError) as refused:
            AuthService.change_role(stale, User.Role.NASABAH)

        self.assertEqual(refused.exception.code, "role_locked")
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.PENGELOLA)

    @patch("apps.authentication.services.google_id_token.verify_oauth2_token")
    def test_a_login_loaded_before_a_role_change_claims_no_membership_and_signs_in(
        self, verify: Mock
    ) -> None:
        # Review on #137: Google login claims a pengurus-entered membership.
        # The login read the account as nasabah, then a role change committed.
        # The claim must see the new role, link nothing, and still sign in,
        # not surface Nasabah.clean's ValidationError as a 401.
        user = User.objects.create_user(
            email="stale-login@example.com",
            nama="Ayu",
            role=User.Role.NASABAH,
            google_id="google-stale",
            email_verified=True,
        )
        bank = BankSampah.objects.create(nama="Bank", alamat="Depok", no_hp_pic="+628111111111")
        record = Nasabah.objects.create(
            bank_sampah=bank,
            nomor="NAS-0001",
            nama="Ayu",
            no_hp="+628111111113",
            email=user.email,
            alamat="Jl. Mawar",
        )
        stale = User.objects.get(pk=user.pk)
        User.objects.filter(pk=user.pk).update(role=User.Role.PENGELOLA)
        verify.return_value = {
            "sub": "google-stale",
            "email": user.email,
            "email_verified": True,
            "name": "Ayu",
        }

        with patch.object(AuthService, "_user_for_email", staticmethod(lambda _email: stale)):
            response = self.client.post("/api/v1/auth/google", {"id_token": "t"}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["user"]["role"], User.Role.PENGELOLA)
        record.refresh_from_db()
        self.assertIsNone(record.user_id)

    def test_each_change_is_recorded_and_nothing_else_is(self) -> None:
        user = self._fresh(User.Role.PENGELOLA)
        locked = User.objects.create_user(
            email="locked@example.com",
            nama="Lengkap",
            role=User.Role.PENGELOLA,
            is_profile_complete=True,
        )

        self.client.force_authenticate(user)
        self.client.patch(URL, {"role": User.Role.NASABAH}, format="json")
        same = self.client.patch(URL, {"role": User.Role.NASABAH}, format="json")
        self.client.force_authenticate(locked)
        self.client.patch(URL, {"role": User.Role.NASABAH}, format="json")

        self.assertEqual(same.status_code, 200, same.data)
        self.assertEqual(
            list(user.role_change_logs.values_list("from_role", "to_role")),
            [(User.Role.PENGELOLA, User.Role.NASABAH)],
        )
        self.assertIsNotNone(user.role_change_logs.get().created_at)
        self.assertFalse(locked.role_change_logs.exists())
