"""Structural boundaries of M1-10B (ADR-008), checked on the source and the app.

- Only the operator CLI may reach the identity provisioning code.
- The application exposes no mutating HTTP route at all in M1-10B, so no
  request can provision, grant, suspend or revoke anything.
"""

import ast
from pathlib import Path

from app.core.config import Settings
from app.main import create_app

API_ROOT = Path(__file__).resolve().parents[1]
APP = API_ROOT / "app"


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_only_the_identity_package_and_cli_reach_provisioning_code() -> None:
    offenders = {
        str(path.relative_to(API_ROOT))
        for path in APP.rglob("*.py")
        if "identity" not in path.relative_to(APP).parts[:1]
        and any(name.startswith(("app.identity", "scripts")) for name in _imports(path))
    }
    assert offenders == set()


def test_operator_scope_is_used_only_by_the_identity_service_and_cli() -> None:
    users = {
        str(path.relative_to(API_ROOT))
        for path in (*APP.rglob("*.py"), *(API_ROOT / "scripts").rglob("*.py"))
        if "app.identity.operator" in _imports(path)
    }
    assert users == {"app/identity/service.py", "scripts/manage_identities.py"}


def test_application_has_no_mutating_routes() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        heroos_env="development",
        database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
    )
    methods = {
        method
        for route in create_app(settings).routes
        for method in (getattr(route, "methods", None) or set())
    }
    assert methods <= {"GET", "HEAD"}
