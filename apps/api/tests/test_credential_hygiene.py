"""Repository-level regression tests: no database credential is committed, and
every consumer fails closed without the untracked root .env
(docs/operations/database-credentials.md)."""

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

# scheme://user:password@host — the password group excludes interpolation and
# template syntax, so only literal credentials match.
DSN_WITH_PASSWORD = re.compile(
    r"postgres(?:ql)?(?:\+\w+)?://(?P<user>[A-Za-z0-9_.\-]+):(?P<password>[^@\s\"'`/]+)@(?P<host>[A-Za-z0-9_.\-\[\]:]+)"
)
TEMPLATE_PASSWORD = re.compile(r"^(?:\$\{.*|\$\(.*|\{.*\}|<[^>]+>|%s|\*+|\.\.\.|x)$")
# Unit tests use unresolvable hosts (RFC 6761 .invalid) or generated values.
SAFE_TEST_HOST = re.compile(r"(^|\.)invalid$|\.example\.com$|amazonaws\.com$")


def _tracked_text_files() -> list[Path]:
    output = subprocess.run(
        # Tracked plus new, not-ignored files: catches a credential before commit.
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        capture_output=True,
        check=True,
    ).stdout.decode()
    files = []
    for name in output.split("\0"):
        path = REPO_ROOT / name
        if name and path.is_file() and not name.endswith((".lock", ".svg", ".ico", ".hcl")):
            files.append(path)
    return files


def test_no_tracked_file_contains_a_literal_database_credential() -> None:
    offenders = []
    for path in _tracked_text_files():
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in DSN_WITH_PASSWORD.finditer(content):
            password, host = match["password"], match["host"].split(":")[0]
            if TEMPLATE_PASSWORD.match(password) or SAFE_TEST_HOST.search(host):
                continue
            if path.is_relative_to(REPO_ROOT / "apps/api/tests") and "{" in password:
                continue  # f-string with a generated or canary value
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {match['user']}@{host}")

    assert offenders == [], "literal database credentials committed"


def test_no_script_defaults_a_password() -> None:
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _tracked_text_files()
        if path.suffix in {".sh", ".yaml", ".yml", ""} or path.name == "Makefile"
        # `${X_PASSWORD:-literal}` or `X_PASSWORD=literal`; a `:-$(...)` lookup is fine.
        if re.search(
            r"PASSWORD[A-Z_]*:-[^$}]|PASSWORD[A-Z_]*=[A-Za-z0-9_]+\s*$", path.read_text(), re.M
        )
    ]

    assert offenders == []


def _compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((REPO_ROOT / "compose.yaml").read_text())
    return loaded


def _required_variable(value: str, name: str) -> bool:
    return re.fullmatch(rf"\$\{{{name}:\?[^}}]+\}}", value) is not None


def test_compose_database_passwords_are_required_interpolations() -> None:
    services = _compose()["services"]

    assert _required_variable(
        services["db"]["environment"]["POSTGRES_PASSWORD"], "HEROOS_DB_ADMIN_PASSWORD"
    )
    runtime_url = services["api"]["environment"]["DATABASE_URL"]
    match = re.fullmatch(r"postgresql\+psycopg://heroos_app:(.+)@db:5432/heroos", runtime_url)
    assert match is not None
    assert _required_variable(match[1], "HEROOS_DB_APP_PASSWORD")


def test_compose_api_never_receives_the_admin_credential() -> None:
    api = _compose()["services"]["api"]

    assert "MIGRATION_DATABASE_URL" not in api["environment"]
    assert "HEROOS_DB_ADMIN_PASSWORD" not in str(api)
    assert "env_file" not in api


def test_compose_ports_bind_to_loopback_only() -> None:
    for name, service in _compose()["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), name


def test_compose_refuses_to_start_without_credentials(tmp_path: Path) -> None:
    # `docker compose config` resolves interpolation without touching any
    # container. Run from an empty project directory so no .env is read.
    docker = subprocess.run(["docker", "compose", "version"], capture_output=True, check=False)
    if docker.returncode != 0:
        pytest.skip("docker compose not available")
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(tmp_path),
            "-f",
            str(REPO_ROOT / "compose.yaml"),
            "config",
            "--quiet",
        ],  # fmt: skip
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)},
        timeout=60,
        check=False,
    )

    assert result.returncode != 0
    assert "HEROOS_DB_" in result.stderr
    assert "is not set - run make env-init" in result.stderr


def test_ci_generates_credentials_before_starting_postgres() -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text())
    for name, job in workflow["jobs"].items():
        commands = [step.get("run", "") for step in job["steps"]]
        starts = [i for i, run in enumerate(commands) if "docker compose up" in run]
        if not starts:
            continue
        generates = [i for i, run in enumerate(commands) if "make env-init" in run]
        assert generates and generates[0] < starts[0], name
        assert "::add-mask::" in commands[generates[0]], name


def test_verification_suites_never_manage_the_shared_runtime_role() -> None:
    for script in ("verify-tenant-isolation.sh", "verify-backup-restore.sh"):
        content = (REPO_ROOT / "scripts" / script).read_text()
        assert "new_disposable_runtime_role" in content, script
        assert "assert_live_runtime_role_unchanged" in content, script
        assert not re.search(r"RUNTIME_LOGIN=heroos_app\b(?!_)", content), script
    for conftest in ("tenant_isolation", "recovery"):
        content = (REPO_ROOT / f"apps/api/tests/{conftest}/conftest.py").read_text()
        assert '"heroos_app")' not in content, conftest
        assert "heroos_app_t_" in content, conftest
