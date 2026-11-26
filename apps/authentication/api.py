"""Public port of the authentication context.

Other contexts (bank_sampah, nasabah) need the current user's next-step hint
and nasabah signup; they route through here instead of importing the
authentication services directly, so the internals (refresh flow, flag sync)
can change without cross-context edits.
"""

from typing import Any, Mapping

from api.models import Nasabah, User
from apps.authentication.services import AuthService, OnboardingService

__all__ = ["lock_for_onboarding", "register_nasabah", "user_state_hint"]


def lock_for_onboarding(user: User) -> None:
    """Lock and reload the account row before an onboarding write checks its
    role, so a concurrent role change can't slip in between (PIL-451).
    Call inside ``transaction.atomic()``."""
    OnboardingService.lock_account(user)


def user_state_hint(user: User) -> str:
    """Same contract as `user_state`: the next onboarding step for the user."""
    return AuthService.user_state(user)


def register_nasabah(user: User, payload: Mapping[str, Any]) -> Nasabah:
    """Create the Nasabah record + saldo for a self-signing nasabah user."""
    return OnboardingService.register_nasabah(user, payload)
