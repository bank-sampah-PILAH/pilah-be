"""Jaga agar nama header kustom hanya hidup di ``shared_kernel/http_headers.py``.

``tests/regression/identity/test_cors.py`` menjaga satu arah: setiap entri
registry wajib lolos preflight. Arah sebaliknya tidak terjaga di sana, dan
itulah celah yang membuat cacat PIL-354 bisa terjadi: sebuah view boleh saja
membaca ``request.headers.get("Header-Baru")`` tanpa pernah mendaftarkannya,
dan tidak ada apa pun yang gagal sampai klien browser mencobanya.

Modul ini memeriksa sumbernya, bukan perilakunya:

* nama yang sudah didefinisikan registry tidak boleh dieja ulang di tempat lain;
* setiap pembacaan header harus berujung pada konstanta registry yang terdaftar,
  atau pada header bawaan yang memang selalu diizinkan preflight.

Pemeriksaan berbasis AST, mengikuti pola ``tests/test_architecture.py``.
"""

import ast
from pathlib import Path

from corsheaders.defaults import default_headers
from django.test import SimpleTestCase

from shared_kernel import http_headers
from shared_kernel.http_headers import HEADER_PERMINTAAN_KUSTOM

REPO_ROOT = Path(__file__).resolve().parent.parent
SCANNED_ROOTS = ("api", "apps", "config", "shared_kernel")
REGISTRY_FILE = REPO_ROOT / "shared_kernel" / "http_headers.py"

# Every header name the registry module defines, by value.
REGISTERED_NAMES = {
    value
    for name, value in vars(http_headers).items()
    if not name.startswith("_") and isinstance(value, str)
}

DEFAULT_HEADERS = {header.lower() for header in default_headers}
REGISTERED_REQUEST_HEADERS = {header.lower() for header in HEADER_PERMINTAAN_KUSTOM}


def _first_party_files() -> list[Path]:
    """Source files that must route header names through the registry.

    Tests are excluded on purpose: a test may spell a header name to prove
    something about it. Migrations are generated.
    """
    files: list[Path] = []
    for root in SCANNED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            if path == REGISTRY_FILE or "migrations" in path.parts:
                continue
            if path.name.startswith("test_") or path.name == "tests.py":
                continue
            files.append(path)
    return files


def _header_read_arguments(tree: ast.AST) -> list[ast.expr]:
    """The argument node of every ``<...>.headers.get(x)`` and ``.headers[x]``."""
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "headers"
            and node.args
        ):
            found.append(node.args[0])
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "headers"
        ):
            found.append(node.slice)
    return found


class CustomHeaderRegistryTests(SimpleTestCase):
    def test_registered_header_names_are_not_spelled_out_elsewhere(self) -> None:
        violations: list[str] = []
        for path in _first_party_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value in REGISTERED_NAMES:
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                        f'"{node.value}" is defined in shared_kernel/http_headers.py; '
                        "import the constant instead of repeating the name"
                    )
        self.assertEqual(violations, [])

    def test_every_header_the_api_reads_is_registered(self) -> None:
        violations: list[str] = []
        for path in _first_party_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for argument in _header_read_arguments(tree):
                where = f"{path.relative_to(REPO_ROOT)}:{argument.lineno}"
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    if argument.value.lower() not in DEFAULT_HEADERS:
                        violations.append(
                            f'{where}: reads custom header "{argument.value}" as a literal; '
                            "add it to HEADER_PERMINTAAN_KUSTOM and read it through the constant, "
                            "or the browser preflight will refuse the request"
                        )
                elif isinstance(argument, ast.Name):
                    value = getattr(http_headers, argument.id, None)
                    if value is None:
                        violations.append(
                            f"{where}: reads a header through unknown name {argument.id}; "
                            "header names come from shared_kernel/http_headers.py"
                        )
                    elif value.lower() not in REGISTERED_REQUEST_HEADERS:
                        violations.append(
                            f"{where}: {argument.id} is not listed in HEADER_PERMINTAAN_KUSTOM, "
                            "so nothing guarantees it survives preflight"
                        )
        self.assertEqual(violations, [])
