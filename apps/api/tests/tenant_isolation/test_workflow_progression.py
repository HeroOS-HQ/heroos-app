"""M2-03 workflow progress events on real PostgreSQL with RLS, as the API role.

The tenant-isolation contract (tenant-isolation.md §9) for
``workflow_progress_events``, and the progression routes through the real
application with the synthetic rule bundle installed:

- isolation three ways (repositories with RLS, RLS alone, the repository filter
  alone), WITH CHECK, and Company-qualified foreign keys to the instance and
  the submission;
- append-only for the runtime role, nothing for the operator, and the
  database itself refusing malformed events (shape, vocabulary, one position
  change per revision, one row per request);
- real concurrency: different transitions racing for one revision apply
  exactly one; the same request sent at once is applied once and every
  response shows the committed outcome;
- a stored event holds codes only (no answer, no free text);
- another Company's administrator can neither read nor move the Case.
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
from app.db.session import get_db
from app.main import create_app
from app.repositories import workflows
from app.tenancy.scope import CompanyScope
from app.workflows.definition import SAFETY_SCREENING
from tests.auth.conftest import TEST_APP_CLIENT_ID, TEST_COGNITO_ISSUER
from tests.fixtures import SYNTHETIC_BUNDLE, synthetic_bundle_pin
from tests.tenant_isolation.conftest import (
    TenantDatabase,
    Tenants,
    count_rows,
    owners,
    scope_for,
)
from tests.tenant_isolation.test_company_blueprint import answer, confirm
from tests.tenant_isolation.test_company_roles import set_role
from tests.tenant_isolation.test_workflow_cases import (  # noqa: F401  (pytest fixtures)
    ALICE,
    BOB,
    CONFLICT,
    NOT_FOUND,
    _parallel,
    auth,
    provider,
    signing_key,
    sqlstate,
)

TABLE = "workflow_progress_events"
NARRATIVE = "[SYNTHETIC] A team member missed two shift handovers in a row."
COLUMNS = (
    "id, company_id, instance_id, kind, transition, pathway, previous_pathway, stage, "
    "decision, reasons, acknowledged, revision, request_key, submission_id, actor_user_id, "
    "bundle_id, bundle_version, bundle_digest, definition_version, intake_status"
)


def _event_sql(**overrides: str) -> str:
    """An INSERT of one refused transition; ``overrides`` replace column expressions."""
    values = {
        "id": "gen_random_uuid()",
        "company_id": ":company",
        "instance_id": ":instance",
        "kind": "'transition_rejected'",
        "transition": "'start:test_check_in'",
        "pathway": "'less_serious'",
        "previous_pathway": "NULL",
        "stage": "'test_check_in'",
        "decision": "'block'",
        "reasons": "'[]'",
        "acknowledged": "'[]'",
        "revision": "1",
        "request_key": "gen_random_uuid()",
        "submission_id": "NULL",
        "actor_user_id": ":user",
        "bundle_id": "'synthetic-progression'",
        "bundle_version": "'synthetic.1'",
        "bundle_digest": "repeat('0', 64)",
        "definition_version": "2",
        "intake_status": "'intake_recorded'",
        **overrides,
    }
    return f"INSERT INTO {TABLE} ({COLUMNS}) VALUES ({', '.join(values.values())})"


@pytest.fixture
def rules_client(
    tenant_database: TenantDatabase,
    provider: CognitoAccessTokenProvider,  # noqa: F811
    tenants: Tenants,
    operator_engine: Engine,
) -> Iterator[TestClient]:
    """The production application with the synthetic rules, on a pooled runtime engine."""
    set_role(operator_engine, tenants.a.company, tenants.a.membership, "company_admin")
    engine = create_engine(tenant_database.runtime_url, pool_size=4, max_overflow=0)
    sessions = sessionmaker(bind=engine, autoflush=False)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        heroos_env="staging",
        database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
        heroos_auth_provider="cognito",
        heroos_cognito_issuer=TEST_COGNITO_ISSUER,
        heroos_cognito_app_client_id=TEST_APP_CLIENT_ID,
        # A synthetic test database: screening and synthetic rules only.
        heroos_sensitive_screening="synthetic_demo",
        heroos_rule_bundle_path=SYNTHETIC_BUNDLE,
        heroos_rule_bundle_sha256=synthetic_bundle_pin(),
    )
    app = create_app(settings)

    def _db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_authentication_provider] = lambda: provider
    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    engine.dispose()


def recorded_case(
    client: TestClient,
    company: uuid.UUID,
    headers: dict[str, str],
) -> tuple[str, int]:
    """A UAE Federal Case through the whole intake (the Company is confirmed)."""
    created = client.post(
        f"/companies/{company}/workflows/disciplinary/cases",
        headers=headers,
        json={"title": "[SYNTHETIC] Progression", "request_key": str(uuid.uuid4())},
    )
    assert created.status_code == 201, created.json()
    case_id: str = created.json()["id"]
    steps = [
        (
            "initial_facts",
            {
                "incident.narrative": NARRATIVE,
                "incident.date": "2026-10-10",
                "incident.history": "new",
                "incident.discussed_with_employee": "yes",
                "incident.evidence_available": "yes",
            },
        ),
        ("jurisdiction", {"jurisdiction.case_confirmation": "uae_federal"}),
        (
            "incident_context",
            {
                "context.location": "at_work",
                "history.same_incident_sanction": "no",
                "context.policy_awareness": "yes",
                "evidence.witnesses": "yes",
            },
        ),
        ("safety_screening", {q.key: "no" for q in SAFETY_SCREENING.questions}),
    ]
    revision = 0
    for step, answers in steps:
        response = client.put(
            f"/companies/{company}/cases/{case_id}/workflow/steps/{step}/answers",
            headers=headers,
            json={
                "expected_revision": revision,
                "submission_key": str(uuid.uuid4()),
                "answers": answers,
            },
        )
        assert response.status_code == 200, response.json()
        revision = response.json()["workflow"]["revision"]
    assert response.json()["status"]["code"] == "intake_recorded"
    return case_id, revision


def choose(
    client: TestClient,
    company: uuid.UUID,
    case_id: str,
    headers: dict[str, str],
    pathway: str,
    revision: int,
    key: str | None = None,
) -> Any:
    return client.post(
        f"/companies/{company}/cases/{case_id}/workflow/progression/pathway",
        headers=headers,
        json={
            "expected_revision": revision,
            "request_key": key or str(uuid.uuid4()),
            "pathway": pathway,
        },
    )


def move(
    client: TestClient,
    company: uuid.UUID,
    case_id: str,
    headers: dict[str, str],
    transition: str,
    revision: int,
    key: str | None = None,
) -> Any:
    return client.post(
        f"/companies/{company}/cases/{case_id}/workflow/progression/transitions",
        headers=headers,
        json={
            "expected_revision": revision,
            "request_key": key or str(uuid.uuid4()),
            "transition": transition,
        },
    )


@pytest.fixture
def progressed(
    rules_client: TestClient,
    tenants: Tenants,
    auth: Any,  # noqa: F811
    runtime_engine: Engine,
    operator_engine: Engine,
) -> dict[str, Any]:
    """Per Company: a recorded Case with a pathway chosen and a refused skip."""
    authority = "[SYNTHETIC] Licensing authority"
    created: dict[str, Any] = {}
    set_role(operator_engine, tenants.b.company, tenants.b.membership, "company_admin")
    for label, tenant, subject in (("a", tenants.a, ALICE), ("b", tenants.b, BOB)):
        answer(runtime_engine, tenant, "other", authority)
        confirm(operator_engine, tenant, "uae_federal", "other", authority)
        case_id, revision = recorded_case(rules_client, tenant.company, auth(subject))
        chosen = choose(
            rules_client, tenant.company, case_id, auth(subject), "less_serious", revision
        )
        assert chosen.status_code == 200, chosen.json()
        revision = chosen.json()["workflow"]["revision"]
        skipped = move(
            rules_client,
            tenant.company,
            case_id,
            auth(subject),
            "start:test_final_review",
            revision,
        )
        assert skipped.json()["progression"]["attempt"]["outcome"] == "rejected"
        with Session(runtime_engine, autoflush=False) as db:
            scope_for(db, tenant)
            instance = db.scalar(
                text("SELECT id FROM workflow_instances WHERE case_id = :c"), {"c": case_id}
            )
            submission = db.scalar(
                text("SELECT id FROM workflow_submissions WHERE instance_id = :i LIMIT 1"),
                {"i": instance},
            )
        created[label] = {
            "case": case_id,
            "instance": instance,
            "submission": submission,
            "revision": revision,
        }
    return created


# --- isolation, three ways ---------------------------------------------------------------


def test_repositories_see_only_their_own_progress_events(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, progressed: dict[str, Any]
) -> None:
    for own, other, tenant in (("a", "b", tenants.a), ("b", "a", tenants.b)):
        with runtime_sessions() as db:
            scope = scope_for(db, tenant)
            assert [
                e.kind for e in workflows.progress_events(scope, progressed[own]["instance"])
            ] == [
                "pathway_selected",
                "transition_rejected",
            ]
            assert workflows.progress_events(scope, progressed[other]["instance"]) == []
            assert workflows.progress_events_by_instance(
                scope, [progressed[other]["instance"]]
            ) == {progressed[other]["instance"]: []}


def test_rls_alone_hides_other_companies_progress_events(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, progressed: dict[str, Any]
) -> None:
    with runtime_sessions() as db:
        assert count_rows(db, TABLE) == 0  # no tenant context: nothing
        scope_for(db, tenants.a)
        assert owners(db, TABLE) == {tenants.a.company}
        assert count_rows(db, TABLE) == 2


def test_the_repository_filter_alone_hides_other_companies_progress_events(
    admin_sessions: sessionmaker[Session], tenants: Tenants, progressed: dict[str, Any]
) -> None:
    # The admin role bypasses RLS: only the repository filter protects here.
    with admin_sessions() as db:
        scope = CompanyScope(session=db, company_id=tenants.a.company)
        assert workflows.progress_events(scope, progressed["b"]["instance"]) == []
        assert len(workflows.progress_events(scope, progressed["a"]["instance"])) == 2


def test_rls_with_check_refuses_progress_events_for_another_company(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, progressed: dict[str, Any]
) -> None:
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        with pytest.raises(DBAPIError) as caught:
            db.execute(
                text(_event_sql()),
                {
                    "company": tenants.b.company,
                    "instance": progressed["b"]["instance"],
                    "user": tenants.a.user,
                },
            )
        assert sqlstate(caught.value) == "42501"


@pytest.mark.parametrize(
    ("overrides", "target"),
    [
        # Own Company id, another Company's instance.
        ({}, "other_instance"),
        # Own instance, another Company's submission.
        (
            {
                "submission_id": ":other_submission",
                "kind": "'escalation_recorded'",
                "decision": "'escalate'",
                "request_key": "NULL",
            },
            "own_instance",
        ),
    ],  # fmt: skip
)
def test_company_qualified_foreign_keys_refuse_cross_company_progress_links(
    runtime_sessions: sessionmaker[Session],
    tenants: Tenants,
    progressed: dict[str, Any],
    overrides: dict[str, str],
    target: str,
) -> None:
    instance = progressed["b" if target == "other_instance" else "a"]["instance"]
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        with pytest.raises(DBAPIError) as caught:
            db.execute(
                text(_event_sql(**overrides)),
                {
                    "company": tenants.a.company,
                    "instance": instance,
                    "other_submission": progressed["b"]["submission"],
                    "user": tenants.a.user,
                },
            )
        assert sqlstate(caught.value) == "23503"


@pytest.mark.parametrize(
    "statement",
    [
        f"UPDATE {TABLE} SET decision = 'allow'",
        f"UPDATE {TABLE} SET kind = 'stage_completed'",
        f"UPDATE {TABLE} SET reasons = '[]'",
        f"DELETE FROM {TABLE}",
        f"TRUNCATE {TABLE}",
    ],
)
def test_runtime_role_can_only_append_progress_events(
    runtime_sessions: sessionmaker[Session],
    tenants: Tenants,
    progressed: dict[str, Any],
    statement: str,
) -> None:
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        with pytest.raises(DBAPIError) as caught:
            db.execute(text(statement))
        assert sqlstate(caught.value) == "42501"


def test_the_operator_cannot_read_progress_events(
    operator_engine: Engine, progressed: dict[str, Any]
) -> None:
    with operator_engine.connect() as conn, pytest.raises(DBAPIError) as caught:
        conn.execute(text(f"SELECT count(*) FROM {TABLE}"))
    assert sqlstate(caught.value) == "42501"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"kind": "'stage_skipped'"}, "23514"),
        ({"decision": "'approve'"}, "23514"),
        # A refusal is blocked or escalated, never allowed.
        ({"decision": "'allow'"}, "23514"),
        # A position change is allowed (or warned) and always an employer request.
        ({"kind": "'stage_started'", "decision": "'block'"}, "23514"),
        ({"kind": "'stage_started'", "request_key": "NULL"}, "23514"),
        (
            {
                "kind": "'pathway_selected'",
                "decision": "'allow'",
                "stage": "NULL",
                "pathway": "NULL",
            },
            "23514",
        ),
        # An escalation found by a save carries no request.
        ({"kind": "'escalation_recorded'", "decision": "'escalate'"}, "23514"),
        ({"previous_pathway": "'serious'"}, "23514"),
        ({"pathway": "'dismissal'"}, "23514"),
        ({"transition": "'skip:test_check_in'"}, "23514"),
        ({"transition": "'start:Test Stage'"}, "23514"),
        ({"bundle_digest": "'not-a-digest'"}, "23514"),
        ({"bundle_version": "'Synthetic 1'"}, "23514"),
        ({"intake_status": "'cleared'"}, "23514"),
        ({"reasons": "'{}'"}, "23514"),
        ({"reasons": "to_jsonb(repeat('x', 20000))::jsonb || '[]'::jsonb"}, "23514"),
        ({"revision": "-1"}, "23514"),
    ],  # fmt: skip
)
def test_the_database_refuses_malformed_progress_events(
    runtime_sessions: sessionmaker[Session],
    tenants: Tenants,
    progressed: dict[str, Any],
    overrides: dict[str, str],
    code: str,
) -> None:
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        with pytest.raises(DBAPIError) as caught:
            db.execute(
                text(_event_sql(**overrides)),
                {
                    "company": tenants.a.company,
                    "instance": progressed["a"]["instance"],
                    "user": tenants.a.user,
                },
            )
        assert sqlstate(caught.value) == code


def test_one_position_change_per_revision_and_one_row_per_request(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, progressed: dict[str, Any]
) -> None:
    params = {
        "company": tenants.a.company,
        "instance": progressed["a"]["instance"],
        "user": tenants.a.user,
    }
    applied = {
        "kind": "'stage_started'",
        "decision": "'allow'",
        "revision": str(progressed["a"]["revision"]),
    }
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        # The pathway choice already produced this revision.
        with pytest.raises(DBAPIError) as caught:
            db.execute(text(_event_sql(**applied)), params)
        assert sqlstate(caught.value) == "23505"
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        key = db.scalar(text(f"SELECT request_key FROM {TABLE} WHERE kind = 'transition_rejected'"))
        with pytest.raises(DBAPIError) as caught:
            db.execute(text(_event_sql(request_key=f"'{key}'::uuid")), params)
        assert sqlstate(caught.value) == "23505"


def test_a_stored_event_holds_codes_only(admin_engine: Engine, progressed: dict[str, Any]) -> None:
    with admin_engine.connect() as conn:
        rows = conn.execute(
            text(f"SELECT reasons::text, acknowledged::text FROM {TABLE} WHERE instance_id = :i"),
            {"i": progressed["a"]["instance"]},
        ).all()
    assert rows
    for reasons, acknowledged in rows:
        stored = reasons + acknowledged
        assert NARRATIVE not in stored
        assert "Test stage" not in stored  # no bundle wording
        assert '"yes"' not in stored and '"no"' not in stored  # no answers


# --- concurrency (real PostgreSQL row locks) ----------------------------------------------


def test_concurrent_transitions_are_serialized(
    rules_client: TestClient,
    tenants: Tenants,
    auth: Any,  # noqa: F811
    runtime_engine: Engine,
    operator_engine: Engine,
    admin_sessions: sessionmaker[Session],
) -> None:
    a = tenants.a
    authority = "[SYNTHETIC] Licensing authority"
    answer(runtime_engine, a, "other", authority)
    confirm(operator_engine, a, "uae_federal", "other", authority)
    case_id, revision = recorded_case(rules_client, a.company, auth(ALICE))

    # Different choices racing for one revision: exactly one is recorded.
    raced = _parallel(
        [
            lambda p=p: choose(rules_client, a.company, case_id, auth(ALICE), p, revision)
            for p in ("less_serious", "serious", "undetermined")
        ]
    )
    assert sorted(r.status_code for r in raced) == [200, 409, 409]
    winner = next(r for r in raced if r.status_code == 200).json()
    revision = winner["workflow"]["revision"]
    expected = ["pathway_selected"]
    if winner["progression"]["pathway"]["key"] == "undetermined":
        # Opens no stage: choose one that does, to race a stage transition next.
        chosen = choose(rules_client, a.company, case_id, auth(ALICE), "serious", revision)
        winner, revision = chosen.json(), chosen.json()["workflow"]["revision"]
        expected.append("pathway_selected")
    start = {"less_serious": "start:test_check_in", "serious": "start:test_notice"}[
        winner["progression"]["pathway"]["key"]
    ]

    # The same request sent three times at once: applied once, every answer the same.
    for round_ in range(3):
        key = str(uuid.uuid4())
        transition = start if round_ == 0 else start.replace("start:", "complete:")
        same = _parallel(
            [
                lambda key=key, transition=transition, revision=revision: move(
                    rules_client, a.company, case_id, auth(ALICE), transition, revision, key
                )
            ]
            * 3
        )
        assert [r.status_code for r in same] == [200, 200, 200]
        outcomes = {r.json()["progression"]["attempt"]["outcome"] for r in same}
        if round_ == 0:
            assert outcomes == {"applied"}
            assert {r.json()["workflow"]["revision"] for r in same} == {revision + 1}
            revision += 1
            expected.append("stage_started")
        else:
            # Refused (checklist not answered): recorded once, nothing moves.
            assert outcomes == {"rejected"}
            assert {r.json()["workflow"]["revision"] for r in same} == {revision}
            expected.append("transition_rejected")
    with admin_sessions() as db:
        kinds = db.scalars(
            text(
                f"SELECT e.kind FROM {TABLE} e JOIN workflow_instances i ON i.id = e.instance_id "
                "WHERE i.case_id = :c ORDER BY e.revision, e.occurred_at"
            ),
            {"c": case_id},
        ).all()
    assert kinds == expected


def test_another_companys_administrator_cannot_read_or_move_the_case(
    rules_client: TestClient,
    tenants: Tenants,
    auth: Any,  # noqa: F811
    progressed: dict[str, Any],
    admin_sessions: sessionmaker[Session],
) -> None:
    case_id = progressed["a"]["case"]
    revision = progressed["a"]["revision"]
    b = tenants.b.company
    for response in (
        rules_client.get(f"/companies/{b}/cases/{case_id}/workflow", headers=auth(BOB)),
        choose(rules_client, b, case_id, auth(BOB), "serious", revision),
        move(rules_client, b, case_id, auth(BOB), "start:test_check_in", revision),
    ):
        assert (response.status_code, response.json()) == NOT_FOUND
    with admin_sessions() as db:
        count = db.scalar(
            text(f"SELECT count(*) FROM {TABLE} WHERE instance_id = :i"),
            {"i": progressed["a"]["instance"]},
        )
    assert count == 2
    # And a stale request from A's own administrator is refused.
    stale = move(
        rules_client, tenants.a.company, case_id, auth(ALICE), "start:test_check_in", revision - 1
    )
    assert (stale.status_code, stale.json()) == CONFLICT
