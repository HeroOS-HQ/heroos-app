"""M2-01 workflow Cases and M2-02 intake evaluations on real PostgreSQL with RLS.

The tenant-isolation contract for new private entities (tenant-isolation.md §9)
applied to ``workflow_instances``, ``workflow_submissions``, ``case_facts`` and
``workflow_evaluations``, as the API runtime role:

- isolation proven three ways: repositories with RLS, RLS alone (unfiltered
  SQL) and the repository filter alone (an admin session that bypasses RLS);
- Company-qualified foreign keys refuse cross-Company and cross-instance links;
- the runtime role can only append (no fact or submission UPDATE/DELETE, no
  instance DELETE, only the revision is updatable) and cannot delete a Case
  that has a workflow (PRIV-020);
- real concurrency: compare-and-set revisions, concurrent saves (one
  evaluation per saved submission) and concurrent idempotent creations through
  the production application;
- the intake end to end on PostgreSQL: a high-risk answer holds the Case and
  writes nothing but the submission, its facts and its evaluation.
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
from app.companies.jurisdiction import (
    JurisdictionAssessment,
    JurisdictionReadiness,
    ReadinessReason,
)
from app.core.config import Settings
from app.db.session import get_db
from app.main import create_app
from app.repositories import workflows
from app.tenancy.scope import CompanyScope
from app.workflows.conditions import DISCIPLINARY_INTAKE
from app.workflows.definition import DISCIPLINARY_V1, DISCIPLINARY_V2, SAFETY_SCREENING
from app.workflows.history import evaluation_results
from app.workflows.intake import evaluate_intake
from tests.auth.conftest import TEST_APP_CLIENT_ID, TEST_COGNITO_ISSUER, LocalJWKClient
from tests.tenant_isolation.conftest import (
    TenantDatabase,
    Tenants,
    count_rows,
    owners,
    scope_for,
)
from tests.tenant_isolation.test_company_blueprint import answer, confirm
from tests.tenant_isolation.test_company_roles import set_role

ALICE = "alice-subject"
BOB = "bob-subject"
TABLES = ("workflow_instances", "workflow_submissions", "case_facts", "workflow_evaluations")
UNCONFIRMED = JurisdictionAssessment(
    JurisdictionReadiness.UNCONFIRMED, ReadinessReason.LICENSING_NOT_PROVIDED
)
EVALUATION_COLUMNS = (
    "id, company_id, instance_id, submission_id, definition_version, ruleset_version, "
    "ruleset_digest, status, hold, hold_reason, screening, results"
)
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
    changes = {"incident.history": "new", "incident.narrative": "[SYNTHETIC] narrative"}
    submission = workflows.record_submission(
        scope,
        item.instance,
        step_key="initial_facts",
        revision=1,
        idempotency_key=uuid.uuid4(),
        user_id=user,
        changes=changes,
    )
    evaluation = evaluate_intake(DISCIPLINARY_V2, changes, UNCONFIRMED)
    workflows.record_evaluation(
        scope, submission, evaluation, evaluation_results(evaluation, DISCIPLINARY_INTAKE)
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
            created[label]["evaluation"] = db.scalar(
                text("SELECT id FROM workflow_evaluations WHERE instance_id = :i"),
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
            assert workflows.evaluations(scope, seeded[other]["instance"]) == {}
            own_evaluations = workflows.evaluations(scope, seeded[own]["instance"])
            assert list(own_evaluations) == [seeded[own]["submission"]]
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
        assert workflows.evaluations(scope, seeded["b"]["instance"]) == {}


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
        pytest.param(
            f"INSERT INTO workflow_evaluations ({EVALUATION_COLUMNS}) VALUES (gen_random_uuid(), "
            ":other_company, :other_instance, :other_submission, 2, 'disciplinary-intake.1', "
            "repeat('0', 64), 'intake_in_progress', NULL, NULL, 'not_applicable', '[]')",
            id="evaluation-in-other-company",
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


def _extra_submission(db: Session, company: uuid.UUID, instance: uuid.UUID, user: uuid.UUID) -> Any:
    """A submission without an evaluation (inserted as admin)."""
    return db.scalar(
        text(
            "INSERT INTO workflow_submissions (id, company_id, instance_id, step_key, revision, "
            "idempotency_key, submitted_by_user_id) VALUES (gen_random_uuid(), :company, "
            ":instance, 'initial_facts', 7, gen_random_uuid(), :user) RETURNING id"
        ),
        {"company": company, "instance": instance, "user": user},
    )


def test_an_evaluation_cannot_point_at_another_companys_submission(
    admin_sessions: sessionmaker[Session], tenants: Tenants, seeded: dict[str, Any]
) -> None:
    # As admin (no RLS): the Company-qualified foreign key alone refuses it.
    with admin_sessions() as db:
        other = _extra_submission(db, tenants.b.company, seeded["b"]["instance"], tenants.b.user)
        for instance in (seeded["b"]["instance"], seeded["a"]["instance"]):
            # The savepoint rolls back first, then the error reaches pytest.raises.
            with pytest.raises(DBAPIError) as caught, db.begin_nested():
                db.execute(
                    text(
                        f"INSERT INTO workflow_evaluations ({EVALUATION_COLUMNS}) VALUES "
                        "(gen_random_uuid(), :company, :instance, :submission, 2, "
                        "'disciplinary-intake.1', repeat('0', 64), 'intake_in_progress', NULL, "
                        "NULL, 'not_applicable', '[]')"
                    ),
                    {"company": tenants.a.company, "instance": instance, "submission": other},
                )
            assert sqlstate(caught.value) == "23503"
        db.rollback()


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ("2, 'disciplinary-intake.1', repeat('0', 64), 'approved', NULL, NULL, 'cleared', '[]'",
         "ck_workflow_evaluations_status"),
        ("2, 'disciplinary-intake.1', repeat('0', 64), 'held_for_specialist_review', "
         "'specialist_review', NULL, 'positive', '[]'", "ck_workflow_evaluations_hold"),
        ("2, 'disciplinary-intake.1', repeat('0', 64), 'intake_recorded', NULL, "
         "'high_risk_factors', 'cleared', '[]'", "ck_workflow_evaluations_hold"),
        ("2, 'disciplinary-intake.1', repeat('0', 64), 'intake_recorded', NULL, NULL, "
         "'waived', '[]'", "ck_workflow_evaluations_screening"),
        ("2, 'disciplinary-intake.1', 'not-a-digest', 'intake_recorded', NULL, NULL, "
         "'cleared', '[]'", "ck_workflow_evaluations_ruleset_digest"),
        ("2, 'disciplinary-intake.1', repeat('0', 64), 'intake_recorded', NULL, NULL, "
         "'cleared', '{}'", "ck_workflow_evaluations_results"),
        ("0, 'disciplinary-intake.1', repeat('0', 64), 'intake_recorded', NULL, NULL, "
         "'cleared', '[]'", "ck_workflow_evaluations_definition_version"),
    ],
)  # fmt: skip
def test_the_database_refuses_an_evaluation_outside_the_vocabulary(
    runtime_sessions: sessionmaker[Session],
    admin_sessions: sessionmaker[Session],
    tenants: Tenants,
    seeded: dict[str, Any],
    values: str,
    constraint: str,
) -> None:
    with admin_sessions() as db:
        submission = _extra_submission(
            db, tenants.a.company, seeded["a"]["instance"], tenants.a.user
        )
        db.commit()
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        with pytest.raises(DBAPIError) as caught:
            db.execute(
                text(
                    f"INSERT INTO workflow_evaluations ({EVALUATION_COLUMNS}) VALUES "
                    f"(gen_random_uuid(), :company, :instance, :submission, {values})"
                ),
                {
                    "company": tenants.a.company,
                    "instance": seeded["a"]["instance"],
                    "submission": submission,
                },
            )
        assert sqlstate(caught.value) == "23514"
        assert constraint in str(caught.value)


def test_one_evaluation_per_submission(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, seeded: dict[str, Any]
) -> None:
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        with pytest.raises(DBAPIError) as caught:
            db.execute(
                text(
                    f"INSERT INTO workflow_evaluations ({EVALUATION_COLUMNS}) VALUES "
                    "(gen_random_uuid(), :company, :instance, :submission, 2, "
                    "'disciplinary-intake.1', repeat('0', 64), 'intake_in_progress', NULL, NULL, "
                    "'not_applicable', '[]')"
                ),
                {
                    "company": tenants.a.company,
                    "instance": seeded["a"]["instance"],
                    "submission": seeded["a"]["submission"],
                },
            )
        assert sqlstate(caught.value) == "23505"


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
        # The evaluation trace: never rewritten, never removed.
        "UPDATE workflow_evaluations SET status = 'intake_recorded'",
        "UPDATE workflow_evaluations SET hold = NULL, hold_reason = NULL",
        "UPDATE workflow_evaluations SET results = '[]'",
        "DELETE FROM workflow_evaluations",
        "TRUNCATE workflow_evaluations",
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
    # applied once, and every response shows the committed result. Repeated,
    # because the race CI caught (run 38777691679) needs a narrow interleaving.
    for round_ in range(10):
        revision = 1 + round_
        key = str(uuid.uuid4())
        answer = ("yes", "no")[round_ % 2]

        def same(key: str = key, revision: int = revision, answer: str = answer) -> Any:
            return pooled_client.put(
                url,
                headers=auth(ALICE),
                json={
                    "expected_revision": revision,
                    "submission_key": key,
                    "answers": {"incident.discussed_with_employee": answer},
                },
            )

        repeated = _parallel([same, same, same])
        assert [r.status_code for r in repeated] == [200, 200, 200]
        assert {r.json()["workflow"]["revision"] for r in repeated} == {revision + 1}
        assert {r.json()["answers"]["incident.discussed_with_employee"] for r in repeated} == {
            answer
        }
    with admin_sessions() as db:
        assert (
            db.scalar(
                text(
                    "SELECT count(*) FROM workflow_submissions s JOIN workflow_instances i "
                    "ON i.id = s.instance_id WHERE i.case_id = :c"
                ),
                {"c": case_id},
            )
            == 11
        )
        # Every saved submission has exactly one evaluation (none for replays).
        assert db.execute(
            text(
                "SELECT count(*), count(DISTINCT e.submission_id) FROM workflow_evaluations e "
                "JOIN workflow_instances i ON i.id = e.instance_id WHERE i.case_id = :c"
            ),
            {"c": case_id},
        ).one() == (11, 11)


def test_a_save_racing_an_identical_committed_save_answers_with_the_committed_state(
    pooled_client: TestClient,
    tenants: Tenants,
    auth: Any,
    runtime_engine: Engine,
    admin_sessions: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for CI run 38777691679 (Tenant Isolation).

    The same save (same submission key) committed by another request right
    after this request's first read. Before the fix, this request read the
    instance (revision 1), then found the other request's submission and replayed
    with the stale revision: a 200 whose revision (1) was older than the answers
    it showed (revision 2), so the employer's next save would have been refused
    as stale. The route now locks the instance row first: the other request
    waits, and every response reflects one committed state.
    """
    a = tenants.a
    created = pooled_client.post(
        f"/companies/{a.company}/workflows/disciplinary/cases",
        headers=auth(ALICE),
        json={"title": "[SYNTHETIC] Race", "request_key": str(uuid.uuid4())},
    )
    case_id = uuid.UUID(created.json()["id"])
    url = f"/companies/{a.company}/cases/{case_id}/workflow/steps/initial_facts/answers"
    first = pooled_client.put(
        url,
        headers=auth(ALICE),
        json={
            "expected_revision": 0,
            "submission_key": str(uuid.uuid4()),
            "answers": {"incident.history": "new"},
        },
    )
    assert first.json()["workflow"]["revision"] == 1
    key = uuid.uuid4()
    original = workflows.get_workflow_case
    state: dict[str, Any] = {"errors": []}

    def concurrent_identical_save() -> None:
        try:
            with Session(runtime_engine, autoflush=False) as db:
                scope = scope_for(db, a)
                item = original(scope, case_id, for_update=True)
                assert item is not None
                if workflows.find_submission(scope, item.instance.id, key) is None:
                    revision = workflows.advance_revision(scope, item.instance.id, 1)
                    if revision is not None:
                        workflows.record_submission(
                            scope,
                            item.instance,
                            step_key="initial_facts",
                            revision=revision,
                            idempotency_key=key,
                            user_id=a.user,
                            changes={"incident.discussed_with_employee": "yes"},
                        )
                scope.commit()
        except Exception as error:  # surfaced by the assertion below
            state["errors"].append(error)

    def racing_lookup(scope: CompanyScope, lookup: uuid.UUID, **options: Any) -> Any:
        result = original(scope, lookup, **options)
        if "worker" not in state:
            # The other request runs right after this read; it can only commit
            # now if this request holds no lock on the instance.
            worker = threading.Thread(target=concurrent_identical_save)
            state["worker"] = worker
            worker.start()
            worker.join(timeout=1.5)
        return result

    monkeypatch.setattr(workflows, "get_workflow_case", racing_lookup)
    response = pooled_client.put(
        url,
        headers=auth(ALICE),
        json={
            "expected_revision": 1,
            "submission_key": str(key),
            "answers": {"incident.discussed_with_employee": "yes"},
        },
    )
    state["worker"].join(timeout=10)
    assert not state["worker"].is_alive()
    assert state["errors"] == []
    assert response.status_code == 200
    body = response.json()
    assert body["workflow"]["revision"] == 2
    assert body["answers"]["incident.discussed_with_employee"] == "yes"
    with admin_sessions() as db:
        assert (
            db.scalar(
                text(
                    "SELECT count(*) FROM workflow_submissions s JOIN workflow_instances i "
                    "ON i.id = s.instance_id WHERE i.case_id = :c AND s.idempotency_key = :k"
                ),
                {"c": case_id, "k": key},
            )
            == 1
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

    # Bob (administrator of B only): 403 on A, 404 for A's Case through B.
    set_role(operator_engine, b.company, b.membership, "company_admin")
    response = pooled_client.get(
        f"/companies/{a.company}/workflows/disciplinary/cases", headers=auth(BOB)
    )
    assert (response.status_code, response.json()) == FORBIDDEN
    response = pooled_client.get(
        f"/companies/{b.company}/cases/{case_id}/workflow", headers=auth(BOB)
    )
    assert (response.status_code, response.json()) == NOT_FOUND

    # Demoted between requests: refused inside the request's transaction, and a
    # member can neither write nor read (administrator-only, M2-01).
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
    for path in (
        f"/companies/{a.company}/cases/{case_id}/workflow",
        f"/companies/{a.company}/workflows/disciplinary/cases",
    ):
        response = pooled_client.get(path, headers=auth(ALICE))
        assert (response.status_code, response.json()) == FORBIDDEN
    # The generic Case records hide the Disciplinary Case from the member.
    records = pooled_client.get(f"/companies/{a.company}/cases", headers=auth(ALICE))
    assert [c["id"] for c in records.json()] == [str(a.case)]
    response = pooled_client.get(f"/companies/{a.company}/cases/{case_id}", headers=auth(ALICE))
    assert (response.status_code, response.json()) == NOT_FOUND


def test_a_high_risk_hold_on_postgresql_writes_only_its_own_trace(
    pooled_client: TestClient,
    tenants: Tenants,
    auth: Any,
    runtime_engine: Engine,
    operator_engine: Engine,
    admin_engine: Engine,
) -> None:
    a = tenants.a
    authority = "[SYNTHETIC] Licensing authority"
    answer(runtime_engine, a, "other", authority)
    confirm(operator_engine, a, "uae_federal", "other", authority)
    created = pooled_client.post(
        f"/companies/{a.company}/workflows/disciplinary/cases",
        headers=auth(ALICE),
        json={"title": "[SYNTHETIC] Intake", "request_key": str(uuid.uuid4())},
    )
    case_id = created.json()["id"]
    base = f"/companies/{a.company}/cases/{case_id}/workflow/steps"

    def put(step: str, answers: dict[str, str], revision: int) -> Any:
        return pooled_client.put(
            f"{base}/{step}/answers",
            headers=auth(ALICE),
            json={
                "expected_revision": revision,
                "submission_key": str(uuid.uuid4()),
                "answers": answers,
            },
        )

    confirmed = put("jurisdiction", {"jurisdiction.case_confirmation": "uae_federal"}, 0)
    assert confirmed.json()["intake"]["case_jurisdiction"]["status"] == "resolved"

    def table_counts() -> dict[str, int]:
        with admin_engine.connect() as conn:
            names = conn.scalars(
                text(
                    "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
                    "AND relkind IN ('r', 'p') ORDER BY relname"
                )
            ).all()
            return {n: conn.scalar(text(f"SELECT count(*) FROM {n}")) or 0 for n in names}

    before = table_counts()
    screening = {q.key: "no" for q in SAFETY_SCREENING.questions}
    held = put("safety_screening", {**screening, "screening.whistleblower": "yes"}, 1)

    assert held.status_code == 200
    body = held.json()
    assert body["status"]["code"] == "held_for_specialist_review"
    assert body["intake"]["hold"]["reason"] == "high_risk_factors"
    after = table_counts()
    changed = {t: after[t] - before[t] for t in after if after[t] != before[t]}
    # One submission, its nine facts and its evaluation; nothing else anywhere.
    assert changed == {"workflow_submissions": 1, "case_facts": 9, "workflow_evaluations": 1}
    with admin_engine.connect() as conn:
        stored = conn.execute(
            text(
                "SELECT e.hold, e.hold_reason, e.jurisdiction, e.screening FROM "
                "workflow_evaluations e JOIN workflow_instances i ON i.id = e.instance_id "
                "WHERE i.case_id = :c ORDER BY e.evaluated_at DESC LIMIT 1"
            ),
            {"c": case_id},
        ).one()
    assert tuple(stored) == ("specialist_review", "high_risk_factors", "uae_federal", "positive")
    # Another Company's administrator sees none of it.
    set_role(operator_engine, tenants.b.company, tenants.b.membership, "company_admin")
    response = pooled_client.get(
        f"/companies/{tenants.b.company}/cases/{case_id}/workflow", headers=auth(BOB)
    )
    assert (response.status_code, response.json()) == NOT_FOUND
