"""M2-01 workflow Cases on real PostgreSQL with RLS, as the API runtime role.

The tenant-isolation contract for new private entities (tenant-isolation.md §9)
applied to ``workflow_instances``, ``workflow_submissions`` and ``case_facts``:

- isolation proven three ways: repositories with RLS, RLS alone (unfiltered
  SQL) and the repository filter alone (an admin session that bypasses RLS);
- Company-qualified foreign keys refuse cross-Company and cross-instance links;
- the runtime role can only append (no fact or submission UPDATE/DELETE, no
  instance DELETE, only the revision is updatable) and cannot delete a Case
  that has a workflow (PRIV-020);
- real concurrency: compare-and-set revisions, concurrent saves and
  concurrent idempotent creations through the production application.
"""

import threading
import time
import uuid
from collections.abc import Generator, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import get_authentication_provider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.core.config import Settings
from app.db.session import get_db
from app.main import create_app
from app.repositories import workflows
from app.tenancy.scope import CompanyScope
from app.workflows.definition import DISCIPLINARY_V1
from tests.auth.conftest import TEST_APP_CLIENT_ID, TEST_COGNITO_ISSUER, LocalJWKClient
from tests.tenant_isolation.conftest import (
    TenantDatabase,
    Tenants,
    count_rows,
    owners,
    scope_for,
)
from tests.tenant_isolation.test_company_roles import set_role

ALICE = "alice-subject"
BOB = "bob-subject"
TABLES = ("workflow_instances", "workflow_submissions", "case_facts")
FORBIDDEN = (403, {"detail": "Forbidden"})
NOT_FOUND = (404, {"detail": "Not found"})
CONFLICT = (409, {"detail": "Conflict"})


KID = "workflow-cases-cognito-key"


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def provider(signing_key: rsa.RSAPrivateKey) -> CognitoAccessTokenProvider:
    jwk: dict[str, Any] = RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return CognitoAccessTokenProvider(
        issuer=TEST_COGNITO_ISSUER,
        app_client_id=TEST_APP_CLIENT_ID,
        jwks_client=LocalJWKClient({"keys": [jwk]}),
    )


@pytest.fixture
def auth(signing_key: rsa.RSAPrivateKey) -> Any:
    """Cognito-shaped access tokens, verified by the production provider."""

    def _auth(subject: str) -> dict[str, str]:
        now = int(time.time())
        claims = {
            "sub": subject,
            "iss": TEST_COGNITO_ISSUER,
            "client_id": TEST_APP_CLIENT_ID,
            "token_use": "access",
            "iat": now,
            "exp": now + 600,
        }
        token = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": KID})
        return {"Authorization": f"Bearer {token}"}

    return _auth


def sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None)


def new_case(scope: CompanyScope, user: uuid.UUID, title: str = "[SYNTHETIC] Case") -> Any:
    item = workflows.create_workflow_case(
        scope, DISCIPLINARY_V1, title=title, request_key=uuid.uuid4(), user_id=user
    )
    revision = workflows.advance_revision(scope, item.instance.id, 0)
    assert revision == 1
    workflows.record_submission(
        scope,
        item.instance,
        step_key="initial_facts",
        revision=1,
        idempotency_key=uuid.uuid4(),
        user_id=user,
        changes={"incident.history": "new", "incident.narrative": "[SYNTHETIC] narrative"},
    )
    return item


@pytest.fixture
def seeded(runtime_sessions: sessionmaker[Session], tenants: Tenants) -> dict[str, Any]:
    """One workflow Case with one answer group per Company, written as the runtime role."""
    created: dict[str, Any] = {}
    for label, tenant in (("a", tenants.a), ("b", tenants.b)):
        with runtime_sessions() as db:
            scope = scope_for(db, tenant)
            item = new_case(scope, tenant.user, f"[SYNTHETIC] Case {label.upper()}")
            created[label] = {
                "case": item.case.id,
                "instance": item.instance.id,
                "request_key": item.instance.request_key,
            }
            scope.commit()
            created[label]["submission"] = db.scalar(
                text("SELECT id FROM workflow_submissions WHERE instance_id = :i"),
                {"i": created[label]["instance"]},
            )
    return created


# --- isolation, three ways ---------------------------------------------------------------


def test_repositories_see_only_their_own_company(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, seeded: dict[str, Any]
) -> None:
    for own, other, tenant in (("a", "b", tenants.a), ("b", "a", tenants.b)):
        with runtime_sessions() as db:
            scope = scope_for(db, tenant)
            assert [i.case.id for i in workflows.list_workflow_cases(scope, "disciplinary")] == [
                seeded[own]["case"]
            ]
            assert workflows.get_workflow_case(scope, seeded[other]["case"]) is None
            assert workflows.find_by_request_key(scope, seeded[other]["request_key"]) is None
            facts = workflows.facts_by_instance(
                scope, [seeded[own]["instance"], seeded[other]["instance"]]
            )
            assert len(facts[seeded[own]["instance"]]) == 2
            assert facts[seeded[other]["instance"]] == []
            assert workflows.submissions(scope, seeded[other]["instance"]) == []
            # Another Company's revision cannot be advanced either.
            assert workflows.advance_revision(scope, seeded[other]["instance"], 1) is None


@pytest.mark.parametrize("table", TABLES)
def test_rls_alone_hides_other_companies_rows(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, seeded: dict[str, Any], table: str
) -> None:
    with runtime_sessions() as db:
        assert count_rows(db, table) == 0  # no tenant context: nothing
        scope_for(db, tenants.a)
        assert owners(db, table) == {tenants.a.company}


def test_repository_filter_alone_hides_other_companies_rows(
    admin_sessions: sessionmaker[Session], tenants: Tenants, seeded: dict[str, Any]
) -> None:
    # The admin role bypasses RLS: only the repository filter protects here.
    with admin_sessions() as db:
        scope = CompanyScope(session=db, company_id=tenants.a.company)
        assert [i.case.id for i in workflows.list_workflow_cases(scope, "disciplinary")] == [
            seeded["a"]["case"]
        ]
        assert workflows.get_workflow_case(scope, seeded["b"]["case"]) is None
        assert workflows.submissions(scope, seeded["b"]["instance"]) == []
        assert workflows.facts_by_instance(scope, [seeded["b"]["instance"]]) == {
            seeded["b"]["instance"]: []
        }


@pytest.mark.parametrize(
    "statement",
    [
        pytest.param(
            "INSERT INTO workflow_instances (id, company_id, case_id, workflow_key, "
            "definition_version, request_key, created_by_user_id) VALUES "
            "(gen_random_uuid(), :other_company, :other_case, 'disciplinary', 1, "
            "gen_random_uuid(), :user)",
            id="instance-in-other-company",
        ),
        pytest.param(
            "INSERT INTO workflow_submissions (id, company_id, instance_id, step_key, revision, "
            "idempotency_key, submitted_by_user_id) VALUES (gen_random_uuid(), :other_company, "
            ":other_instance, 'initial_facts', 9, gen_random_uuid(), :user)",
            id="submission-in-other-company",
        ),
        pytest.param(
            "INSERT INTO case_facts (id, company_id, instance_id, submission_id, fact_key, value) "
            "VALUES (gen_random_uuid(), :other_company, :other_instance, :other_submission, "
            "'incident.history', '\"new\"')",
            id="fact-in-other-company",
        ),
    ],
)
def test_rls_with_check_refuses_rows_for_another_company(
    runtime_sessions: sessionmaker[Session],
    tenants: Tenants,
    seeded: dict[str, Any],
    statement: str,
) -> None:
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        with pytest.raises(DBAPIError) as caught:
            db.execute(
                text(statement),
                {
                    "other_company": tenants.b.company,
                    "other_case": tenants.b.case,
                    "other_instance": seeded["b"]["instance"],
                    "other_submission": seeded["b"]["submission"],
                    "user": tenants.a.user,
                },
            )
        assert sqlstate(caught.value) == "42501"


@pytest.mark.parametrize(
    "statement",
    [
        # Own Company id, but another Company's Case / instance / submission.
        pytest.param(
            "INSERT INTO workflow_instances (id, company_id, case_id, workflow_key, "
            "definition_version, request_key, created_by_user_id) VALUES "
            "(gen_random_uuid(), :company, :other_case, 'disciplinary', 1, gen_random_uuid(), "
            ":user)",
            id="instance-for-other-company-case",
        ),
        pytest.param(
            "INSERT INTO workflow_submissions (id, company_id, instance_id, step_key, revision, "
            "idempotency_key, submitted_by_user_id) VALUES (gen_random_uuid(), :company, "
            ":other_instance, 'initial_facts', 9, gen_random_uuid(), :user)",
            id="submission-for-other-company-instance",
        ),
        pytest.param(
            "INSERT INTO case_facts (id, company_id, instance_id, submission_id, fact_key, value) "
            "VALUES (gen_random_uuid(), :company, :instance, :other_submission, "
            "'incident.date', '\"not_sure\"')",
            id="fact-for-other-company-submission",
        ),
    ],
)
def test_company_qualified_foreign_keys_refuse_cross_company_links(
    # The fact key is one the target submission doesn't hold, so only the
    # foreign key (not the per-submission unique key) can refuse the row.
    admin_sessions: sessionmaker[Session],
    tenants: Tenants,
    seeded: dict[str, Any],
    statement: str,
) -> None:
    # As admin (no RLS): the foreign keys alone refuse the link.
    with admin_sessions() as db, pytest.raises(DBAPIError) as caught:
        db.execute(
            text(statement),
            {
                "company": tenants.a.company,
                "instance": seeded["a"]["instance"],
                "other_case": tenants.b.case,
                "other_instance": seeded["b"]["instance"],
                "other_submission": seeded["b"]["submission"],
                "user": tenants.a.user,
            },
        )
    assert sqlstate(caught.value) == "23503"


def test_a_fact_cannot_point_at_a_submission_of_another_instance(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, seeded: dict[str, Any]
) -> None:
    with runtime_sessions() as db:
        scope = scope_for(db, tenants.a)
        second = new_case(scope, tenants.a.user, "[SYNTHETIC] Second")
        with pytest.raises(DBAPIError) as caught:
            db.execute(
                text(
                    "INSERT INTO case_facts (id, company_id, instance_id, submission_id, "
                    "fact_key, value) VALUES (gen_random_uuid(), :company, :instance, "
                    ":submission, 'incident.date', '\"not_sure\"')"
                ),
                {
                    "company": tenants.a.company,
                    "instance": second.instance.id,
                    "submission": seeded["a"]["submission"],
                },
            )
        assert sqlstate(caught.value) == "23503"


# --- append-only and no deletion ------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE case_facts SET value = '\"tampered\"'",
        "DELETE FROM case_facts",
        "UPDATE workflow_submissions SET revision = revision + 10",
        "DELETE FROM workflow_submissions",
        "DELETE FROM workflow_instances",
        "UPDATE workflow_instances SET case_id = gen_random_uuid()",
        "UPDATE workflow_instances SET created_by_user_id = gen_random_uuid()",
        "TRUNCATE case_facts",
    ],
)
def test_runtime_role_can_only_append(
    runtime_sessions: sessionmaker[Session],
    tenants: Tenants,
    seeded: dict[str, Any],
    statement: str,
) -> None:
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        with pytest.raises(DBAPIError) as caught:
            db.execute(text(statement))
        assert sqlstate(caught.value) == "42501"


def test_only_the_revision_of_an_instance_is_updatable(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, seeded: dict[str, Any]
) -> None:
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        updated = db.execute(
            text("UPDATE workflow_instances SET revision = revision + 1, updated_at = now()")
        )
        assert updated.rowcount == 1  # A's only instance; B's is invisible


def test_a_case_with_a_workflow_cannot_be_deleted(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, seeded: dict[str, Any]
) -> None:
    # The API role may delete Cases (M1-06 primitive, no route), but a workflow
    # Case is protected by the foreign key: no implicit deletion (PRIV-020).
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        with pytest.raises(DBAPIError) as caught:
            db.execute(text("DELETE FROM cases WHERE id = :c"), {"c": seeded["a"]["case"]})
        assert sqlstate(caught.value) == "23503"


def test_the_operator_role_cannot_read_workflow_data(
    operator_engine: Engine, seeded: dict[str, Any]
) -> None:
    for table in TABLES:
        with operator_engine.connect() as conn, pytest.raises(DBAPIError) as caught:
            conn.execute(text(f"SELECT count(*) FROM {table}"))
        assert sqlstate(caught.value) == "42501"


# --- concurrency (real PostgreSQL row locks) ----------------------------------------------


def test_compare_and_set_lets_exactly_one_writer_win(
    runtime_engine: Engine, tenants: Tenants, seeded: dict[str, Any]
) -> None:
    instance = seeded["a"]["instance"]
    first = Session(runtime_engine, autoflush=False)
    second = Session(runtime_engine, autoflush=False)
    results: dict[str, int | None] = {}
    try:
        first_scope = scope_for(first, tenants.a)
        second_scope = scope_for(second, tenants.a)
        assert workflows.advance_revision(first_scope, instance, 1) == 2  # holds the row lock

        def contender() -> None:
            results["second"] = workflows.advance_revision(second_scope, instance, 1)
            second.rollback()

        worker = threading.Thread(target=contender)
        worker.start()
        time.sleep(0.3)  # let the contender block on the row lock
        first.commit()
        worker.join(timeout=10)
        assert not worker.is_alive()
    finally:
        first.close()
        second.close()
    assert results == {"second": None}


@pytest.fixture
def pooled_client(
    tenant_database: TenantDatabase,
    provider: CognitoAccessTokenProvider,
    tenants: Tenants,
    operator_engine: Engine,
) -> Iterator[TestClient]:
    set_role(operator_engine, tenants.a.company, tenants.a.membership, "company_admin")
    # Several connections, so concurrent requests really run concurrently.
    engine = create_engine(tenant_database.runtime_url, pool_size=4, max_overflow=0)
    sessions = sessionmaker(bind=engine, autoflush=False)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        heroos_env="staging",
        database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
        heroos_auth_provider="cognito",
        heroos_cognito_issuer=TEST_COGNITO_ISSUER,
        heroos_cognito_app_client_id=TEST_APP_CLIENT_ID,
    )
    app = create_app(settings)

    def _db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_authentication_provider] = lambda: provider
    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    engine.dispose()


def _parallel(calls: list[Any]) -> list[Any]:
    barrier = threading.Barrier(len(calls))

    def run(call: Any) -> Any:
        barrier.wait()
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(run, calls))


def test_concurrent_creations_with_one_key_make_one_case(
    pooled_client: TestClient, tenants: Tenants, auth: Any, admin_sessions: sessionmaker[Session]
) -> None:
    url = f"/companies/{tenants.a.company}/workflows/disciplinary/cases"
    for attempt in range(5):
        key = str(uuid.uuid4())
        body = {"title": f"[SYNTHETIC] Concurrent {attempt}", "request_key": key}
        responses = _parallel(
            [
                lambda body=body: pooled_client.post(url, headers=auth(ALICE), json=body)
                for _ in range(3)
            ]
        )
        # Exactly one creation; every other request replays it.
        assert sorted(r.status_code for r in responses) == [200, 200, 201]
        assert len({r.json()["id"] for r in responses}) == 1
        with admin_sessions() as db:
            assert (
                db.scalar(
                    text("SELECT count(*) FROM workflow_instances WHERE request_key = :k"),
                    {"k": key},
                )
                == 1
            )


def test_concurrent_saves_against_one_revision_apply_once(
    pooled_client: TestClient, tenants: Tenants, auth: Any, admin_sessions: sessionmaker[Session]
) -> None:
    created = pooled_client.post(
        f"/companies/{tenants.a.company}/workflows/disciplinary/cases",
        headers=auth(ALICE),
        json={"title": "[SYNTHETIC] Saves", "request_key": str(uuid.uuid4())},
    )
    case_id = created.json()["id"]
    url = f"/companies/{tenants.a.company}/cases/{case_id}/workflow/steps/initial_facts/answers"

    def save(value: str, key: str) -> Any:
        return pooled_client.put(
            url,
            headers=auth(ALICE),
            json={
                "expected_revision": 0,
                "submission_key": key,
                "answers": {"incident.history": value},
            },
        )

    # Different saves racing for revision 0: exactly one wins, the others are stale.
    different = _parallel(
        [lambda v=v: save(v, str(uuid.uuid4())) for v in ("new", "not_sure", "raised_before")]
    )
    assert sorted(r.status_code for r in different) == [200, 409, 409]
    winner = next(r for r in different if r.status_code == 200).json()
    assert winner["workflow"]["revision"] == 1

    # The same save sent three times at once (a double click and a retry):
    # applied once, every response shows the result.
    view = pooled_client.get(
        f"/companies/{tenants.a.company}/cases/{case_id}/workflow", headers=auth(ALICE)
    )
    key = str(uuid.uuid4())

    def same() -> Any:
        return pooled_client.put(
            url,
            headers=auth(ALICE),
            json={
                "expected_revision": view.json()["workflow"]["revision"],
                "submission_key": key,
                "answers": {"incident.discussed_with_employee": "yes"},
            },
        )

    repeated = _parallel([same, same, same])
    assert [r.status_code for r in repeated] == [200, 200, 200]
    assert {r.json()["workflow"]["revision"] for r in repeated} == {2}
    with admin_sessions() as db:
        assert (
            db.scalar(
                text(
                    "SELECT count(*) FROM workflow_submissions s JOIN workflow_instances i "
                    "ON i.id = s.instance_id WHERE i.case_id = :c"
                ),
                {"c": case_id},
            )
            == 2
        )


# --- the production routes on PostgreSQL ----------------------------------------------------


def test_routes_isolate_and_authorize_on_postgresql(
    pooled_client: TestClient, tenants: Tenants, auth: Any, operator_engine: Engine
) -> None:
    a, b = tenants.a, tenants.b
    created = pooled_client.post(
        f"/companies/{a.company}/workflows/disciplinary/cases",
        headers=auth(ALICE),
        json={"title": "[SYNTHETIC] Route case", "request_key": str(uuid.uuid4())},
    )
    assert created.status_code == 201
    case_id = created.json()["id"]

    # The seeded M1 Case has no workflow: not a workflow Case (404), not listed.
    response = pooled_client.get(
        f"/companies/{a.company}/cases/{a.case}/workflow", headers=auth(ALICE)
    )
    assert (response.status_code, response.json()) == NOT_FOUND
    listed = pooled_client.get(
        f"/companies/{a.company}/workflows/disciplinary/cases", headers=auth(ALICE)
    )
    assert [c["id"] for c in listed.json()] == [case_id]

    # Bob (a member of B only): 403 on A, 404 for A's Case through B.
    response = pooled_client.get(
        f"/companies/{a.company}/workflows/disciplinary/cases", headers=auth(BOB)
    )
    assert (response.status_code, response.json()) == FORBIDDEN
    response = pooled_client.get(
        f"/companies/{b.company}/cases/{case_id}/workflow", headers=auth(BOB)
    )
    assert (response.status_code, response.json()) == NOT_FOUND

    # Demoted between requests: the write is refused in the write transaction.
    set_role(operator_engine, a.company, a.membership, "member")
    response = pooled_client.put(
        f"/companies/{a.company}/cases/{case_id}/workflow/steps/initial_facts/answers",
        headers=auth(ALICE),
        json={
            "expected_revision": 0,
            "submission_key": str(uuid.uuid4()),
            "answers": {"incident.history": "new"},
        },
    )
    assert (response.status_code, response.json()) == FORBIDDEN
    member_view = pooled_client.get(
        f"/companies/{a.company}/cases/{case_id}/workflow", headers=auth(ALICE)
    )
    assert (member_view.status_code, member_view.json()["can_edit"]) == (200, False)
