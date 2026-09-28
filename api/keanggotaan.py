"""Compatibility shim: the module moved to apps.membership.keanggotaan (PIL-48)."""

from apps.membership.keanggotaan import (  # noqa: F401
    FIELD_PROFIL_GLOBAL,
    profil_terkunci,
    punya_akun,
)

__all__ = ["FIELD_PROFIL_GLOBAL", "profil_terkunci", "punya_akun"]
