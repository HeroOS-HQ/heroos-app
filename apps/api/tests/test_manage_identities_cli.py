"""Operator CLI safeguards that need no database (scripts/manage_identities.py)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from scripts import manage_identities
from scripts.manage_identities import OperatorRefusal, build_parser, check_transport_policy

API_ROOT = Path(__file__).resolve().parents[1]


NO_ENV: dict[str, str] = {}


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://heroos_op_x@localhost:5433/heroos",
        "postgresql+psycopg://heroos_op_x@127.0.0.1/heroos",
        "postgresql+psycopg://heroos_op_x@[::1]:5433/heroos",
    ],
)
def test_literal_loopback_connections_need_no_tls(url: str) -> None:
    # Local Compose use: the published loopback port (127.0.0.1:5433).
    assert check_transport_policy(make_url(url), NO_ENV) is False


def test_loopback_with_verify_full_still_requires_an_encrypted_session() -> None:
    url = make_url("postgresql+psycopg://heroos_op_x@localhost/heroos?sslmode=verify-full")
    assert check_transport_policy(url, NO_ENV) is True


@pytest.mark.parametrize(
    "host",
    [
        # Network names that merely look local can resolve anywhere.
        "db",
        "postgres",
        "heroos-db",
        "localhost.example.test",
        "127.0.0.1.nip.io",
        "0.0.0.0",
        "127.0.0.2",
        "10.0.0.5",
        "db.example.test",
    ],
)
@pytest.mark.parametrize(
    "query",
    ["", "?sslmode=disable", "?sslmode=prefer", "?sslmode=require", "?sslmode=verify-ca"],
)
def test_every_other_host_requires_verify_full(host: str, query: str) -> None:
    url = make_url(f"postgresql+psycopg://heroos_op_x@{host}/heroos{query}")
    with pytest.raises(OperatorRefusal, match="verify-full"):
        check_transport_policy(url, NO_ENV)


@pytest.mark.parametrize("host", ["db", "db.example.test"])
def test_non_loopback_with_verify_full_is_accepted(host: str) -> None:
    url = make_url(f"postgresql+psycopg://heroos_op_x@{host}/heroos?sslmode=verify-full")
    assert check_transport_policy(url, NO_ENV) is True


@pytest.mark.parametrize(
    "query",
    [
        "?host=db.example.test",
        "?hostaddr=10.0.0.5",
        "?HostAddr=10.0.0.5",
        "?service=remote",
        "?servicefile=/tmp/x",
        "?sslmode=verify-full&host=db.example.test",
    ],
)
def test_query_parameters_cannot_redirect_the_connection(query: str) -> None:
    # SQLAlchemy passes query parameters to libpq: ?host= would override the
    # loopback host in the URL and skip TLS.
    url = make_url(f"postgresql+psycopg://heroos_op_x@localhost/heroos{query}")
    with pytest.raises(OperatorRefusal, match="must not set host"):
        check_transport_policy(url, NO_ENV)


@pytest.mark.parametrize("variable", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"])
@pytest.mark.parametrize("query", ["", "?sslmode=verify-full"])
def test_environment_cannot_redirect_a_loopback_connection(variable: str, query: str) -> None:
    url = make_url(f"postgresql+psycopg://heroos_op_x@localhost/heroos{query}")
    with pytest.raises(OperatorRefusal, match="redirect"):
        check_transport_policy(url, {variable: "x"})


def test_a_host_is_required() -> None:
    with pytest.raises(OperatorRefusal, match="host"):
        check_transport_policy(make_url("postgresql+psycopg://heroos_op_x@/heroos"), NO_ENV)


def test_missing_operator_url_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEROOS_OPERATOR_DATABASE_URL", raising=False)
    exit_code = manage_identities.run(
        [
            "--expect-database",
            "heroos",
            "--reference",
            "HER-230",
            "suspend-user",
            "--user",
            "00000000-0000-4000-8000-000000000001",
        ]
    )
    assert exit_code == manage_identities.EXIT_REFUSED


@pytest.mark.parametrize(
    "reference",
    ["", "her-230", "HER230", "fix things", "alice@example.com", "alembic:b8a11c15ed91"],
)
def test_change_reference_must_be_an_issue_key(reference: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(
            [
                "--expect-database",
                "heroos",
                "--reference",
                reference,
                "suspend-user",
                "--user",
                "00000000-0000-4000-8000-000000000001",
            ]
        )
    assert exc_info.value.code == 2


def test_subjects_are_not_accepted_as_arguments() -> None:
    # Pseudonymous personal data must not reach process lists or shell history.
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "--expect-database",
                "heroos",
                "--reference",
                "HER-230",
                "provision",
                "--company",
                "00000000-0000-4000-8000-000000000001",
                "--issuer",
                "urn:heroos:test",
                "--subject",
                "someone",
            ]
        )


def test_there_is_no_delete_command() -> None:
    commands = build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    assert not any("delete" in name for name in commands)


def test_cli_imports_without_api_settings_or_database_engine() -> None:
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("HEROOS_") and name not in ("DATABASE_URL", "MIGRATION_DATABASE_URL")
    }
    probe = (
        "import sys, scripts.manage_identities\n"
        "assert 'app.core.config' not in sys.modules, 'imported API settings'\n"
        "assert 'app.db.session' not in sys.modules, 'imported the API engine'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
