"""Module boundary guard for the modular monolith.

Final rules:
- apps/<bc>/* may import: stdlib, django, DRF, third-party infra, shared_kernel,
  api.models (the Django app's model registry — stable, migration-safe), its own
  package, another BC via apps.<bc>.api, or another BC's serializers (DTOs).
- apps/<bc>/* may NOT import any other api.* module nor another BC's
  models/services/views.
- shared_kernel/* may NOT import api.* (except api.models) or apps.*.
"""

import ast
from pathlib import Path

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parent.parent
APPS_ROOT = REPO_ROOT / "apps"
KERNEL_ROOT = REPO_ROOT / "shared_kernel"

# api.models is the model registry aggregator, not logic — the one api.*
# import the domain layer is allowed to keep.
ALLOWED_API_MODULES = {"api.models"}


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def _is_allowed_api(module: str) -> bool:
    return module in ALLOWED_API_MODULES or module.startswith(
        tuple(f"{m}." for m in ALLOWED_API_MODULES)
    )


class ArchitectureTest(SimpleTestCase):
    def test_app_boundaries(self) -> None:
        violations: list[str] = []
        for path in sorted(APPS_ROOT.rglob("*.py")):
            context = path.relative_to(APPS_ROOT).parts[0]
            for module in _imported_modules(path):
                if module == "api" or module.startswith("api."):
                    if not _is_allowed_api(module):
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

    def test_shared_kernel_has_no_app_imports(self) -> None:
        violations: list[str] = []
        for path in sorted(KERNEL_ROOT.rglob("*.py")):
            for module in _imported_modules(path):
                if module == "apps" or module.startswith("apps."):
                    violations.append(f"{path}: kernel imports app {module}")
                elif (module == "api" or module.startswith("api.")) and not _is_allowed_api(module):
                    violations.append(f"{path}: kernel imports {module}")
        self.assertEqual(violations, [])
