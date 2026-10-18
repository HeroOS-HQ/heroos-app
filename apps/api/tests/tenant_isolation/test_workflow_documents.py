"""M2-04C document previews on real PostgreSQL with RLS, as the API role.

Document routes store nothing, so there is no table to isolate. What this
proves, through the real application with the synthetic rules and templates:

- every document route runs in a transaction PostgreSQL itself keeps
  read-only (any INSERT, UPDATE or DELETE fails with SQLSTATE 25006), and
  the read-only guard holds for the ORM and for raw SQL;
- a preview leaves no trace: no row anywhere in the database contains a value
  that was previewed, no row count changes, and the Case's revision is unchanged;
- another Company's administrator can neither list, open nor preview a Case's
  templates (404, exactly like an unknown Case), and A's routes refuse B (403).
"""

import uuid
from collections.abc import Generator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import get_authentication_provider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.core.config import Settings
from app.db.models import Case
from app.db.session import get_db
from app.main import create_app
from app.tenancy.dependencies import ReadOnlyTransactionError, make_read_only
from tests.auth.conftest import TEST_APP_CLIENT_ID, TEST_COGNITO_ISSUER
from tests.fixtures import (
    SYNTHETIC_BUNDLE,
    SYNTHETIC_TEMPLATES,
    synthetic_bundle_pin,
    synthetic_templates_pin,
)
from tests.tenant_isolation.conftest import TenantDatabase, Tenants, scope_for
from tests.tenant_isolation.test_company_blueprint import answer, confirm
from tests.tenant_isolation.test_company_roles import set_role
from tests.tenant_isolation.test_workflow_cases import (  # noqa: F401  (pytest fixtures)
    ALICE,
    BOB,
    FORBIDDEN,
    NOT_FOUND,
    auth,
    provider,
    signing_key,
    sqlstate,
)
from tests.tenant_isolation.test_workflow_progression import choose, move, recorded_case

CHECK_IN = "synthetic.check_in_note"
# Unique per run: if it is anywhere in the database afterwards, a preview kept it.
MARKER = f"[SYNTHETIC] Preview marker {uuid.uuid4().hex}"
READ_ONLY_SQL_TRANSACTION = "25006"


@pytest.fixture
def documents_client(
    tenant_database: TenantDatabase,
    provider: CognitoAccessTokenProvider,  # noqa: F811
    tenants: Tenants,
    operator_engine: Engine,
) -> Iterator[tuple[TestClient, list[str]]]:
    """The production application with the synthetic rules and templates.

    Also yields, per request, whether its transaction was still read-only when
    the request finished (``SHOW transaction_read_only`` before the session closes).
    """
    set_role(operator_engine, tenants.a.company, tenants.a.membership, "company_admin")
    set_role(operator_engine, tenants.b.company, tenants.b.membership, "company_admin")
    engine = create_engine(tenant_database.runtime_url, pool_size=4, max_overflow=0)
    sessions = sessionmaker(bind=engine, autoflush=False)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        heroos_env="staging",
        database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
        heroos_auth_provider="cognito",
        heroos_cognito_issuer=TEST_COGNITO_ISSUER,
        heroos_cognito_app_client_id=TEST_APP_CLIENT_ID,
        heroos_sensitive_screening="synthetic_demo",
        heroos_rule_bundle_path=SYNTHETIC_BUNDLE,
        heroos_rule_bundle_sha256=synthetic_bundle_pin(),
        heroos_template_bundle_path=SYNTHETIC_TEMPLATES,
        heroos_template_bundle_sha256=synthetic_templates_pin(),
    )
    app = create_app(settings)
    read_only: list[str] = []

    def _db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db
            if db.in_transaction():
                read_only.append(str(db.scalar(text("SHOW transaction_read_only"))))

    app.dependency_overrides[get_authentication_provider] = lambda: provider
    app.dependency_overrides[get_db] = _db
    yield TestClient(app), read_only
    engine.dispose()


def at_check_in(
    client: TestClient,
    tenants: Tenants,
    tenant_key: str,
    headers: dict[str, str],
    runtime_engine: Engine,
    operator_engine: Engine,
) -> str:
    tenant = getattr(tenants, tenant_key)
    authority = "[SYNTHETIC] Licensing authority"
    answer(runtime_engine, tenant, "other", authority)
    confirm(operator_engine, tenant, "uae_federal", "other", authority)
    case_id, revision = recorded_case(client, tenant.company, headers)
    chosen = choose(client, tenant.company, case_id, headers, "less_serious", revision)
    started = move(
        client,
        tenant.company,
        case_id,
        headers,
        "start:test_check_in",
        chosen.json()["workflow"]["revision"],
    )
    assert started.status_code == 200, started.json()
    return case_id


def _paths(company: uuid.UUID, case_id: str) -> tuple[str, str, str]:
    base = f"/companies/{company}/cases/{case_id}/documents"
    return base, f"{base}/{CHECK_IN}", f"{base}/{CHECK_IN}/preview"


def _preview_body() -> dict[str, Any]:
    return {
        "template_version": 1,
        "values": {"recipient_name": MARKER, "summary": MARKER, "discussion_points": [MARKER]},
        "choices": {"meeting_format": ["online"]},
    }


def _everything(admin_engine: Engine) -> tuple[dict[str, int], int]:
    """Row counts of every table, and how many rows anywhere contain the marker."""
    with admin_engine.connect() as db:
        tables = list(
            db.scalars(
                text(
                    "SELECT quote_ident(tablename) FROM pg_tables WHERE schemaname = 'public' "
                    "ORDER BY tablename"
                )
            )
        )
        counts = {t: int(db.scalar(text(f"SELECT count(*) FROM {t}")) or 0) for t in tables}
        found = sum(
            int(
                db.scalar(
                    text(f"SELECT count(*) FROM {t} AS r WHERE strpos(r::text, :m) > 0"),
                    {"m": MARKER},
                )
                or 0
            )
            for t in tables
        )
    return counts, found


def test_the_read_only_guard_is_enforced_by_postgresql(
    runtime_engine: Engine, tenants: Tenants
) -> None:
    with Session(runtime_engine, autoflush=False) as db:
        scope_for(db, tenants.a)
        make_read_only(db)
        assert db.scalar(text("SHOW transaction_read_only")) == "on"
        with pytest.raises(DBAPIError) as refused:
            db.execute(
                text(
                    "INSERT INTO cases (id, company_id, case_type, title) "
                    "VALUES (gen_random_uuid(), :c, 'general', '[SYNTHETIC] Never')"
                ),
                {"c": tenants.a.company},
            )
        assert sqlstate(refused.value) == READ_ONLY_SQL_TRANSACTION
        db.rollback()
    with Session(runtime_engine, autoflush=False) as db:
        scope_for(db, tenants.a)
        make_read_only(db)
        db.add(Case(company_id=tenants.a.company, case_type="general", title="[SYNTHETIC] Never"))
        with pytest.raises(ReadOnlyTransactionError):
            db.flush()


def test_every_document_route_runs_read_only_and_keeps_nothing(
    documents_client: tuple[TestClient, list[str]],
    tenants: Tenants,
    auth: Any,  # noqa: F811
    runtime_engine: Engine,
    operator_engine: Engine,
    admin_engine: Engine,
) -> None:
    client, read_only = documents_client
    case_id = at_check_in(client, tenants, "a", auth(ALICE), runtime_engine, operator_engine)
    listing, opened, previewed = _paths(tenants.a.company, case_id)
    before, found_before = _everything(admin_engine)
    assert found_before == 0

    read_only.clear()
    responses = [
        client.get(listing, headers=auth(ALICE)),
        client.get(opened, headers=auth(ALICE)),
        client.post(previewed, headers=auth(ALICE), json=_preview_body()),
        # Refused input is never kept either.
        client.post(
            previewed,
            headers=auth(ALICE),
            json={"template_version": 1, "values": {"recipient_name": MARKER + "\n"}},
        ),
    ]
    assert [r.status_code for r in responses] == [200, 200, 200, 422]
    assert MARKER in str(responses[2].json()["blocks"])
    assert MARKER not in responses[3].text
    # Each of those requests ended in a transaction PostgreSQL kept read-only.
    assert read_only == ["on"] * 4

    after, found_after = _everything(admin_engine)
    assert after == before
    assert found_after == 0


def test_another_companys_administrator_cannot_reach_the_templates(
    documents_client: tuple[TestClient, list[str]],
    tenants: Tenants,
    auth: Any,  # noqa: F811
    runtime_engine: Engine,
    operator_engine: Engine,
) -> None:
    client, _ = documents_client
    case_id = at_check_in(client, tenants, "a", auth(ALICE), runtime_engine, operator_engine)
    # A's Case through B's routes, and an unknown Case: identical 404s.
    for target in (case_id, str(uuid.uuid4())):
        listing, opened, previewed = _paths(tenants.b.company, target)
        for response in (
            client.get(listing, headers=auth(BOB)),
            client.get(opened, headers=auth(BOB)),
            client.post(previewed, headers=auth(BOB), json=_preview_body()),
        ):
            assert (response.status_code, response.json()) == NOT_FOUND
    # A's routes with B's token: 403, like a Company that doesn't exist.
    listing, _, previewed = _paths(tenants.a.company, case_id)
    for response in (
        client.get(listing, headers=auth(BOB)),
        client.post(previewed, headers=auth(BOB), json=_preview_body()),
    ):
        assert (response.status_code, response.json()) == FORBIDDEN
    # A still sees its own template.
    assert client.get(listing, headers=auth(ALICE)).json()["templates"][0]["available"] is True
