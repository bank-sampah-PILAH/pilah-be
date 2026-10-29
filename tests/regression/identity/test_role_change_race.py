"""PIL-451, review P1 on #137: a role change racing an onboarding write.

Each registration path checks the account's role and then, later, links a
bank sampah or a membership. A role change that commits in between would
leave, say, a nasabah account linked to a bank. Both sides must serialize on
the account row, so the role change waits and then sees what was linked.

Real row locks need PostgreSQL (SQLite has none), so this runs where CI runs.
"""

import threading
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from unittest import skipUnless
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from api.models import BankSampah, Nasabah, User, UserRoleChangeLog
from apps.authentication.services import AuthService, AuthServiceError, OnboardingService
from apps.bank_sampah.services import BankOnboardingService

WAIT = 5.0


@skipUnless(connection.vendor == "postgresql", "Row locks need PostgreSQL")
class RoleChangeRaceTests(TransactionTestCase):
    def _race(
        self,
        user: User,
        register: Callable[[User], Any],
        pause_on: tuple[type, str],
        new_role: str,
    ) -> dict[str, Any]:
        """Runs `register` in thread A, paused right after its role check, then
        a role change in thread B, then lets A finish. Returns B's outcome."""
        reached, proceed = threading.Event(), threading.Event()
        owner, method = pause_on
        original = getattr(owner, method)

        def paused(*args: Any, **kwargs: Any) -> Any:
            if threading.current_thread().name == "registration":
                reached.set()
                proceed.wait(WAIT)
            return original(*args, **kwargs)

        outcome: dict[str, Any] = {}

        def registration() -> None:
            try:
                register(User.objects.get(pk=user.pk))
            finally:
                connection.close()

        def role_change() -> None:
            try:
                AuthService.change_role(User.objects.get(pk=user.pk), new_role)
                outcome["changed"] = True
            except AuthServiceError as exc:
                outcome["refused"] = exc.code
            finally:
                connection.close()

        with patch.object(owner, method, paused):
            a = threading.Thread(target=registration, name="registration")
            a.start()
            self.assertTrue(reached.wait(WAIT), "registration never reached its write")
            b = threading.Thread(target=role_change, name="role-change")
            b.start()
            b.join(1.0)
            outcome["waited_for_registration"] = b.is_alive()
            proceed.set()
            a.join(WAIT)
            b.join(WAIT)
        return outcome

    def _assert_role_kept(self, user: User, role: str, outcome: dict[str, Any]) -> None:
        user.refresh_from_db()
        self.assertEqual(user.role, role, outcome)
        self.assertTrue(outcome["waited_for_registration"], outcome)
        self.assertEqual(outcome.get("refused"), "role_locked", outcome)
        self.assertFalse(UserRoleChangeLog.objects.filter(user=user).exists())

    def test_a_role_change_waits_for_a_bank_registration_in_progress(self) -> None:
        user = User.objects.create_user(email="race-bank@example.com", role=User.Role.PENGELOLA)
        payload = {
            "nama": "Bank Balapan",
            "alamat": "Depok",
            "kota": "Depok",
            "no_hp_pic": "+628111111111",
            "foto_kegiatan": SimpleUploadedFile("f.png", b"png", content_type="image/png"),
        }

        outcome = self._race(
            user,
            lambda u: BankOnboardingService.register_bank_sampah(u, payload),
            (BankSampah, "save"),
            User.Role.NASABAH,
        )

        self._assert_role_kept(user, User.Role.PENGELOLA, outcome)
        self.assertIsNotNone(user.bank_sampah_id)

    def test_a_role_change_waits_for_a_membership_application_in_progress(self) -> None:
        bank = BankSampah.objects.create(
            nama="Bank Aktif", alamat="Depok", no_hp_pic="+628111111111"
        )
        user = User.objects.create_user(
            email="race-member@example.com",
            role=User.Role.NASABAH,
            alamat="Jl. Mawar",
            no_hp="+628111111112",
        )

        outcome = self._race(
            user,
            lambda u: OnboardingService.register_nasabah(u, {"bank_sampah_id": bank.id}),
            (Nasabah, "save"),
            User.Role.PENGELOLA,
        )

        self._assert_role_kept(user, User.Role.NASABAH, outcome)
        self.assertTrue(Nasabah.objects.filter(user=user, bank_sampah=bank).exists())

    def test_a_role_change_waits_for_an_invite_being_accepted(self) -> None:
        bank = BankSampah.objects.create(
            nama="Bank Pengundang",
            alamat="Depok",
            no_hp_pic="+628111111111",
            invite_token="race-token",
            invite_token_expires=timezone.now() + timedelta(days=1),
        )
        user = User.objects.create_user(email="race-invite@example.com", role=User.Role.PENGELOLA)

        outcome = self._race(
            user,
            lambda u: BankOnboardingService.accept_invite(u, "race-token"),
            (User, "save"),
            User.Role.NASABAH,
        )

        self._assert_role_kept(user, User.Role.PENGELOLA, outcome)
        self.assertEqual(user.bank_sampah_id, bank.id)
