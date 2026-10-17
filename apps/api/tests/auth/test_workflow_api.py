"""Workflow Cases through the real application (M2-01).

``create_app`` with staging settings, Cognito access tokens verified by the
production provider, and in-memory SQLite built from the real models (no RLS;
the database layer, grants and concurrency are proven on PostgreSQL in
tests/tenant_isolation/test_workflow_cases.py).

Covers the access policy (administrators only, reads included; Disciplinary
records hidden from members in the generic Case routes), idempotent creation,
versioned answers with stale-write protection and replay, validation without
echoing values, and the "not implemented yet" boundaries of the slice.
"""

import logging
import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import get_authentication_provider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.db.base import Base
from app.db.models import (
    Case,
    CaseFact,
    CompanyBlueprint,
    Membership,
    WorkflowEvaluation,
    WorkflowInstance,
    WorkflowProgressEvent,
    WorkflowSubmission,
)
from app.db.session import get_db
from app.main import create_app
from tests.auth.conftest import CognitoTokenFactory, SeedData, bearer
from tests.auth.test_company_admin_api import make_admin
from tests.auth.test_company_api import staging_settings

FORBIDDEN = (403, {"detail": "Forbidden"})
NOT_FOUND = (404, {"detail": "Not found"})
CONFLICT = (409, {"detail": "Conflict"})
NARRATIVE = "[SYNTHETIC] A team member left the site early on two shifts.\nNo one was told."
STEP_ANSWERS = "/workflow/steps/initial_facts/answers"


@pytest.fixture
def sessions(session_factory: sessionmaker[Session], seed: SeedData) -> sessionmaker[Session]:
    engine = session_factory.kw["bind"]
    with session_factory() as db:
        # SQLite cannot compile the cases FK's column-scoped ON DELETE SET NULL
        # (see test_company_api.py); the ORM model is unchanged.
        db.execute(
            text(
                "CREATE TABLE cases (id CHAR(32) PRIMARY KEY, company_id CHAR(32) NOT NULL, "
                "subject_id CHAR(32), case_type VARCHAR(50) NOT NULL, title VARCHAR(200) NOT NULL, "
                "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
                "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"
            )
        )
        db.commit()
    Base.metadata.create_all(
        engine,
        tables=[
            CompanyBlueprint.__table__,
            WorkflowInstance.__table__,
            WorkflowSubmission.__table__,
            CaseFact.__table__,
            WorkflowEvaluation.__table__,
            WorkflowProgressEvent.__table__,
        ],
    )
    return session_factory


@pytest.fixture
def client(
    sessions: sessionmaker[Session], cognito_provider: CognitoAccessTokenProvider
) -> TestClient:
    app = create_app(staging_settings())

    def _db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_authentication_provider] = lambda: cognito_provider
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


@pytest.fixture
def alice(make_cognito_token: CognitoTokenFactory) -> dict[str, str]:
    return bearer(make_cognito_token("alice-subject"))


@pytest.fixture
def bob(make_cognito_token: CognitoTokenFactory) -> dict[str, str]:
    return bearer(make_cognito_token("bob-subject"))


@pytest.fixture
def admin_alice(
    sessions: sessionmaker[Session], seed: SeedData, alice: dict[str, str]
) -> dict[str, str]:
    make_admin(sessions, seed.company_a, seed.alice)
    return alice


def cases_url(company: uuid.UUID | str, workflow: str = "disciplinary") -> str:
    return f"/companies/{company}/workflows/{workflow}/cases"


def create(
    client: TestClient,
    headers: dict[str, str],
    company: uuid.UUID,
    title: str = "[SYNTHETIC] Attendance concern",
    key: str | None = None,
) -> Any:
    return client.post(
        cases_url(company),
        headers=headers,
        json={"title": title, "request_key": key or str(uuid.uuid4())},
    )


def save(
    client: TestClient,
    headers: dict[str, str],
    company: uuid.UUID,
    case_id: str,
    answers: dict[str, object],
    *,
    revision: int,
    key: str | None = None,
) -> Any:
    return client.put(
        f"/companies/{company}/cases/{case_id}{STEP_ANSWERS}",
        headers=headers,
        json={
            "expected_revision": revision,
            "submission_key": key or str(uuid.uuid4()),
            "answers": answers,
        },
    )


def count(sessions: sessionmaker[Session], model: type[Base]) -> int:
    with sessions() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


# --- creation and reading ------------------------------------------------------------


def test_administrator_creates_a_disciplinary_case(
    client: TestClient, sessions: sessionmaker[Session], seed: SeedData, admin_alice: dict[str, str]
) -> None:
    response = create(client, admin_alice, seed.company_a)

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "[SYNTHETIC] Attendance concern"
    # Set by the server from the workflow, never by the client.
    assert body["case_type"] == "disciplinary"
    assert body["workflow_key"] == "disciplinary"
    # Company A's jurisdiction isn't confirmed: the intake is paused from the start.
    assert body["status"] == {
        "code": "awaiting_jurisdiction",
        "label": "Awaiting jurisdiction confirmation",
    }
    # Initial facts (5) and incident context (4); no jurisdiction or screening yet.
    assert (body["answered"], body["total"]) == (0, 9)
    with sessions() as db:
        instance = db.scalar(select(WorkflowInstance))
        assert instance is not None
        assert (instance.company_id, instance.created_by_user_id) == (seed.company_a, seed.alice)
        assert (instance.revision, instance.definition_version) == (0, 2)

    listed = client.get(cases_url(seed.company_a), headers=admin_alice)
    assert listed.status_code == 200
    assert [case["id"] for case in listed.json()] == [body["id"]]


def test_the_case_opens_with_the_guided_conversation(
    client: TestClient, seed: SeedData, admin_alice: dict[str, str]
) -> None:
    case_id = create(client, admin_alice, seed.company_a).json()["id"]

    view = client.get(f"/companies/{seed.company_a}/cases/{case_id}/workflow", headers=admin_alice)

    assert view.status_code == 200
    body = view.json()
    assert body["can_edit"] is True
    assert body["workflow"] == {
        "key": "disciplinary",
        "title": "Disciplinary",
        "definition_version": 2,
        "revision": 0,
    }
    assert body["answers"] == {}
    assert len(body["missing"]) == 9
    assert body["asked"] == body["missing"]
    assert [q["key"] for q in body["steps"][0]["questions"]] == [
        "incident.narrative",
        "incident.date",
        "incident.history",
        "incident.discussed_with_employee",
        "incident.evidence_available",
    ]
    assert [m["kind"] for m in body["conversation"]] == [
        "information",
        "question_group",
        "hold",
        "missing_information",
        "question_group",
        "status_notice",
    ]
    # Jurisdiction readiness comes from the Blueprint (none here): not confirmed.
    assert body["jurisdiction"]["readiness"] == "unconfirmed"
    assert body["jurisdiction"]["guidance_allowed"] is False
    assert body["intake"]["case_jurisdiction"]["status"] == "company_unconfirmed"
    assert body["intake"]["hold"]["reason"] == "company_jurisdiction_unconfirmed"
    assert body["intake"]["hold"]["action"] == "block"
    assert body["intake"]["next_stage_open"] is False
    steps = {step["key"]: step for step in body["steps"]}
    assert [k for k, step in steps.items() if not step["available"]] == [
        "jurisdiction",
        "safety_screening",
    ]
    assert steps["safety_screening"]["provisional"] is True
    assert [p["status"] for p in body["progress"]] == [
        "completed",
        "needs_information",
        "blocked",
        "needs_information",
        "blocked",
        "blocked",
    ]
    assert body["not_available"] == [
        "Classification of the incident",
        "Options and decisions",
        "Documents",
        "Expert review",
    ]
    assert [(h["kind"], h["by_viewer"]) for h in body["history"]] == [("case_created", True)]


def test_members_cannot_list_open_create_or_answer(
    client: TestClient,
    sessions: sessionmaker[Session],
    seed: SeedData,
    alice: dict[str, str],
) -> None:
    # Interim least-privilege policy (M2-01): Disciplinary Cases are for
    # Company administrators only, reads included.
    assert (create(client, alice, seed.company_a).status_code, count(sessions, Case)) == (403, 0)

    make_admin(sessions, seed.company_a, seed.alice)
    title = "[SYNTHETIC] Confidential title"
    case_id = create(client, alice, seed.company_a, title=title).json()["id"]
    save(client, alice, seed.company_a, case_id, {"incident.narrative": NARRATIVE}, revision=0)
    with sessions() as db:
        db.execute(update(Membership).values(role="member"))
        db.commit()

    # Demoted: every workflow route answers the same fixed 403, with no content.
    for response in (
        client.get(cases_url(seed.company_a), headers=alice),
        client.get(f"/companies/{seed.company_a}/cases/{case_id}/workflow", headers=alice),
        client.get(f"/companies/{seed.company_a}/cases/{uuid.uuid4()}/workflow", headers=alice),
        save(client, alice, seed.company_a, case_id, {"incident.history": "new"}, revision=1),
        create(client, alice, seed.company_a),
    ):
        assert (response.status_code, response.json()) == FORBIDDEN
    assert count(sessions, WorkflowSubmission) == 1
    assert count(sessions, Case) == 1


def test_generic_case_records_hide_disciplinary_cases_from_members(
    client: TestClient,
    sessions: sessionmaker[Session],
    seed: SeedData,
    alice: dict[str, str],
) -> None:
    make_admin(sessions, seed.company_a, seed.alice)
    title = "[SYNTHETIC] Confidential title"
    case_id = create(client, alice, seed.company_a, title=title).json()["id"]
    with sessions() as db:
        db.add(Case(company_id=seed.company_a, case_type="general", title="[SYNTHETIC] Other"))
        db.commit()

    admin_list = client.get(f"/companies/{seed.company_a}/cases", headers=alice).json()
    assert sorted(c["case_type"] for c in admin_list) == ["disciplinary", "general"]
    assert (
        client.get(f"/companies/{seed.company_a}/cases/{case_id}", headers=alice).status_code == 200
    )

    with sessions() as db:
        db.execute(update(Membership).values(role="member"))
        db.commit()
    member_list = client.get(f"/companies/{seed.company_a}/cases", headers=alice)
    assert [c["case_type"] for c in member_list.json()] == ["general"]
    assert title not in member_list.text
    member_get = client.get(f"/companies/{seed.company_a}/cases/{case_id}", headers=alice)
    assert (member_get.status_code, member_get.json()) == NOT_FOUND


def test_another_company_is_forbidden_and_its_cases_are_not_found(
    client: TestClient,
    sessions: sessionmaker[Session],
    seed: SeedData,
    admin_alice: dict[str, str],
    bob: dict[str, str],
) -> None:
    make_admin(sessions, seed.company_b, seed.bob)
    b_case = create(client, bob, seed.company_b).json()["id"]

    # Company B's routes: 403, exactly like a Company that does not exist.
    assert (client.get(cases_url(seed.company_b), headers=admin_alice).status_code) == 403
    assert create(client, admin_alice, seed.company_b).status_code == 403
    # B's Case through A's routes: 404, exactly like a random id.
    for case_id in (b_case, str(uuid.uuid4())):
        response = client.get(
            f"/companies/{seed.company_a}/cases/{case_id}/workflow", headers=admin_alice
        )
        assert (response.status_code, response.json()) == NOT_FOUND
        response = save(client, admin_alice, seed.company_a, case_id, {}, revision=0)
        assert (response.status_code, response.json()) == NOT_FOUND
    assert client.get(cases_url(seed.company_a), headers=admin_alice).json() == []
    assert count(sessions, WorkflowSubmission) == 0


def test_unknown_workflows_and_steps_are_not_found(
    client: TestClient, seed: SeedData, admin_alice: dict[str, str]
) -> None:
    assert client.get(cases_url(seed.company_a, "probation"), headers=admin_alice).json() == {
        "detail": "Not found"
    }
    response = client.post(
        cases_url(seed.company_a, "probation"),
        headers=admin_alice,
        json={"title": "x", "request_key": str(uuid.uuid4())},
    )
    assert (response.status_code, response.json()) == NOT_FOUND
    case_id = create(client, admin_alice, seed.company_a).json()["id"]
    response = client.put(
        f"/companies/{seed.company_a}/cases/{case_id}/workflow/steps/decision/answers",
        headers=admin_alice,
        json={"expected_revision": 0, "submission_key": str(uuid.uuid4()), "answers": {}},
    )
    assert (response.status_code, response.json()) == NOT_FOUND


def test_unauthenticated_requests_are_refused(client: TestClient, seed: SeedData) -> None:
    assert client.get(cases_url(seed.company_a)).status_code == 401
    assert client.post(cases_url(seed.company_a), json={}).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"title": "x"},
        {"title": "x", "request_key": "not-a-uuid"},
        {"title": "", "request_key": str(uuid.uuid4())},
        {"title": " padded", "request_key": str(uuid.uuid4())},
        {"title": "x" * 201, "request_key": str(uuid.uuid4())},
        {"title": 7, "request_key": str(uuid.uuid4())},
        # Never mass-assignable: the server sets the type and the Company.
        {"title": "x", "request_key": str(uuid.uuid4()), "case_type": "probation"},
        {"title": "x", "request_key": str(uuid.uuid4()), "company_id": str(uuid.uuid4())},
    ],
)
def test_invalid_case_requests_are_refused(
    client: TestClient,
    sessions: sessionmaker[Session],
    seed: SeedData,
    admin_alice: dict[str, str],
    body: dict[str, object],
) -> None:
    response = client.post(cases_url(seed.company_a), headers=admin_alice, json=body)
    assert response.status_code == 422
    # The submitted value is never echoed (no "input" field in the errors).
    assert '"input"' not in response.text
    assert count(sessions, Case) == 0


# --- idempotent creation ---------------------------------------------------------------


def test_a_retried_creation_returns_the_same_case(
    client: TestClient, sessions: sessionmaker[Session], seed: SeedData, admin_alice: dict[str, str]
) -> None:
    key = str(uuid.uuid4())
    first = create(client, admin_alice, seed.company_a, key=key)
    retry = create(client, admin_alice, seed.company_a, key=key)

    assert (first.status_code, retry.status_code) == (201, 200)
    assert retry.json()["id"] == first.json()["id"]
    assert (count(sessions, Case), count(sessions, WorkflowInstance)) == (1, 1)

    reused = create(client, admin_alice, seed.company_a, title="Another case", key=key)
    assert (reused.status_code, reused.json()) == CONFLICT
    assert count(sessions, Case) == 1


# --- answers ---------------------------------------------------------------------------


def test_answers_are_saved_versioned_and_survive_reopening(
    client: TestClient, sessions: sessionmaker[Session], seed: SeedData, admin_alice: dict[str, str]
) -> None:
    case_id = create(client, admin_alice, seed.company_a).json()["id"]

    first = save(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        {"incident.narrative": NARRATIVE, "incident.history": "new"},
        revision=0,
    )
    assert first.status_code == 200
    assert first.json()["workflow"]["revision"] == 1
    # The Company jurisdiction isn't confirmed: answers are saved, the intake paused.
    assert first.json()["status"]["code"] == "awaiting_jurisdiction"

    second = save(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        {
            "incident.date": "not_sure",
            "incident.history": "raised_before",
            "incident.discussed_with_employee": "no",
            "incident.evidence_available": "yes",
        },
        revision=1,
    )
    assert second.status_code == 200

    # Reopened: a fresh read returns the persisted state.
    reopened = client.get(
        f"/companies/{seed.company_a}/cases/{case_id}/workflow", headers=admin_alice
    ).json()
    assert reopened["workflow"]["revision"] == 2
    assert reopened["answers"] == {
        "incident.narrative": NARRATIVE,
        "incident.date": "not_sure",
        "incident.history": "raised_before",
        "incident.discussed_with_employee": "no",
        "incident.evidence_available": "yes",
    }
    # The initial facts are complete; the incident context is still to answer
    # (with the documented-action follow-up, since the issue was raised before).
    assert not any(key.startswith("incident.") for key in reopened["missing"])
    assert "history.documented_action" in reopened["missing"]
    assert reopened["uncertain"] == ["incident.date"]
    # The jurisdiction is not confirmed: nothing jurisdiction-specific proceeds.
    assert reopened["status"]["code"] == "awaiting_jurisdiction"
    turns = [m for m in reopened["conversation"] if m["kind"] == "answer_confirmation"]
    assert [len(t["items"]) for t in turns] == [2, 4]
    assert all(t["by_viewer"] for t in turns)

    # Versioned and append-only: the earlier value is still stored.
    with sessions() as db:
        history = db.scalars(
            select(CaseFact.value)
            .where(CaseFact.fact_key == "incident.history")
            .order_by(CaseFact.value)
        ).all()
    assert sorted(history) == ["new", "raised_before"]
    listed = client.get(cases_url(seed.company_a), headers=admin_alice).json()
    assert (listed[0]["answered"], listed[0]["status"]["code"]) == (5, "awaiting_jurisdiction")


def test_an_answer_can_be_cleared_later(
    client: TestClient, seed: SeedData, admin_alice: dict[str, str]
) -> None:
    case_id = create(client, admin_alice, seed.company_a).json()["id"]
    save(client, admin_alice, seed.company_a, case_id, {"incident.date": "2026-10-01"}, revision=0)

    cleared = save(
        client, admin_alice, seed.company_a, case_id, {"incident.date": None}, revision=1
    )

    assert cleared.status_code == 200
    assert cleared.json()["answers"] == {}
    assert "incident.date" in cleared.json()["missing"]


def test_a_stale_save_is_refused_and_writes_nothing(
    client: TestClient, sessions: sessionmaker[Session], seed: SeedData, admin_alice: dict[str, str]
) -> None:
    case_id = create(client, admin_alice, seed.company_a).json()["id"]
    save(client, admin_alice, seed.company_a, case_id, {"incident.history": "new"}, revision=0)

    # Written against revision 0, after another save made it 1.
    stale = save(
        client, admin_alice, seed.company_a, case_id, {"incident.history": "not_sure"}, revision=0
    )

    assert (stale.status_code, stale.json()) == CONFLICT
    assert count(sessions, WorkflowSubmission) == 1
    view = client.get(f"/companies/{seed.company_a}/cases/{case_id}/workflow", headers=admin_alice)
    assert view.json()["answers"] == {"incident.history": "new"}


def test_a_retried_save_is_applied_once(
    client: TestClient, sessions: sessionmaker[Session], seed: SeedData, admin_alice: dict[str, str]
) -> None:
    case_id = create(client, admin_alice, seed.company_a).json()["id"]
    key = str(uuid.uuid4())
    answers = {"incident.history": "new"}

    first = save(client, admin_alice, seed.company_a, case_id, answers, revision=0, key=key)
    # The response was lost; the client retries with the same key and revision.
    retry = save(client, admin_alice, seed.company_a, case_id, answers, revision=0, key=key)

    assert (first.status_code, retry.status_code) == (200, 200)
    assert retry.json()["workflow"]["revision"] == 1
    assert (count(sessions, WorkflowSubmission), count(sessions, CaseFact)) == (1, 1)


def test_saving_unchanged_answers_creates_no_revision(
    client: TestClient, sessions: sessionmaker[Session], seed: SeedData, admin_alice: dict[str, str]
) -> None:
    case_id = create(client, admin_alice, seed.company_a).json()["id"]
    save(client, admin_alice, seed.company_a, case_id, {"incident.history": "new"}, revision=0)

    again = save(
        client, admin_alice, seed.company_a, case_id, {"incident.history": "new"}, revision=1
    )

    assert again.status_code == 200
    assert again.json()["workflow"]["revision"] == 1
    assert count(sessions, WorkflowSubmission) == 1


@pytest.mark.parametrize(
    ("answers", "location"),
    [
        ({"incident.narrative": " " + NARRATIVE}, "incident.narrative"),
        ({"incident.narrative": "x" * 4001}, "incident.narrative"),
        ({"incident.date": "2999-01-01"}, "incident.date"),
        ({"incident.history": "serious"}, "incident.history"),
        ({"incident.severity": "high"}, "incident.severity"),
    ],
)
def test_invalid_answers_are_refused_without_echoing_them(
    client: TestClient,
    sessions: sessionmaker[Session],
    seed: SeedData,
    admin_alice: dict[str, str],
    answers: dict[str, object],
    location: str,
) -> None:
    case_id = create(client, admin_alice, seed.company_a).json()["id"]

    response = save(client, admin_alice, seed.company_a, case_id, answers, revision=0)

    assert response.status_code == 422
    assert [e["loc"] for e in response.json()["detail"]] == [["body", "answers", location]]
    for value in answers.values():
        assert str(value).strip()[:40] not in response.text
    assert count(sessions, WorkflowSubmission) == 0


@pytest.mark.parametrize(
    "body",
    [
        {"submission_key": str(uuid.uuid4()), "answers": {}},
        {"expected_revision": -1, "submission_key": str(uuid.uuid4()), "answers": {}},
        {"expected_revision": "0", "submission_key": str(uuid.uuid4()), "answers": {}},
        {"expected_revision": 0, "answers": {}},
        {"expected_revision": 0, "submission_key": str(uuid.uuid4()), "answers": {"k": 1}},
        {
            "expected_revision": 0,
            "submission_key": str(uuid.uuid4()),
            "answers": {},
            "revision": 9,
        },
    ],
)
def test_malformed_saves_are_refused(
    client: TestClient, seed: SeedData, admin_alice: dict[str, str], body: dict[str, object]
) -> None:
    case_id = create(client, admin_alice, seed.company_a).json()["id"]
    response = client.put(
        f"/companies/{seed.company_a}/cases/{case_id}{STEP_ANSWERS}", headers=admin_alice, json=body
    )
    assert response.status_code == 422


def test_case_content_never_reaches_the_logs(
    client: TestClient,
    seed: SeedData,
    admin_alice: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    title = "[SYNTHETIC] Unique title 7f3a"
    case_id = create(client, admin_alice, seed.company_a, title=title).json()["id"]
    save(
        client, admin_alice, seed.company_a, case_id, {"incident.narrative": NARRATIVE}, revision=0
    )
    save(client, admin_alice, seed.company_a, case_id, {"incident.narrative": " bad"}, revision=1)

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert title not in logged
    assert "A team member left the site" not in logged
