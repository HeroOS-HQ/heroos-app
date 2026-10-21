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


def test_cli_refuses_the_b1b_schema(tenant_database: TenantDatabase) -> None:
    # The CLI needs C1's grants and exactly the current contract (8 since D5).
    with disposable_database(tenant_database, "clib1b") as admin_url:
        assert run_alembic(admin_url, "upgrade", "09cb5ec569b9").returncode == 0
        database = make_url(admin_url).database or ""
        operator_url = (
            make_url(tenant_database.operator_url)
            .set(database=database)
            .render_as_string(hide_password=False)
        )
        result = cli(operator_url, "jurisdiction-status", "--company", str(uuid.uuid4()))
    assert result.returncode == 3
    assert "schema contract is 2" in result.stderr


@pytest.mark.parametrize(
    ("revision", "contract"),
    [("3f6c2a9d81b4", 3), ("75ec6db8b6c1", 4), ("8d217d768395", 6), ("c4a7e2d9b310", 7)],
    ids=["c1", "d1", "d3", "d4"],
)
def test_cli_refuses_an_earlier_schema(
    tenant_database: TenantDatabase, revision: str, contract: int
) -> None:
    # Exact contract: the CLI refuses any schema it was not written against,
    # including the previous ones (C1, contract 3; D1, contract 4; D3, contract
    # 6; D4, contract 7), even though D1 to D5 add nothing for the operator.
    with disposable_database(tenant_database, f"cli{contract}") as admin_url:
        assert run_alembic(admin_url, "upgrade", revision).returncode == 0
        database = make_url(admin_url).database or ""
        operator_url = (
            make_url(tenant_database.operator_url)
            .set(database=database)
            .render_as_string(hide_password=False)
        )
        result = cli(operator_url, "jurisdiction-status", "--company", str(uuid.uuid4()))
    assert result.returncode == 3
    assert f"schema contract is {contract}" in result.stderr


# --- Company registration, roles and jurisdiction (M1-10C) ------------------------


def test_cli_registers_a_company_idempotently_without_printing_the_subject(
    tenant_database: TenantDatabase, tenants: Tenants
) -> None:
    company = str(uuid.uuid4())
    args = (
        "register-company",
        "--company",
        company,
        "--name",
        "Delta Logistics FZCO",
        "--issuer",
        SERVICE_TEST_ISSUER,
    )
    first = cli(tenant_database.operator_url, *args, subject="cli-founder-subject")
    assert first.returncode == 0, first.stderr
    created = json.loads(first.stdout)
    assert created["outcome"] == "created"
    assert created["company_id"] == company
    assert set(created) == {
        "command",
        "outcome",
        "company_id",
        "blueprint_id",
        "user_id",
        "identity_id",
        "membership_id",
    }

    again = cli(tenant_database.operator_url, *args, subject="cli-founder-subject")
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)["outcome"] == "unchanged"

    other = cli(tenant_database.operator_url, *args, subject="cli-intruder-subject")
    assert other.returncode == 4
    assert json.loads(other.stdout) == {
        "command": "register-company",
        "outcome": "refused",
        "code": "company_exists",
    }
    for output in (first.stdout, first.stderr, again.stdout, again.stderr):
        assert "cli-founder-subject" not in output


def test_cli_appoints_an_administrator_and_confirms_a_jurisdiction(
    tenant_database: TenantDatabase, tenants: Tenants
) -> None:
    url = tenant_database.operator_url
    company = str(tenants.a.company)

    promoted = cli(
        url,
        "set-role",
        "--company",
        company,
        "--membership",
        str(tenants.a.membership),
        "--role",
        "company_admin",
    )
    assert promoted.returncode == 0, promoted.stderr
    assert json.loads(promoted.stdout)["role"] == "company_admin"

    status = cli(url, "jurisdiction-status", "--company", company)
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout) == {
        "command": "jurisdiction-status",
        "outcome": "unchanged",
        "company_id": company,
        "licensing_location": None,
        "licensing_authority": None,
        "readiness": "unconfirmed",
        "reason": "licensing_not_provided",
        "employment_jurisdiction": None,
    }
    # Nothing to confirm against yet: the customer has not answered.
    unanswered = cli(
        url,
        "confirm-jurisdiction",
        "--company",
        company,
        "--jurisdiction",
        "difc",
        "--licensing-location",
        "difc",
    )
    assert unanswered.returncode == 4
    assert json.loads(unanswered.stdout)["code"] == "licensing_answer_mismatch"
    # "not sure" can never be confirmed against.
    unsure = cli(
        url,
        "confirm-jurisdiction",
        "--company",
        company,
        "--jurisdiction",
        "difc",
        "--licensing-location",
        "not_sure",
    )
    assert unsure.returncode == 2

    cleared = cli(url, "clear-jurisdiction", "--company", company)
    assert cleared.returncode == 0, cleared.stderr
    assert json.loads(cleared.stdout)["outcome"] == "unchanged"


def test_cli_rejects_unknown_roles_and_jurisdictions_at_parse_time(
    tenant_database: TenantDatabase, tenants: Tenants
) -> None:
    for args in (
        (
            "set-role",
            "--company",
            str(tenants.a.company),
            "--membership",
            str(tenants.a.membership),
            "--role",
            "owner",
        ),
        (
            "confirm-jurisdiction",
            "--company",
            str(tenants.a.company),
            "--jurisdiction",
            "mohre",
            "--licensing-location",
            "difc",
        ),
    ):
        result = cli(tenant_database.operator_url, *args)
        assert result.returncode == 2, args
