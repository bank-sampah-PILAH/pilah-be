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

# PIL-428: TransaksiQuerySet.tercatat() is the one named rule for "setoran that
# still count"; every other read calls it instead of spelling out the status.
TERCATAT_RULE_HOME = APPS_ROOT / "ledger" / "models.py"


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def _names_transaksi_tercatat(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "TERCATAT"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "Status"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "Transaksi"
    )


def _spelled_out_tercatat_filters(path: Path) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"filter", "exclude"}
        ):
            continue
        for keyword in node.keywords:
            if _names_transaksi_tercatat(keyword.value) or (keyword.arg or "").endswith(
                "transaksi__status"
            ):
                lines.append(keyword.value.lineno)
    return lines


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
                    # Depth 2 (`from apps.other import x`) reaches past the
                    # port: cross-context imports must name apps.<bc>.api or
                    # apps.<bc>.serializers explicitly.
                    if parts[1] != context and (
                        len(parts) < 3 or parts[2] not in ("api", "serializers")
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

    def test_counted_setoran_are_read_through_tercatat(self) -> None:
        violations: list[str] = []
        for path in sorted(APPS_ROOT.rglob("*.py")):
            if path == TERCATAT_RULE_HOME or path.name.startswith("test_"):
                continue
            violations.extend(
                f"{path.relative_to(REPO_ROOT)}:{line}"
                for line in _spelled_out_tercatat_filters(path)
            )
        self.assertEqual(violations, [])
