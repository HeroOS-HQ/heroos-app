"""The identity operator CLI end to end on PostgreSQL (subprocess, real logins).

Runs ``python -m scripts.manage_identities`` exactly as an operator would, with
an environment that contains no API settings at all.
"""

import json
import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy.engine import make_url

from tests.tenant_isolation.conftest import (
    API_ROOT,
    SERVICE_TEST_ISSUER,
    TenantDatabase,
    Tenants,
    disposable_database,
    run_alembic,
)

SUBJECT = "cli-operator-subject"


def cli(
    url: str, *args: str, subject: str | None = None, database: str | None = None
) -> subprocess.CompletedProcess[str]:
    # No HEROOS_* or DATABASE_URL: the CLI must not need or read API settings.
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("HEROOS_", "TENANT_TEST_"))
        and name not in ("DATABASE_URL", "MIGRATION_DATABASE_URL")
    }
    env["HEROOS_OPERATOR_DATABASE_URL"] = url
    expect = database or make_url(url).database or ""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.manage_identities",
            "--expect-database",
            expect,
            "--reference",
            "HER-230",
            *args,
        ],
        cwd=API_ROOT,
        env=env,
        input=None if subject is None else subject + "\n",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_cli_provisions_idempotently_without_printing_secrets_or_subjects(
    tenant_database: TenantDatabase, tenants: Tenants
) -> None:
    args = ("provision", "--company", str(tenants.a.company), "--issuer", SERVICE_TEST_ISSUER)
    first = cli(tenant_database.operator_url, *args, subject=SUBJECT)
    assert first.returncode == 0, first.stderr
    created = json.loads(first.stdout)
    assert created["outcome"] == "created"
    assert set(created) == {"command", "outcome", "user_id", "identity_id", "membership_id"}

    again = cli(tenant_database.operator_url, *args, subject=SUBJECT)
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)["outcome"] == "unchanged"

    password = make_url(tenant_database.operator_url).password or ""
    for output in (first.stdout, first.stderr, again.stdout, again.stderr):
        assert SUBJECT not in output
        assert password not in output


def test_cli_lifecycle_commands(tenant_database: TenantDatabase, tenants: Tenants) -> None:
    url = tenant_database.operator_url
    company = str(tenants.a.company)
    membership = str(tenants.a.membership)
    user = str(tenants.a.user)
    for args in (
        ("revoke-membership", "--company", company, "--membership", membership),
        ("reactivate-membership", "--company", company, "--membership", membership),
        ("suspend-user", "--user", user),
        ("reactivate-user", "--user", user),
        ("revoke-identity", "--identity", str(tenants.a.identity)),
        ("reactivate-identity", "--identity", str(tenants.a.identity)),
    ):
        result = cli(url, *args)
        assert result.returncode == 0, (args, result.stderr)
        assert json.loads(result.stdout)["outcome"] == "updated", args


def test_cli_reports_refused_operations_with_fixed_codes(
    tenant_database: TenantDatabase, tenants: Tenants
) -> None:
    result = cli(
        tenant_database.operator_url,
        "grant",
        "--company",
        str(tenants.b.company),
        "--issuer",
        SERVICE_TEST_ISSUER,
        subject="nobody-subject",
    )
    assert result.returncode == 4
    assert json.loads(result.stdout) == {
        "command": "grant",
        "outcome": "refused",
        "code": "identity_not_found",
    }


@pytest.mark.parametrize("credential", ["runtime", "admin"])
def test_cli_refuses_api_and_owner_credentials(
    tenant_database: TenantDatabase, tenants: Tenants, credential: str
) -> None:
    url = tenant_database.runtime_url if credential == "runtime" else tenant_database.admin_url
    result = cli(url, "suspend-user", "--user", str(tenants.a.user))
    assert result.returncode == 3
    assert "refused" in result.stderr


def test_cli_refuses_an_unconfirmed_database(
    tenant_database: TenantDatabase, tenants: Tenants
) -> None:
    result = cli(
        tenant_database.operator_url,
        "suspend-user",
        "--user",
        str(tenants.a.user),
        database="heroos",
    )
    assert result.returncode == 3
    assert "--expect-database" in result.stderr


def test_cli_refuses_a_schema_before_b1b(tenant_database: TenantDatabase) -> None:
    with disposable_database(tenant_database, "clib1a") as admin_url:
        assert run_alembic(admin_url, "upgrade", "b8a11c15ed91").returncode == 0
        database = make_url(admin_url).database or ""
        operator_url = (
            make_url(tenant_database.operator_url)
            .set(database=database)
            .render_as_string(hide_password=False)
        )
        result = cli(operator_url, "suspend-user", "--user", str(uuid.uuid4()))
    assert result.returncode == 3
    assert "schema contract is 1" in result.stderr
