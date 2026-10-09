"""Local credential tooling (scripts.db_credentials): generated values only,
private files, no value ever printed, and `apply` changes passwords only."""

import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from scripts import db_credentials as tool
from scripts.db_credentials import (
    ADMIN_PASSWORD,
    APP_PASSWORD,
    DATABASE_URL,
    DEV_AUTH_SECRET,
    MIGRATION_DATABASE_URL,
    CredentialError,
    check_env_file,
    command_apply,
    command_init,
    command_rotate,
    parse_env,
    render_env,
)
from scripts.scram import generate_password

EXAMPLE = """# Template comment
HEROOS_ENV=development
HEROOS_DB_ADMIN_PASSWORD=
HEROOS_DB_APP_PASSWORD=
DATABASE_URL=
MIGRATION_DATABASE_URL=
HEROOS_AUTH_PROVIDER=development
HEROOS_DEV_AUTH_SECRET=
"""
SECRET_KEYS = (ADMIN_PASSWORD, APP_PASSWORD, DEV_AUTH_SECRET)


@pytest.fixture
def example(tmp_path: Path) -> Path:
    path = tmp_path / "template.env"
    path.write_text(EXAMPLE)
    return path


@pytest.fixture
def env_file(tmp_path: Path, example: Path) -> Path:
    path = tmp_path / "project" / ".env"
    path.parent.mkdir()
    command_init(path, example, 5433)
    return path


def _values(path: Path) -> dict[str, str]:
    return parse_env(path.read_text())[0]


def _secrets(path: Path) -> list[str]:
    values = _values(path)
    return [values[key] for key in SECRET_KEYS if values.get(key)]


def _run_check(path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = tool.main(["--env-file", str(path), "check"])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _set(path: Path, **updates: str) -> None:
    path.write_text(render_env(path.read_text(), updates))


# init / check -------------------------------------------------------------------


def test_init_creates_private_file_with_generated_values(
    env_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    values = _values(env_file)
    assert values["HEROOS_ENV"] == "development"  # template lines preserved
    assert len({values[key] for key in SECRET_KEYS}) == 3
    assert values[DATABASE_URL].startswith("postgresql+psycopg://heroos_app:")
    assert values[MIGRATION_DATABASE_URL].endswith("@localhost:5433/heroos")

    code, output = _run_check(env_file, capsys)

    assert code == 0, output
    assert "FAIL" not in output
    assert "SKIP  git: not inside a Git work tree" in output
    for value in _secrets(env_file):
        assert value not in output


def test_init_output_contains_no_values(
    tmp_path: Path, example: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / ".env"
    command_init(path, example, 5433)

    output = capsys.readouterr().out
    for value in _secrets(path):
        assert value not in output


def test_init_never_overwrites(env_file: Path, example: Path) -> None:
    before = env_file.read_text()

    with pytest.raises(CredentialError, match="never overwritten"):
        command_init(env_file, example, 5433)

    assert env_file.read_text() == before


def _weak(path: Path) -> None:
    _set(path, **{APP_PASSWORD: "heroos_app_password"})


def _mismatch(path: Path) -> None:
    _set(path, **{APP_PASSWORD: generate_password()})


def _same_passwords(path: Path) -> None:
    admin = _values(path)[ADMIN_PASSWORD]
    _set(
        path,
        **{
            APP_PASSWORD: admin,
            DATABASE_URL: f"postgresql+psycopg://heroos_app:{admin}@localhost:5433/heroos",
        },
    )


def _admin_as_runtime(path: Path) -> None:
    _set(path, **{DATABASE_URL: _values(path)[MIGRATION_DATABASE_URL]})


def _remote_host(path: Path) -> None:
    app = _values(path)[APP_PASSWORD]
    _set(path, **{DATABASE_URL: f"postgresql+psycopg://heroos_app:{app}@db.example.com/heroos"})


def _duplicate(path: Path) -> None:
    path.write_text(path.read_text() + f"{APP_PASSWORD}={generate_password()}\n")


def _dev_secret_reuse(path: Path) -> None:
    _set(path, **{DEV_AUTH_SECRET: _values(path)[ADMIN_PASSWORD]})


def _readable(path: Path) -> None:
    path.chmod(0o644)


def _missing_url(path: Path) -> None:
    _set(path, **{MIGRATION_DATABASE_URL: ""})


@pytest.mark.parametrize(
    ("mutate", "failing"),
    [
        pytest.param(_readable, "file-permissions", id="world-readable"),
        pytest.param(_weak, APP_PASSWORD, id="non-generated-password"),
        pytest.param(_mismatch, DATABASE_URL, id="url-password-mismatch"),
        pytest.param(_same_passwords, "distinct-passwords", id="admin-equals-runtime"),
        pytest.param(_admin_as_runtime, DATABASE_URL, id="runtime-url-uses-admin-role"),
        pytest.param(_remote_host, DATABASE_URL, id="non-local-host"),
        pytest.param(_duplicate, APP_PASSWORD, id="duplicate-key"),
        pytest.param(_dev_secret_reuse, DEV_AUTH_SECRET, id="dev-secret-reuses-db-password"),
        pytest.param(_missing_url, MIGRATION_DATABASE_URL, id="missing-url"),
    ],
)
def test_check_fails_closed_without_printing_values(
    env_file: Path,
    capsys: pytest.CaptureFixture[str],
    mutate: Callable[[Path], None],
    failing: str,
) -> None:
    mutate(env_file)

    code, output = _run_check(env_file, capsys)

    assert code == 1
    assert f"FAIL  {failing}" in output
    for value in [*_secrets(env_file), "heroos_app_password"]:
        assert value not in output
    assert "postgresql+psycopg://" not in output


def test_check_reports_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, output = _run_check(tmp_path / ".env", capsys)

    assert code == 1
    assert "FAIL  file" in output


def _git(directory: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(directory), *arguments], check=True, capture_output=True)


def test_check_requires_env_file_ignored_and_untracked(
    env_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = env_file.parent
    _git(project, "init", "-q")
    (project / ".gitignore").write_text(".env\n")

    code, output = _run_check(env_file, capsys)
    assert code == 0, output
    assert "OK    git-ignored" in output
    assert "OK    git-untracked" in output

    _git(project, "add", "-f", ".env")
    code, output = _run_check(env_file, capsys)
    assert code == 1
    assert "FAIL  git-untracked" in output


def test_check_refuses_env_file_not_ignored(
    env_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(env_file.parent, "init", "-q")

    code, output = _run_check(env_file, capsys)

    assert code == 1
    assert "FAIL  git-ignored" in output


# rotate ------------------------------------------------------------------------------


@pytest.fixture
def backup_dir(tmp_path: Path) -> Path:
    path = tmp_path / "backups"
    path.mkdir(mode=0o700)
    return path


def test_rotate_backs_up_and_replaces_only_database_credentials(
    env_file: Path, backup_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _set(env_file, HEROOS_LOCAL_STORAGE_ROOT="/srv/objects")
    before_content = env_file.read_text()
    before = _values(env_file)

    command_rotate(env_file, backup_dir, dev_auth_secret=False)

    after = _values(env_file)
    for key in (ADMIN_PASSWORD, APP_PASSWORD, DATABASE_URL, MIGRATION_DATABASE_URL):
        assert after[key] != before[key], key
    assert after[DEV_AUTH_SECRET] == before[DEV_AUTH_SECRET]
    assert after["HEROOS_LOCAL_STORAGE_ROOT"] == "/srv/objects"
    assert "# Template comment" in env_file.read_text()
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600

    (backup,) = backup_dir.iterdir()
    assert backup.name.startswith("env.pre-rotation.")
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert backup.read_text() == before_content

    output = capsys.readouterr().out
    for value in [*_secrets(env_file), before[ADMIN_PASSWORD], before[APP_PASSWORD]]:
        assert value not in output
    assert _run_check(env_file, capsys)[0] == 0


def test_rotate_keeps_port_and_optionally_rotates_dev_secret(
    tmp_path: Path, example: Path, backup_dir: Path
) -> None:
    path = tmp_path / ".env"
    command_init(path, example, 55433)
    secret = _values(path)[DEV_AUTH_SECRET]

    command_rotate(path, backup_dir, dev_auth_secret=True)

    assert _values(path)[DEV_AUTH_SECRET] != secret
    assert "@localhost:55433/heroos" in _values(path)[DATABASE_URL]


def test_rotate_adds_missing_managed_keys(tmp_path: Path, backup_dir: Path) -> None:
    # An older .env that only has the URLs (as before this change).
    path = tmp_path / ".env"
    path.write_text("HEROOS_ENV=development\nDATABASE_URL=x\nMIGRATION_DATABASE_URL=y\n")
    path.chmod(0o600)

    command_rotate(path, backup_dir, dev_auth_secret=False)

    values = _values(path)
    assert values[ADMIN_PASSWORD] and values[APP_PASSWORD]
    assert check_env_file(path)[0].ok


@pytest.mark.parametrize("mode", [0o755, 0o750, 0o701])
def test_rotate_refuses_non_private_backup_directory(
    env_file: Path, tmp_path: Path, mode: int
) -> None:
    directory = tmp_path / "open"
    directory.mkdir()
    directory.chmod(mode)
    before = env_file.read_text()

    with pytest.raises(CredentialError, match="mode 0700"):
        command_rotate(env_file, directory, dev_auth_secret=False)

    assert env_file.read_text() == before
    assert not list(directory.iterdir())


def test_rotate_refuses_backup_directory_inside_repository(env_file: Path) -> None:
    with pytest.raises(CredentialError, match="outside the repository"):
        command_rotate(env_file, tool.REPO_ROOT / "docs", dev_auth_secret=False)


def test_rotate_requires_existing_env_file(tmp_path: Path, backup_dir: Path) -> None:
    with pytest.raises(CredentialError, match="make env-init"):
        command_rotate(tmp_path / ".env", backup_dir, dev_auth_secret=False)


# apply ---------------------------------------------------------------------------------

ROLE_STATE = "heroos|t|t|t|t|t|t|t|-1|-|-|t\nheroos_app|f|t|f|f|t|f|f|-1|-|heroos_app_runtime|t\n"


class FakePsql:
    def __init__(self, states: list[str]) -> None:
        self.states = states
        self.statements: list[str] = []

    def __call__(self, sql: str) -> str:
        self.statements.append(sql)
        if sql.lstrip().startswith("SELECT"):
            return self.states.pop(0)
        return ""


@pytest.fixture
def repository_env(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(tool, "DEFAULT_ENV_FILE", env_file)
    return env_file


@pytest.fixture
def logins(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    attempts: list[tuple[str, bool]] = []
    monkeypatch.setattr(tool, "_verify_login", lambda url, runtime: attempts.append((url, runtime)))
    return attempts


def test_apply_requires_confirmation(repository_env: Path) -> None:
    psql = FakePsql([])

    with pytest.raises(CredentialError, match="--confirm"):
        command_apply(repository_env, confirm=False, run=psql)

    assert psql.statements == []


def test_apply_only_uses_the_repository_env_file(env_file: Path, tmp_path: Path) -> None:
    other = tmp_path / "other.env"
    other.write_text(env_file.read_text())
    psql = FakePsql([])

    with pytest.raises(CredentialError, match="repository .env only"):
        command_apply(other, confirm=True, run=psql)

    assert psql.statements == []


def test_apply_refuses_failing_env_check_before_touching_database(
    repository_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # e.g. an old .env backup holding the retired development defaults.
    _weak(repository_env)
    psql = FakePsql([ROLE_STATE, ROLE_STATE])

    with pytest.raises(CredentialError, match="nothing was changed"):
        command_apply(repository_env, confirm=True, run=psql)

    assert psql.statements == []
    assert "heroos_app_password" not in capsys.readouterr().out


def test_apply_sets_verifiers_in_one_transaction_and_verifies_logins(
    repository_env: Path,
    logins: list[tuple[str, bool]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    psql = FakePsql([ROLE_STATE, ROLE_STATE])

    command_apply(repository_env, confirm=True, run=psql)

    values = _values(repository_env)
    (change,) = [sql for sql in psql.statements if "ALTER ROLE" in sql]
    assert change.startswith("BEGIN;") and change.rstrip().endswith("COMMIT;")
    assert change.count("PASSWORD 'SCRAM-SHA-256$4096:") == 2
    assert "ALTER ROLE heroos PASSWORD" in change and "ALTER ROLE heroos_app PASSWORD" in change
    for value in _secrets(repository_env):
        assert value not in change
    assert logins == [(values[MIGRATION_DATABASE_URL], False), (values[DATABASE_URL], True)]

    output = capsys.readouterr()
    for value in [*_secrets(repository_env), "SCRAM-SHA-256$"]:
        assert value not in output.out + output.err


def test_apply_detects_role_attribute_changes(
    repository_env: Path, logins: list[tuple[str, bool]]
) -> None:
    changed = ROLE_STATE.replace("heroos_app|f|t|f|f|t|f|f", "heroos_app|f|t|f|f|t|f|t")
    psql = FakePsql([ROLE_STATE, changed])

    with pytest.raises(CredentialError, match="changed unexpectedly"):
        command_apply(repository_env, confirm=True, run=psql)

    assert logins == []


def test_apply_refuses_missing_roles(repository_env: Path) -> None:
    psql = FakePsql(["heroos|t|t|t|t|t|t|t|-1|-|-|t\n"])

    with pytest.raises(CredentialError, match="heroos_app do not exist"):
        command_apply(repository_env, confirm=True, run=psql)

    assert not [sql for sql in psql.statements if "ALTER ROLE" in sql]


def test_compose_psql_redacts_verifiers_from_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class Failed:
        returncode = 1
        stdout = ""
        stderr = (
            "ERROR:  syntax error\n"
            "LINE 1: ALTER ROLE heroos PASSWORD 'SCRAM-SHA-256$4096:abc$def:ghi';"
        )

    monkeypatch.setattr(tool.subprocess, "run", lambda *_, **__: Failed())

    with pytest.raises(CredentialError) as exc_info:
        tool.compose_psql("SELECT 1")

    assert "abc$def" not in str(exc_info.value)
    assert "SCRAM-SHA-256$<redacted>" in str(exc_info.value)


def test_render_env_preserves_unmanaged_lines_and_drops_duplicates() -> None:
    content = "# c\nA=1\nexport B=2\nA=3\nC='x'\n"

    rendered = render_env(content, {"A": "new", "D": "d"})

    assert rendered.splitlines()[:4] == ["# c", "A=new", "export B=2", "C='x'"]
    assert parse_env(rendered) == ({"A": "new", "B": "2", "C": "x", "D": "d"}, set())
