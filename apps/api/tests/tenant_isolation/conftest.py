"""Real-PostgreSQL tenant isolation suite (``make tenant-isolation-check``).

RLS cannot be proven on SQLite. This suite:

1. creates a disposable ``*_tenant_isolation_test`` database (never ``heroos``),
2. applies every Alembic migration as the migration/admin role,
3. bootstraps a disposable RLS-restricted runtime login role
   (``heroos_app_t_<hex>`` with a random password) and a disposable identity
   operator login (``heroos_op_t_<hex>``). Never the shared ``heroos_app``:
   roles are cluster-wide, so managing it here would change the live API
   credential,
4. seeds two tenants as admin, and
5. exercises tenant-private data as the runtime role, and identity
   provisioning as the operator role.

The database and the disposable roles are dropped afterwards, also on failure.

Configured by environment variables (``scripts/verify-tenant-isolation.sh`` sets
them). Without them the suite is skipped, so ``make check`` needs no database;
with ``TENANT_TEST_REQUIRED=1`` missing configuration fails instead.
"""

import os
import re
import secrets
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.auth.models import AuthenticatedCompanyContext
from app.auth.providers.development import DEVELOPMENT_ISSUER
from app.db.models import (
    Case,
    CaseSubject,
    Company,
    CompanyBlueprint,
    Membership,
    User,
    UserIdentity,
)
from app.tenancy.scope import CompanyScope, open_company_scope
from scripts.bootstrap_runtime_role import bootstrap_operator_role, bootstrap_runtime_role
from tests.auth.conftest import TEST_COGNITO_ISSUER

API_ROOT = Path(__file__).resolve().parents[2]

ADMIN_URL_ENV = "TENANT_TEST_ADMIN_URL"
DATABASE_ENV = "TENANT_TEST_DATABASE"
RUNTIME_ROLE_ENV = "TENANT_TEST_RUNTIME_ROLE"
RUNTIME_PASSWORD_ENV = "TENANT_TEST_RUNTIME_PASSWORD"
OPERATOR_ROLE_ENV = "TENANT_TEST_OPERATOR_ROLE"
OPERATOR_PASSWORD_ENV = "TENANT_TEST_OPERATOR_PASSWORD"
REQUIRED_ENV = "TENANT_TEST_REQUIRED"

SAFE_DATABASE_NAME = re.compile(r"[a-z0-9_]+_tenant_isolation_test")
DISPOSABLE_RUNTIME_ROLE = re.compile(r"heroos_app_t_[0-9a-f]{8}")
DISPOSABLE_OPERATOR_ROLE = re.compile(r"heroos_op_t_[0-9a-f]{8}")

# Tenant-owned tables the API role reads, and the column naming the owning
# Company.
TENANT_TABLES = {
    "companies": "id",
    "memberships": "company_id",
    "company_blueprints": "company_id",
    "case_subjects": "company_id",
    "cases": "company_id",
}
# Tenant tables the API role may also update. Memberships are written only by
# the identity operator (ADR-008), still under the same tenant_isolation policy.
RUNTIME_WRITABLE_TABLES = {
    table: column for table, column in TENANT_TABLES.items() if table != "memberships"
}
# Tenant tables the API role may insert into. Companies are created only by
# operator registration (M1-10C): the API role holds no INSERT or DELETE there.
RUNTIME_INSERTABLE_TABLES = {
    table: column for table, column in RUNTIME_WRITABLE_TABLES.items() if table != "companies"
}
# Tenant-owned audit tables: written only by owner-run triggers; no API grant.
TENANT_AUDIT_TABLES = {
    "membership_events": "company_id",
    "company_events": "company_id",
    "company_registrations": "company_id",
}

# Issuers every seeded identity is bound under: the Cognito, OIDC and
# development providers used by the HTTP tests, and the URN used by
# service-level tests.
OIDC_TEST_ISSUER = "https://heroos-demo.idp.test.invalid/"
SERVICE_TEST_ISSUER = "urn:heroos:test"
TEST_ISSUERS = (TEST_COGNITO_ISSUER, OIDC_TEST_ISSUER, DEVELOPMENT_ISSUER, SERVICE_TEST_ISSUER)
# Fixture writes as admin are attributed like any other change (audit triggers).
TEST_REFERENCE = "HER-230"


@dataclass(frozen=True)
class TenantDatabase:
    admin_url: str
    runtime_url: str
    runtime_role: str
    operator_url: str
    operator_role: str


def admin_url_for(tenant_database: TenantDatabase, database: str) -> str:
    return (
        make_url(tenant_database.admin_url)
        .set(database=database)
        .render_as_string(hide_password=False)
    )


def run_alembic(admin_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run Alembic as the migration/admin role against ``admin_url``."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env={**os.environ, "MIGRATION_DATABASE_URL": admin_url},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@contextmanager
def disposable_database(tenant_database: TenantDatabase, label: str) -> Iterator[str]:
    """A fresh empty ``*_tenant_isolation_test`` database; yields its admin URL."""
    name = f"heroos_{label}_{secrets.token_hex(4)}_tenant_isolation_test"
    assert SAFE_DATABASE_NAME.fullmatch(name)
    maintenance = create_engine(
        make_url(tenant_database.admin_url).set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        with maintenance.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        yield admin_url_for(tenant_database, name)
    finally:
        with maintenance.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        maintenance.dispose()


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

    # The script passes the identities it will also clean up; direct pytest runs
    # generate them. Either way they must be disposable roles.
    runtime_role = os.environ.get(RUNTIME_ROLE_ENV) or f"heroos_app_t_{secrets.token_hex(4)}"
    runtime_password = os.environ.get(RUNTIME_PASSWORD_ENV) or secrets.token_hex(32)
    if not DISPOSABLE_RUNTIME_ROLE.fullmatch(runtime_role):
        pytest.fail(
            f"refusing runtime role {runtime_role!r}: the suite only manages disposable "
            "heroos_app_t_<8 hex> roles, never the shared heroos_app"
        )
    operator_role = os.environ.get(OPERATOR_ROLE_ENV) or f"heroos_op_t_{secrets.token_hex(4)}"
    operator_password = os.environ.get(OPERATOR_PASSWORD_ENV) or secrets.token_hex(32)
    if not DISPOSABLE_OPERATOR_ROLE.fullmatch(operator_role):
        pytest.fail(
            f"refusing operator role {operator_role!r}: the suite only manages disposable "
            "heroos_op_t_<8 hex> roles"
        )

    admin = make_url(admin_url)
    test_admin_url = admin.set(database=name).render_as_string(hide_password=False)
    runtime_url = admin.set(
        database=name, username=runtime_role, password=runtime_password
    ).render_as_string(hide_password=False)
    operator_url = admin.set(
        database=name, username=operator_role, password=operator_password
    ).render_as_string(hide_password=False)

    maintenance = create_engine(admin.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with maintenance.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))

        migration = run_alembic(test_admin_url, "upgrade", "head")
        if migration.returncode != 0:
            pytest.fail(f"alembic upgrade head failed:\n{migration.stderr}")

        bootstrap_runtime_role(test_admin_url, runtime_url)
        bootstrap_operator_role(test_admin_url, operator_url)

        yield TenantDatabase(
            admin_url=test_admin_url,
            runtime_url=runtime_url,
            runtime_role=runtime_role,
            operator_url=operator_url,
            operator_role=operator_role,
        )
    finally:
        with maintenance.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'DROP ROLE IF EXISTS "{runtime_role}"'))
            conn.execute(text(f'DROP ROLE IF EXISTS "{operator_role}"'))
        maintenance.dispose()


@pytest.fixture(scope="session")
def admin_engine(tenant_database: TenantDatabase) -> Iterator[Engine]:
    """Migration/admin role (local superuser). Bypasses RLS: setup and ground truth only."""
    # A transaction leaked by a failing test must fail the next setup loudly
    # instead of blocking its TRUNCATE forever.
    engine = create_engine(
        tenant_database.admin_url, connect_args={"options": "-c lock_timeout=10s"}
    )
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def runtime_engine(tenant_database: TenantDatabase) -> Iterator[Engine]:
    """The API runtime role: subject to RLS. Every isolation assertion uses it."""
    engine = create_engine(tenant_database.runtime_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def operator_engine(tenant_database: TenantDatabase) -> Iterator[Engine]:
    """The identity-operator role: provisioning only, subject to RLS for Memberships."""
    engine = create_engine(tenant_database.operator_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def runtime_sessions(runtime_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=runtime_engine, autoflush=False)


@pytest.fixture
def admin_sessions(admin_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=admin_engine, autoflush=False)


@pytest.fixture
def operator_sessions(operator_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=operator_engine, autoflush=False)


@dataclass(frozen=True)
class Tenant:
    company: uuid.UUID
    user: uuid.UUID
    identity_subject: str
    # Binding under SERVICE_TEST_ISSUER (the one service-level tests resolve).
    identity: uuid.UUID
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
            identity_id=self.identity,
        )


@dataclass(frozen=True)
class Tenants:
    """Company A (alice) and Company B (bob); carol is a User with no Membership."""

    a: Tenant
    b: Tenant
    carol: uuid.UUID


GLOBAL_TABLES = ("users", "user_identities", "identity_events")


def attribute_changes(db: Session) -> None:
    """Set the change reference the audit triggers require for this transaction."""
    db.execute(
        text("SELECT set_config('heroos.actor_reference', :ref, true)"), {"ref": TEST_REFERENCE}
    )


def bind_identities(db: Session, user: User, subject: str) -> uuid.UUID:
    """Bind ``subject`` under every test issuer; return the service-issuer binding."""
    identities = {
        issuer: UserIdentity(user_id=user.id, issuer=issuer, subject=subject)
        for issuer in TEST_ISSUERS
    }
    db.add_all(identities.values())
    db.flush()
    return identities[SERVICE_TEST_ISSUER].id


def _create_tenant(db: Session, label: str, subject: str) -> Tenant:
    company = Company(name=f"Company {label}")
    user = User()
    db.add_all([company, user])
    db.flush()
    identity = bind_identities(db, user, subject)
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
        identity=identity,
        membership=membership.id,
        blueprint=blueprint.id,
        subject=case_subject.id,
        case=case.id,
    )


@pytest.fixture
def tenants(admin_sessions: sessionmaker[Session]) -> Tenants:
    """Fresh two-tenant data for every test, written as admin (bypasses RLS)."""
    with admin_sessions() as db:
        # Cascades to memberships, identities and the audit tables. The audit
        # tables refuse TRUNCATE (append-only trigger); this disposable test
        # database is reset by suspending trigger firing for this transaction,
        # which only a superuser (the local test admin) can do.
        db.execute(text("SET LOCAL session_replication_role = replica"))
        db.execute(text("TRUNCATE companies, users CASCADE"))
        db.execute(text("SET LOCAL session_replication_role = origin"))
        attribute_changes(db)
        a = _create_tenant(db, "A", "alice-subject")
        b = _create_tenant(db, "B", "bob-subject")
        carol = User()
        db.add(carol)
        db.flush()
        bind_identities(db, carol, "carol-subject")
        db.commit()
        return Tenants(a=a, b=b, carol=carol.id)


@dataclass(frozen=True)
class LegacyDatabase:
    """A disposable database at ``97d4200fe7a2`` with pre-M1-10B data."""

    admin_url: str
    runtime_url: str
    operator_url: str
    company_a: uuid.UUID
    company_b: uuid.UUID
    alice: uuid.UUID
    bob: uuid.UUID
    alice_membership: uuid.UUID
    bob_membership: uuid.UUID
    # Company A has a Blueprint with legacy values; Company B has none.
    blueprint_a: uuid.UUID


def _as(url: str, database: str) -> str:
    return make_url(url).set(database=database).render_as_string(hide_password=False)


@pytest.fixture
def legacy_db(tenant_database: TenantDatabase) -> Iterator[LegacyDatabase]:
    """Two Companies (alice in A, bob in B) as a pre-M1-10B deployment has them."""
    with disposable_database(tenant_database, "legacy") as admin_url:
        migrated = run_alembic(admin_url, "upgrade", "97d4200fe7a2")
        assert migrated.returncode == 0, migrated.stderr
        ids = {name: uuid.uuid4() for name in ("a", "b", "alice", "bob", "ma", "mb", "bpa")}
        engine = create_engine(admin_url)
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO companies (id, name) VALUES (:a, 'Legacy A'), (:b, 'Legacy B')"),
                ids,
            )
            conn.execute(
                text(
                    "INSERT INTO users (id, identity_subject) "
                    "VALUES (:alice, 'alice-subject'), (:bob, 'bob-subject')"
                ),
                ids,
            )
            conn.execute(
                text(
                    "INSERT INTO memberships (id, company_id, user_id) "
                    "VALUES (:ma, :a, :alice), (:mb, :b, :bob)"
                ),
                ids,
            )
            conn.execute(
                text(
                    "INSERT INTO company_blueprints "
                    "(id, company_id, legal_name, primary_jurisdiction, industry, employee_count) "
                    "VALUES (:bpa, :a, 'Legacy A LLC', 'DIFC', 'Retail', 12)"
                ),
                ids,
            )
            conn.execute(
                text(
                    "INSERT INTO cases (id, company_id, case_type, title) "
                    "VALUES (gen_random_uuid(), :a, 'probation', 'Case A'), "
                    "(gen_random_uuid(), :b, 'probation', 'Case B')"
                ),
                ids,
            )
        engine.dispose()
        database = make_url(admin_url).database or ""
        yield LegacyDatabase(
            admin_url=admin_url,
            runtime_url=_as(tenant_database.runtime_url, database),
            operator_url=_as(tenant_database.operator_url, database),
            company_a=ids["a"],
            company_b=ids["b"],
            alice=ids["alice"],
            bob=ids["bob"],
            alice_membership=ids["ma"],
            bob_membership=ids["mb"],
            blueprint_a=ids["bpa"],
        )


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
    assert table in TENANT_TABLES or table in TENANT_AUDIT_TABLES or table in GLOBAL_TABLES
    count: int = session.scalar(text(f"SELECT count(*) FROM {table}"))
    return count


def owners(session: Session, table: str) -> set[uuid.UUID]:
    """Owning Company of every row RLS lets through, from an unfiltered query."""
    column = {**TENANT_TABLES, **TENANT_AUDIT_TABLES}[table]
    return set(session.scalars(text(f"SELECT {column} FROM {table}")))
