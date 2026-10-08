"""Real-PostgreSQL tenant isolation suite (``make tenant-isolation-check``).

RLS cannot be proven on SQLite. This suite:

1. creates a disposable ``*_tenant_isolation_test`` database (never ``heroos``),
2. applies every Alembic migration as the migration/admin role,
3. bootstraps the RLS-restricted runtime login role,
4. seeds two tenants as admin, and
5. exercises tenant-private data as the runtime role.

The database is dropped afterwards, also on failure.

Configured by environment variables (``scripts/verify-tenant-isolation.sh`` sets
them). Without them the suite is skipped, so ``make check`` needs no database;
with ``TENANT_TEST_REQUIRED=1`` missing configuration fails instead.
"""

import os
import re
import subprocess
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.auth.models import AuthenticatedCompanyContext
from app.db.models import Case, CaseSubject, Company, CompanyBlueprint, Membership, User
from app.tenancy.scope import CompanyScope, open_company_scope
from scripts.bootstrap_runtime_role import bootstrap_runtime_role

API_ROOT = Path(__file__).resolve().parents[2]

ADMIN_URL_ENV = "TENANT_TEST_ADMIN_URL"
DATABASE_ENV = "TENANT_TEST_DATABASE"
RUNTIME_ROLE_ENV = "TENANT_TEST_RUNTIME_ROLE"
RUNTIME_PASSWORD_ENV = "TENANT_TEST_RUNTIME_PASSWORD"
REQUIRED_ENV = "TENANT_TEST_REQUIRED"

SAFE_DATABASE_NAME = re.compile(r"[a-z0-9_]+_tenant_isolation_test")

# Tenant-owned tables and the column naming the owning Company.
TENANT_TABLES = {
    "companies": "id",
    "memberships": "company_id",
    "company_blueprints": "company_id",
    "case_subjects": "company_id",
    "cases": "company_id",
}


@dataclass(frozen=True)
class TenantDatabase:
    admin_url: str
    runtime_url: str
    runtime_role: str


@pytest.fixture(scope="session")
def tenant_database() -> Iterator[TenantDatabase]:
    admin_url = os.environ.get(ADMIN_URL_ENV)
    if not admin_url:
        message = f"{ADMIN_URL_ENV} not set; run `make tenant-isolation-check`"
        if os.environ.get(REQUIRED_ENV) == "1":
            pytest.fail(message)
        pytest.skip(message)

    name = os.environ.get(DATABASE_ENV, "heroos_tenant_isolation_test")
    if not SAFE_DATABASE_NAME.fullmatch(name):
        pytest.fail(f"refusing to use database {name!r}: must match *_tenant_isolation_test")

    runtime_role = os.environ.get(RUNTIME_ROLE_ENV, "heroos_app")
    runtime_password = os.environ.get(RUNTIME_PASSWORD_ENV, "heroos_app_local")

    admin = make_url(admin_url)
    test_admin_url = admin.set(database=name).render_as_string(hide_password=False)
    runtime_url = admin.set(
        database=name, username=runtime_role, password=runtime_password
    ).render_as_string(hide_password=False)

    maintenance = create_engine(admin.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with maintenance.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))

        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=API_ROOT,
            env={**os.environ, "MIGRATION_DATABASE_URL": test_admin_url},
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if migration.returncode != 0:
            pytest.fail(f"alembic upgrade head failed:\n{migration.stderr}")

        bootstrap_runtime_role(test_admin_url, runtime_url)

        yield TenantDatabase(
            admin_url=test_admin_url, runtime_url=runtime_url, runtime_role=runtime_role
        )
    finally:
        with maintenance.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        maintenance.dispose()


@pytest.fixture(scope="session")
def admin_engine(tenant_database: TenantDatabase) -> Iterator[Engine]:
    """Migration/admin role (local superuser). Bypasses RLS: setup and ground truth only."""
    engine = create_engine(tenant_database.admin_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def runtime_engine(tenant_database: TenantDatabase) -> Iterator[Engine]:
    """The API runtime role: subject to RLS. Every isolation assertion uses it."""
    engine = create_engine(tenant_database.runtime_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def runtime_sessions(runtime_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=runtime_engine, autoflush=False)


@pytest.fixture
def admin_sessions(admin_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=admin_engine, autoflush=False)


@dataclass(frozen=True)
class Tenant:
    company: uuid.UUID
    user: uuid.UUID
    identity_subject: str
    membership: uuid.UUID
    blueprint: uuid.UUID
    subject: uuid.UUID
    case: uuid.UUID

    @property
    def context(self) -> AuthenticatedCompanyContext:
        return AuthenticatedCompanyContext(
            user_id=self.user,
            company_id=self.company,
            membership_id=self.membership,
            identity_subject=self.identity_subject,
        )


@dataclass(frozen=True)
class Tenants:
    """Company A (alice) and Company B (bob); carol is a User with no Membership."""

    a: Tenant
    b: Tenant
    carol: uuid.UUID


def _create_tenant(db: Session, label: str, subject: str) -> Tenant:
    company = Company(name=f"Company {label}")
    user = User(identity_subject=subject)
    db.add_all([company, user])
    db.flush()
    membership = Membership(company_id=company.id, user_id=user.id)
    blueprint = CompanyBlueprint(
        company_id=company.id, legal_name=f"Company {label} LLC", primary_jurisdiction="DIFC"
    )
    case_subject = CaseSubject(
        company_id=company.id, subject_type="employee", display_name=f"Employee {label}"
    )
    db.add_all([membership, blueprint, case_subject])
    db.flush()
    case = Case(
        company_id=company.id,
        subject_id=case_subject.id,
        case_type="disciplinary",
        title=f"Case {label}",
    )
    db.add(case)
    db.flush()
    return Tenant(
        company=company.id,
        user=user.id,
        identity_subject=subject,
        membership=membership.id,
        blueprint=blueprint.id,
        subject=case_subject.id,
        case=case.id,
    )


@pytest.fixture
def tenants(admin_sessions: sessionmaker[Session]) -> Tenants:
    """Fresh two-tenant data for every test, written as admin (bypasses RLS)."""
    with admin_sessions() as db:
        db.execute(text("TRUNCATE companies, users CASCADE"))
        a = _create_tenant(db, "A", "alice-subject")
        b = _create_tenant(db, "B", "bob-subject")
        carol = User(identity_subject="carol-subject")
        db.add(carol)
        db.commit()
        return Tenants(a=a, b=b, carol=carol.id)


def scope_for(session: Session, tenant: Tenant) -> CompanyScope:
    """Production path: tenant context set from an AuthenticatedCompanyContext."""
    return open_company_scope(session, tenant.context)


def tenant_setting(session: Session) -> str | None:
    """The raw PostgreSQL value of heroos.company_id on this connection."""
    value: str | None = session.scalar(text("SELECT current_setting('heroos.company_id', true)"))
    return value


def backend_pid(session: Session) -> int:
    pid: int = session.scalar(text("SELECT pg_backend_pid()"))
    return pid


def count_rows(session: Session, table: str) -> int:
    """Unfiltered row count: anything returned is what RLS lets through."""
    assert table in TENANT_TABLES or table == "users"
    count: int = session.scalar(text(f"SELECT count(*) FROM {table}"))
    return count


def owners(session: Session, table: str) -> set[uuid.UUID]:
    """Owning Company of every row RLS lets through, from an unfiltered query."""
    column = TENANT_TABLES[table]
    return set(session.scalars(text(f"SELECT {column} FROM {table}")))
