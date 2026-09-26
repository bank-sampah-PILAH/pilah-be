"""Module boundary guard for the modular monolith.

Rules (loose phase — commit "tighten guard" removes the api.models allowance
once models live in apps/*/models.py):
- apps/<bc>/* may import: stdlib, django, DRF, third-party infra, shared_kernel,
  api.models (temporary), its own package, another BC via apps.<bc>.api, or
  another BC's serializers (shared DTOs — presentation reuse, no logic).
- apps/<bc>/* may NOT import api.services/views/serializers/permissions/etc.
  (moved homes must be used) nor another BC's models/services/views.
"""

import ast
from pathlib import Path

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parent.parent
APPS_ROOT = REPO_ROOT / "apps"

# ponytail: temporary — models still live in api/models.py; the tighten commit
# drops api.models from this set so apps only touch their own models + facades.
ALLOWED_API_MODULES = {"api.models"}

FORBIDDEN_API_MODULES = {
    "api.services",
    "api.views",
    "api.serializers",
    "api.permissions",
    "api.pagination",
    "api.exceptions",
    "api.validators",
    "api.health",
}


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


class ArchitectureTest(SimpleTestCase):
    def test_app_boundaries(self) -> None:
        violations: list[str] = []
        if not APPS_ROOT.exists():
            return
        for path in sorted(APPS_ROOT.rglob("*.py")):
            context = path.relative_to(APPS_ROOT).parts[0]
            for module in _imported_modules(path):
                if module in FORBIDDEN_API_MODULES or module.startswith(
                    tuple(f"{m}." for m in FORBIDDEN_API_MODULES)
                ):
                    violations.append(f"{path}: forbidden {module}")
                elif module == "api" or module.startswith("api."):
                    if module not in ALLOWED_API_MODULES and not module.startswith(
                        tuple(f"{m}." for m in ALLOWED_API_MODULES)
                    ):
                        violations.append(f"{path}: forbidden {module}")
                elif module == "apps" or module.startswith("apps."):
                    parts = module.split(".")
                    if (
                        len(parts) > 2
                        and parts[1] != context
                        and parts[2] not in ("api", "serializers")
                    ):
                        violations.append(f"{path}: cross-context {module}")
        self.assertEqual(violations, [])
