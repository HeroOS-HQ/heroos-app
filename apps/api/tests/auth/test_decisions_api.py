"""Employer decision records and the unified case history (M2-04) through the real application.

Same harness as test_progression_api.py: ``create_app`` with staging settings,
Cognito tokens verified by the production provider and in-memory SQLite built
from the real models (RLS, grants, the database's own refusals and real
concurrency are proven on PostgreSQL in
tests/tenant_isolation/test_workflow_decisions.py).

Covers: recording a factual record; finding it again after a refresh and a new
sign-in; the unified history (sources, natures, order, pagination); corrections
and clarifications that keep the original and say which version is current;
cross-case and cross-Company corrections; a superseded version that can't be
corrected again; retries, stale revisions and reused keys; members and other
Companies; forged actors, approvals and unsafe categories; that a record never
releases a hold, completes a stage, counts as a warning or needs installed
rules; that nothing else is written; and that no sensitive answer or record
text reaches the history or the logs.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.db.base import Base
from app.db.models import (
    CaseFact,
    Membership,
    WorkflowDecisionRecord,
    WorkflowEvaluation,
    WorkflowInstance,
    WorkflowProgressEvent,
    WorkflowSubmission,
)
from tests.auth.conftest import CognitoTokenFactory, SeedData, bearer
from tests.auth.test_company_admin_api import make_admin
from tests.auth.test_intake_api import CLEAR, put, view
from tests.auth.test_progression_api import (  # noqa: F401  (pytest fixtures)
    client,
    no_rules_client,
    pathway,
    progression_client,
    recorded_case,
    transition,
)
from tests.auth.test_workflow_api import (  # noqa: F401  (pytest fixtures)
    CONFLICT,
    FORBIDDEN,
    NOT_FOUND,
    admin_alice,
    alice,
    bob,
    create,
    sessions,
)

SUMMARY = "[SYNTHETIC] Manager reviewed the shift handover logs"
EXPLANATION = "[SYNTHETIC] The operations lead compared two weeks of logs.\nNo other issue found."
ROLE = "[SYNTHETIC] Operations lead"
EVIDENCE = [
    {"kind": "internal_document", "description": "[SYNTHETIC] Handover log, weeks 40-41"},
    {"kind": "meeting_note", "description": "[SYNTHETIC] Review notes", "reference": "HR-2026-014"},
]
# Labels of the sensitive screening questions (never repeated in any history).
SCREENING_WORDS = ("pregnan", "maternity", "sick leave", "medical", "whistleblow")


def record_body(revision: int, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "expected_revision": revision,
        "request_key": str(uuid.uuid4()),
        "category": "internal_review_completed",
        "summary": SUMMARY,
        "explanation": EXPLANATION,
        "occurred_on": "2026-10-12",
        "decision_maker": "other",
        "decision_maker_role": ROLE,
        "evidence_status": "held",
        "evidence": EVIDENCE,
    }
    body.update(overrides)
    return {key: value for key, value in body.items() if value is not ...}


def record(
    client: TestClient,  # noqa: F811
    headers: dict[str, str],
    company: uuid.UUID,
    case_id: str,
    body: dict[str, Any],
) -> Any:
    path = f"/companies/{company}/cases/{case_id}/decisions"
    return client.post(path, headers=headers, json=body)


def correct(
    client: TestClient,  # noqa: F811
    headers: dict[str, str],
    company: uuid.UUID,
    case_id: str,
    record_id: str,
    body: dict[str, Any],
    *,
    relation: str = "correction",
    reason: str = "[SYNTHETIC] The review date was wrong.",
) -> Any:
    return client.post(
        f"/companies/{company}/cases/{case_id}/decisions/{record_id}/corrections",
        headers=headers,
        json={**body, "relation": relation, "change_reason": reason},
    )


def history(
    client: TestClient,  # noqa: F811
    headers: dict[str, str],
    company: uuid.UUID,
    case_id: str,
    **params: Any,
) -> Any:
    return client.get(
        f"/companies/{company}/cases/{case_id}/history", headers=headers, params=params
    )


def count(sessions: sessionmaker[Session], model: type[Base]) -> int:  # noqa: F811
    with sessions() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


def counts(sessions: sessionmaker[Session]) -> dict[str, int]:  # noqa: F811
    return {
        model.__tablename__: count(sessions, model)
        for model in (
            WorkflowSubmission,
            CaseFact,
            WorkflowEvaluation,
            WorkflowProgressEvent,
            WorkflowDecisionRecord,
        )
    }


def new_case(
    client: TestClient,  # noqa: F811
    headers: dict[str, str],
    seed: SeedData,
) -> str:
    created = create(client, headers, seed.company_a)
    assert created.status_code == 201
    case_id: str = created.json()["id"]
    return case_id


# --- recording, persistence and the history --------------------------------------------


def test_an_administrator_records_a_factual_decision_and_finds_it_again(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    make_cognito_token: CognitoTokenFactory,
) -> None:
    case_id = new_case(client, admin_alice, seed)
    saved = record(client, admin_alice, seed.company_a, case_id, record_body(0))
    assert saved.status_code == 200, saved.json()
    body = saved.json()
    decisions = body["decisions"]
    (stored,) = decisions["records"]
    assert decisions["saved"] == stored["id"]
    assert stored["current"] is True and stored["version"] == 1
    assert stored["relation"] == "original" and stored["supersedes"] is None
    assert stored["category"] == "internal_review_completed"
    assert stored["category_label"] == "Internal review completed"
    assert (stored["summary"], stored["explanation"]) == (SUMMARY, EXPLANATION)
    assert stored["occurred_on"] == "2026-10-12"
    # The named decision-maker is the employer's statement; the actor is the session.
    assert (stored["decision_maker"], stored["decision_maker_role"]) == ("other", ROLE)
    assert stored["recorded_by_viewer"] is True
    assert stored["evidence_status"] == "held"
    assert [e["description"] for e in stored["evidence"]] == [e["description"] for e in EVIDENCE]
    assert stored["evidence"][1]["reference"] == "HR-2026-014"
    assert stored["evidence"][0]["kind_label"] == "Internal document"
    # The workflow context at the time (rules installed, jurisdiction unconfirmed).
    assert stored["context"] == {
        "revision": 1,
        "intake_status": "awaiting_jurisdiction",
        "progression_status": "paused",
    }
    # A record is a Case write: it takes a revision like any other.
    assert body["workflow"]["revision"] == 1
    # And it's the newest entry of the unified history at once.
    first = body["timeline"]["entries"][0]
    assert first["id"] == f"decision:{stored['id']}"
    assert first["nature"] == "employer_record" and first["kind"] == "decision_recorded"
    assert first["title"] == "Employer record: Internal review completed"
    assert first["status"] == "current" and first["by_viewer"] is True
    assert first["source"] == {"type": "decision_record", "id": stored["id"]}

    # A refresh and a new sign-in (a new token) read the same from the database.
    with sessions() as db:
        row = db.scalar(select(WorkflowDecisionRecord))
        assert row is not None and row.recorded_by_user_id == seed.alice
    for headers in (admin_alice, bearer(make_cognito_token("alice-subject"))):
        again = view(client, headers, seed.company_a, case_id)
        assert again["decisions"]["records"] == decisions["records"]
        assert again["decisions"]["saved"] is None
        listed = client.get(f"/companies/{seed.company_a}/cases/{case_id}/decisions",
                            headers=headers)  # fmt: skip
        assert listed.status_code == 200
        assert listed.json()["records"] == decisions["records"]
        page = history(client, headers, seed.company_a, case_id)
        assert page.status_code == 200
        assert [e["id"] for e in page.json()["entries"]] == [
            f"decision:{stored['id']}",
            "created",
        ]


def test_the_categories_are_factual_only(
    client: TestClient,  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    response = client.get(
        f"/companies/{seed.company_a}/workflows/disciplinary/decision-categories",
        headers=admin_alice,
    )
    assert response.status_code == 200
    options = response.json()
    keys = [c["key"] for c in options["categories"]]
    assert keys == [
        "internal_review_completed",
        "information_requested",
        "meeting_recorded",
        "employer_observation",
        "internal_pause_or_follow_up",
        "other_note",
    ]
    text = " ".join(f"{c['key']} {c['label']} {c['description']}" for c in options["categories"])
    for word in ("warning", "suspen", "penalt", "dismiss", "terminat", "approv", "misconduct"):
        assert word not in text.lower()
    assert "isn't a warning, a penalty" in options["notice"]
    assert "can't be recorded here" in options["not_recordable"]
    assert options["limits"]["summary"] == 200 and options["limits"]["evidence_items"] == 10
    unknown = client.get(
        f"/companies/{seed.company_a}/workflows/probation/decision-categories", headers=admin_alice
    )
    assert (unknown.status_code, unknown.json()) == NOT_FOUND


@pytest.mark.parametrize(
    "category",
    [
        "formal_warning_issued",
        "suspension_imposed",
        "financial_penalty_imposed",
        "employment_terminated",
        "serious_misconduct_established",
        "specialist_review_approved",
    ],
)
def test_unsafe_categories_are_refused(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    category: str,
) -> None:
    case_id = new_case(client, admin_alice, seed)
    response = record(client, admin_alice, seed.company_a, case_id,
                      record_body(0, category=category))  # fmt: skip
    assert response.status_code == 422
    assert [e["loc"] for e in response.json()["detail"]] == [["body", "category"]]
    assert count(sessions, WorkflowDecisionRecord) == 0


@pytest.mark.parametrize(
    ("overrides", "loc"),
    [
        # The actor comes from the session; no approval or status can be sent.
        ({"recorded_by_user_id": "00000000-0000-4000-8000-000000000001"}, "recorded_by_user_id"),
        ({"actor_user_id": "00000000-0000-4000-8000-000000000001"}, "actor_user_id"),
        ({"legal_approval": True}, "legal_approval"),
        ({"authorizes_transition": "complete:test_check_in"}, "authorizes_transition"),
        ({"status": "approved"}, "status"),
        ({"summary": ""}, "summary"),
        ({"summary": " leading space"}, "summary"),
        ({"summary": "two\nlines"}, "summary"),
        ({"summary": "x" * 201}, "summary"),
        ({"explanation": "x" * 4001}, "explanation"),
        ({"explanation": "bell\u0007"}, "explanation"),
        ({"occurred_on": "12/10/2026"}, "occurred_on"),
        ({"occurred_on": "2026-10-12T00:00:00"}, "occurred_on"),
        ({"occurred_on": 20261012}, "occurred_on"),
        ({"occurred_on": "1989-12-31"}, "occurred_on"),
        ({"decision_maker": "recorder"}, "decision_maker_role"),
        ({"decision_maker_role": ...}, "decision_maker_role"),
        ({"decision_maker": "the_ceo"}, "decision_maker"),
        ({"evidence_status": "none"}, "evidence"),
        ({"evidence": []}, "evidence"),
        ({"evidence": [{"kind": "upload", "description": "x"}]}, "evidence"),
        (
            {"evidence": [{"kind": "policy", "description": "https://example.invalid/f"}]},
            "evidence",
        ),
        ({"evidence": [{"kind": "policy", "description": "see www.example.invalid"}]}, "evidence"),
        (
            {"evidence": [{"kind": "policy", "description": "x", "reference": "file://srv/x"}]},
            "evidence",
        ),
        ({"evidence": [{"kind": "policy", "description": "javascript:alert(1)"}]}, "evidence"),
        ({"evidence": [{"kind": "policy", "description": "x", "url": "x"}]}, "evidence"),
        ({"evidence": [{"kind": "policy", "description": f"{i}"} for i in range(11)]}, "evidence"),
        ({"expected_revision": -1}, "expected_revision"),
        ({"request_key": "not-a-key"}, "request_key"),
    ],  # fmt: skip
)
def test_invalid_or_forged_records_are_refused_without_echoing_them(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    overrides: dict[str, Any],
    loc: str,
) -> None:
    case_id = new_case(client, admin_alice, seed)
    response = record(client, admin_alice, seed.company_a, case_id,
                      record_body(0, **overrides))  # fmt: skip
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert {e["loc"][1] for e in detail} == {loc}
    assert all(set(e) <= {"type", "loc", "msg"} for e in detail)
    text = response.text
    for value in ("example.invalid", "alert(1)", "leading space", "the_ceo", SUMMARY):
        assert value not in text
    assert count(sessions, WorkflowDecisionRecord) == 0


def test_a_future_date_is_refused_but_a_time_zone_ahead_is_allowed(
    client: TestClient,  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = new_case(client, admin_alice, seed)
    today = datetime.now(UTC).date()
    future = record(client, admin_alice, seed.company_a, case_id,
                    record_body(0, occurred_on=str(today + timedelta(days=2))))  # fmt: skip
    assert future.status_code == 422
    ahead = record(client, admin_alice, seed.company_a, case_id,
                   record_body(0, occurred_on=str(today + timedelta(days=1))))  # fmt: skip
    assert ahead.status_code == 200


def test_the_employer_may_say_no_evidence_is_available_or_not_sure(
    client: TestClient,  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = new_case(client, admin_alice, seed)
    revision = 0
    for status in ("none", "not_sure"):
        saved = record(client, admin_alice, seed.company_a, case_id,
                       record_body(revision, evidence_status=status, evidence=...,
                                   decision_maker="recorder", decision_maker_role=...))  # fmt: skip
        assert saved.status_code == 200, saved.json()
        revision = saved.json()["workflow"]["revision"]
        newest = saved.json()["decisions"]["records"][0]
        assert (newest["evidence_status"], newest["evidence"]) == (status, [])
        assert (newest["decision_maker"], newest["decision_maker_role"]) == ("recorder", None)


# --- corrections and clarifications ----------------------------------------------------


def test_a_correction_keeps_the_original_and_says_which_version_is_current(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = new_case(client, admin_alice, seed)
    first = record(client, admin_alice, seed.company_a, case_id, record_body(0)).json()
    original = first["decisions"]["records"][0]
    corrected = correct(client, admin_alice, seed.company_a, case_id, original["id"],
                        record_body(1, occurred_on="2026-10-13"))  # fmt: skip
    assert corrected.status_code == 200, corrected.json()
    records = corrected.json()["decisions"]["records"]
    assert [r["version"] for r in records] == [2, 1]
    newest, earlier = records
    assert corrected.json()["decisions"]["saved"] == newest["id"]
    assert (newest["relation"], newest["supersedes"], newest["current"]) == (
        "correction",
        original["id"],
        True,
    )
    assert newest["change_reason"] == "[SYNTHETIC] The review date was wrong."
    assert newest["chain_id"] == original["id"] == earlier["chain_id"]
    # The original is unchanged and marked superseded, never erased.
    assert earlier["id"] == original["id"] and earlier["current"] is False
    assert earlier["superseded_by"] == newest["id"]
    assert {k: v for k, v in earlier.items() if k not in ("current", "superseded_by")} == {
        k: v for k, v in original.items() if k not in ("current", "superseded_by")
    }
    # A clarification adds a third version on top.
    clarified = correct(client, admin_alice, seed.company_a, case_id, newest["id"],
                        record_body(2, explanation=f"{EXPLANATION}\nThe logs are kept by HR."),
                        relation="clarification",
                        reason="[SYNTHETIC] Added where the logs are.")  # fmt: skip
    assert clarified.status_code == 200
    versions = clarified.json()["decisions"]["records"]
    assert [(r["version"], r["relation"], r["current"]) for r in versions] == [
        (3, "clarification", True),
        (2, "correction", False),
        (1, "original", False),
    ]
    assert count(sessions, WorkflowDecisionRecord) == 3
    # The history keeps every version, says which is current and links them.
    entries = clarified.json()["timeline"]["entries"]
    decisions = [e for e in entries if e["category"] == "decisions"]
    assert [(e["kind"], e["status"]) for e in decisions] == [
        ("decision_clarified", "current"),
        ("decision_corrected", "superseded"),
        ("decision_recorded", "superseded"),
    ]
    assert decisions[0]["title"] == "Employer record clarified: Internal review completed"
    assert decisions[1]["link"] == {
        "relation": "correction",
        "supersedes": f"decision:{original['id']}",
        "superseded_by": f"decision:{versions[0]['id']}",
    }
    assert "A later version replaced this one." in decisions[2]["detail"]


def test_only_the_current_version_can_be_corrected(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = new_case(client, admin_alice, seed)
    original = record(client, admin_alice, seed.company_a, case_id, record_body(0)).json()
    original_id = original["decisions"]["records"][0]["id"]
    assert correct(client, admin_alice, seed.company_a, case_id, original_id,
                   record_body(1)).status_code == 200  # fmt: skip
    # The superseded original can't start a second line (no branch, no cycle).
    again = correct(client, admin_alice, seed.company_a, case_id, original_id, record_body(2))
    assert (again.status_code, again.json()) == CONFLICT
    assert count(sessions, WorkflowDecisionRecord) == 2


def test_cross_case_and_unknown_corrections_are_not_found(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_x = new_case(client, admin_alice, seed)
    case_y = new_case(client, admin_alice, seed)
    in_x = record(client, admin_alice, seed.company_a, case_x, record_body(0)).json()
    record_id = in_x["decisions"]["records"][0]["id"]
    # Case Y's route can't reach a record of Case X: it doesn't exist there.
    for target in (record_id, str(uuid.uuid4())):
        response = correct(client, admin_alice, seed.company_a, case_y, target, record_body(0))
        assert (response.status_code, response.json()) == NOT_FOUND
    assert count(sessions, WorkflowDecisionRecord) == 1
    assert view(client, admin_alice, seed.company_a, case_y)["decisions"]["records"] == []


def test_a_retry_is_applied_once_and_a_reused_key_is_a_conflict(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = new_case(client, admin_alice, seed)
    body = record_body(0)
    first = record(client, admin_alice, seed.company_a, case_id, body)
    retried = record(client, admin_alice, seed.company_a, case_id, body)
    assert retried.status_code == 200
    assert retried.json()["decisions"]["saved"] == first.json()["decisions"]["saved"]
    assert retried.json()["workflow"]["revision"] == first.json()["workflow"]["revision"] == 1
    assert count(sessions, WorkflowDecisionRecord) == 1
    # The key identifies the request (as for answers and transitions): a retry
    # sent after the response was lost replays, whatever revision it carries.
    late = record(client, admin_alice, seed.company_a, case_id, {**body, "expected_revision": 1})
    assert late.json()["decisions"]["saved"] == first.json()["decisions"]["saved"]
    # The same key for different content is a conflict.
    for changed in ({"summary": "[SYNTHETIC] Something else"}, {"occurred_on": "2026-10-11"},
                    {"evidence_status": "none", "evidence": []}):  # fmt: skip
        reused = record(client, admin_alice, seed.company_a, case_id, {**body, **changed})
        assert (reused.status_code, reused.json()) == CONFLICT
    # A correction retried with its key is applied once too.
    original_id = first.json()["decisions"]["saved"]
    fix = record_body(1)
    one = correct(client, admin_alice, seed.company_a, case_id, original_id, fix)
    two = correct(client, admin_alice, seed.company_a, case_id, original_id, fix)
    assert (one.status_code, two.status_code) == (200, 200)
    assert one.json()["decisions"]["saved"] == two.json()["decisions"]["saved"]
    as_clarification = correct(client, admin_alice, seed.company_a, case_id, original_id, fix,
                               relation="clarification")  # fmt: skip
    assert (as_clarification.status_code, as_clarification.json()) == CONFLICT
    assert count(sessions, WorkflowDecisionRecord) == 2


def test_a_stale_revision_is_refused(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = new_case(client, admin_alice, seed)
    first = record(client, admin_alice, seed.company_a, case_id, record_body(0)).json()
    stale = record(client, admin_alice, seed.company_a, case_id, record_body(0))
    assert (stale.status_code, stale.json()) == CONFLICT
    # Answers saved since the form was read make a correction stale too.
    answered = put(client, admin_alice, seed.company_a, case_id, "initial_facts",
                   {"incident.history": "new"}, revision=1)  # fmt: skip
    assert answered.json()["workflow"]["revision"] == 2
    stale_fix = correct(client, admin_alice, seed.company_a, case_id,
                        first["decisions"]["saved"], record_body(1))  # fmt: skip
    assert (stale_fix.status_code, stale_fix.json()) == CONFLICT
    # And a record makes an answer form that was read before it stale.
    stale_answers = put(client, admin_alice, seed.company_a, case_id, "initial_facts",
                        {"incident.history": "not_sure"}, revision=1)  # fmt: skip
    assert (stale_answers.status_code, stale_answers.json()) == CONFLICT
    assert count(sessions, WorkflowDecisionRecord) == 1


# --- access ----------------------------------------------------------------------------


def test_members_can_neither_read_nor_record_decisions(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = new_case(client, admin_alice, seed)
    saved = record(client, admin_alice, seed.company_a, case_id, record_body(0)).json()
    record_id = saved["decisions"]["saved"]
    with sessions() as db:
        db.execute(update(Membership).values(role="member"))
        db.commit()
    company = seed.company_a
    for response in (
        client.get(f"/companies/{company}/cases/{case_id}/decisions", headers=admin_alice),
        client.get(f"/companies/{company}/cases/{case_id}/history", headers=admin_alice),
        client.get(f"/companies/{company}/workflows/disciplinary/decision-categories",
                   headers=admin_alice),
        record(client, admin_alice, company, case_id, record_body(1)),
        correct(client, admin_alice, company, case_id, record_id, record_body(1)),
    ):  # fmt: skip
        assert (response.status_code, response.json()) == FORBIDDEN
    assert count(sessions, WorkflowDecisionRecord) == 1


def test_another_company_can_neither_read_nor_correct_the_records(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    bob: dict[str, str],  # noqa: F811
) -> None:
    case_id = new_case(client, admin_alice, seed)
    saved = record(client, admin_alice, seed.company_a, case_id, record_body(0)).json()
    record_id = saved["decisions"]["saved"]
    make_admin(sessions, seed.company_b, seed.bob)
    b = seed.company_b
    # Through Company B's routes, A's Case and record are not found (like random ids).
    for response in (
        client.get(f"/companies/{b}/cases/{case_id}/decisions", headers=bob),
        client.get(f"/companies/{b}/cases/{case_id}/history", headers=bob),
        record(client, bob, b, case_id, record_body(1)),
        correct(client, bob, b, case_id, record_id, record_body(1)),
    ):
        assert (response.status_code, response.json()) == NOT_FOUND
    # Bob's own Case can't reach A's record either (cross-tenant supersession).
    bobs_case = create(client, bob, b).json()["id"]
    response = correct(client, bob, b, bobs_case, record_id, record_body(0))
    assert (response.status_code, response.json()) == NOT_FOUND
    # Through Company A's routes: forbidden.
    for response in (
        client.get(f"/companies/{seed.company_a}/cases/{case_id}/history", headers=bob),
        correct(client, bob, seed.company_a, case_id, record_id, record_body(1)),
    ):
        assert (response.status_code, response.json()) == FORBIDDEN
    assert count(sessions, WorkflowDecisionRecord) == 1


# --- a record is never a workflow authorization ----------------------------------------


def test_a_record_never_releases_an_intake_hold(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    held = {**CLEAR, "screening.whistleblower": "yes"}
    case_id, revision = recorded_case(client, sessions, seed, admin_alice, screening=held)
    before = view(client, admin_alice, seed.company_a, case_id)
    assert before["status"]["code"] == "held_for_specialist_review"
    claim = "[SYNTHETIC] Specialist review done, hold cleared"
    body = record_body(revision, category="internal_pause_or_follow_up", summary=claim)
    saved = record(client, admin_alice, seed.company_a, case_id, body)
    assert saved.status_code == 200
    after = saved.json()
    assert after["decisions"]["records"][0]["context"]["intake_status"] == (
        "held_for_specialist_review"
    )
    assert after["decisions"]["records"][0]["context"]["progression_status"] == "held"
    # Everything the hold decides is exactly as before.
    for key in ("status", "intake", "steps", "progress", "not_available"):
        assert after[key] == before[key], key
    assert after["progression"]["gate"]["code"] == "case_held"
    assert after["progression"]["status"] == before["progression"]["status"]
    events = count(sessions, WorkflowProgressEvent)
    refused = pathway(client, admin_alice, seed.company_a, case_id, "less_serious",
                      revision=after["workflow"]["revision"])  # fmt: skip
    assert refused.json()["progression"]["attempt"]["outcome"] == "rejected"
    assert refused.json()["progression"]["pathway"] is None
    assert count(sessions, WorkflowProgressEvent) == events + 1


def test_a_record_never_completes_a_stage_or_counts_as_a_warning(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    chosen = pathway(client, admin_alice, seed.company_a, case_id, "less_serious",
                     revision=revision)  # fmt: skip
    started = transition(client, admin_alice, seed.company_a, case_id, "start:test_check_in",
                         revision=chosen.json()["workflow"]["revision"])  # fmt: skip
    before = started.json()
    assert before["progression"]["status"]["code"] == "in_stage"
    stored_before = counts(sessions)
    revision = before["workflow"]["revision"]
    for category, summary in (
        ("meeting_recorded", "[SYNTHETIC] Check-in held; stage complete"),
        ("other_note", "[SYNTHETIC] Formal written warning issued today"),
        ("employer_observation", "[SYNTHETIC] Serious misconduct established; dismissed"),
    ):
        saved = record(client, admin_alice, seed.company_a, case_id,
                       record_body(revision, category=category, summary=summary))  # fmt: skip
        assert saved.status_code == 200
        after = saved.json()
        revision = after["workflow"]["revision"]
        # The stage is still in progress, its completion still refused, no
        # warning or outcome exists, and nothing but the record was written.
        assert after["progression"]["stages"] == before["progression"]["stages"]
        assert after["progression"]["status"] == before["progression"]["status"]
        assert after["progression"]["actions"] == before["progression"]["actions"]
        assert after["progression"]["history"] == before["progression"]["history"]
        assert after["not_available"] == before["not_available"]
        assert after["answers"] == before["answers"]
    assert counts(sessions) == {**stored_before, "workflow_decision_records": 3}
    complete = transition(client, admin_alice, seed.company_a, case_id,
                          "complete:test_check_in", revision=revision)  # fmt: skip
    assert complete.json()["progression"]["attempt"]["outcome"] == "rejected"
    assert complete.json()["progression"]["status"]["code"] == "in_stage"


def test_records_need_no_installed_rules(
    no_rules_client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = new_case(no_rules_client, admin_alice, seed)
    saved = record(no_rules_client, admin_alice, seed.company_a, case_id, record_body(0))
    assert saved.status_code == 200
    body = saved.json()
    assert body["progression"]["gate"]["code"] == "rules_unavailable"
    assert body["decisions"]["records"][0]["context"]["progression_status"] == "unavailable"
    fixed = correct(no_rules_client, admin_alice, seed.company_a, case_id,
                    body["decisions"]["saved"], record_body(1))  # fmt: skip
    assert fixed.status_code == 200
    assert counts(sessions)["workflow_progress_events"] == 0


# --- the unified history ---------------------------------------------------------------


def test_the_history_unifies_every_source_without_sensitive_answers(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    chosen = pathway(client, admin_alice, seed.company_a, case_id, "less_serious",
                     revision=revision).json()  # fmt: skip
    revision = chosen["workflow"]["revision"]
    skipped = transition(client, admin_alice, seed.company_a, case_id, "start:test_final_review",
                         revision=revision).json()  # fmt: skip
    assert skipped["progression"]["attempt"]["outcome"] == "rejected"
    saved = record(client, admin_alice, seed.company_a, case_id, record_body(revision)).json()
    # Answers that change the screening after it was recorded: a hold now.
    held = put(client, admin_alice, seed.company_a, case_id, "safety_screening",
               {"screening.pregnancy_maternity": "yes", "screening.sick_leave": "yes"},
               revision=saved["workflow"]["revision"]).json()  # fmt: skip
    assert held["status"]["code"] == "held_for_specialist_review"

    page = history(client, admin_alice, seed.company_a, case_id, limit=100).json()
    entries = page["entries"]
    assert page["total"] == len(entries) and page["next_before"] is None
    kinds = [e["kind"] for e in reversed(entries)]
    assert kinds[0] == "case_created"
    for kind in ("answers_saved", "jurisdiction", "screening", "intake_recorded",
                 "pathway_selected", "transition_rejected", "decision_recorded",
                 "hold_placed"):  # fmt: skip
        assert kind in kinds, kind
    natures = {e["kind"]: e["nature"] for e in entries}
    assert natures["answers_saved"] == "employer_record"
    assert natures["decision_recorded"] == "employer_record"
    assert natures["intake_recorded"] == "system_check"
    assert natures["hold_placed"] == "system_check"
    assert natures["transition_rejected"] == "refused_request"
    assert natures["pathway_selected"] == "workflow_change"
    rejected = next(e for e in entries if e["kind"] == "transition_rejected")
    assert rejected["status"] == "refused" and "didn't move on" in rejected["detail"]
    # Same sources as the per-source histories, nothing invented or dropped.
    ids = {e["id"] for e in entries}
    assert {h["id"] for h in held["history"]} <= ids
    assert {h["id"] for h in held["progression"]["history"]} <= ids
    # Causal order: the record before the save that placed the hold.
    order = [e["id"] for e in reversed(entries)]
    decision_id = f"decision:{saved['decisions']['saved']}"
    hold = next(e["id"] for e in entries if e["kind"] == "hold_placed")
    assert order.index(decision_id) < order.index(hold)
    # No screening answer, sensitive label or record explanation is restated.
    text = " ".join(f"{e['title']} {e['detail'] or ''}" for e in entries).lower()
    for word in SCREENING_WORDS:
        assert word not in text, word
    assert "2 screening answers" in text
    assert EXPLANATION.lower() not in text and ROLE.lower() not in text
    assert "handover log, weeks" not in text  # evidence stays with the record
    assert SUMMARY.lower() in text


def test_the_history_order_is_deterministic_and_pages_cover_it_exactly_once(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = new_case(client, admin_alice, seed)
    revision = 0
    for index in range(7):
        saved = record(client, admin_alice, seed.company_a, case_id,
                       record_body(revision, summary=f"[SYNTHETIC] Note {index}"))  # fmt: skip
        revision = saved.json()["workflow"]["revision"]
    # SQLite's CURRENT_TIMESTAMP has one-second resolution: these share timestamps,
    # so the order rests on the revision, never on the clock.
    full = history(client, admin_alice, seed.company_a, case_id, limit=100).json()
    assert full == history(client, admin_alice, seed.company_a, case_id, limit=100).json()
    summaries = [e["detail"] for e in full["entries"] if e["category"] == "decisions"]
    assert summaries == [f"“[SYNTHETIC] Note {i}”" for i in reversed(range(7))]
    assert full["total"] == 8

    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": 3} if cursor is None else {"limit": 3, "before": cursor}
        page = history(client, admin_alice, seed.company_a, case_id, **params).json()
        seen += [e["id"] for e in page["entries"]]
        assert page["total"] == 8 and len(page["entries"]) <= 3
        cursor = page["next_before"]
        if cursor is None:
            break
    assert seen == [e["id"] for e in full["entries"]]
    # The view carries the first page.
    first = view(client, admin_alice, seed.company_a, case_id)["timeline"]
    assert [e["id"] for e in first["entries"]] == seen[:8] and first["next_before"] is None

    for params in ({"limit": 0}, {"limit": 101}, {"before": "Not A Cursor"},
                   {"before": f"decision:{uuid.uuid4()}"}, {"before": "x" * 201}):  # fmt: skip
        bad = history(client, admin_alice, seed.company_a, case_id, **params)
        assert bad.status_code == 422, params
        assert "Not A Cursor" not in bad.text


def test_records_are_never_logged(
    client: TestClient,  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    case_id = new_case(client, admin_alice, seed)
    saved = record(client, admin_alice, seed.company_a, case_id, record_body(0)).json()
    correct(client, admin_alice, seed.company_a, case_id, saved["decisions"]["saved"],
            record_body(1))  # fmt: skip
    record(client, admin_alice, seed.company_a, case_id, record_body(0, summary="bad\n"))
    logged = caplog.text
    assert "Workflow decision recorded" in logged and "relation=correction" in logged
    for value in (SUMMARY, EXPLANATION, ROLE, "HR-2026-014", "Handover log", "review date"):
        assert value not in logged


def test_an_instance_revision_belongs_to_one_write(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = new_case(client, admin_alice, seed)
    revision = 0
    for step in range(3):
        if step % 2:
            response = put(client, admin_alice, seed.company_a, case_id, "initial_facts",
                           {"incident.history": "new" if step == 1 else "not_sure"},
                           revision=revision)  # fmt: skip
        else:
            response = record(client, admin_alice, seed.company_a, case_id,
                              record_body(revision))  # fmt: skip
        assert response.status_code == 200
        revision = response.json()["workflow"]["revision"]
    with sessions() as db:
        submissions = set(db.scalars(select(WorkflowSubmission.revision)).all())
        decided = set(db.scalars(select(WorkflowDecisionRecord.revision)).all())
        instance = db.scalar(select(WorkflowInstance.revision))
    assert submissions == {2} and decided == {1, 3} and instance == 3


@pytest.mark.parametrize("screening", ["disabled"])
def test_records_work_with_the_default_screening_setting(
    sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    screening: str,
) -> None:
    default = progression_client(sessions, cognito_provider, screening=screening, rules=False)
    case_id = new_case(default, admin_alice, seed)
    saved = record(default, admin_alice, seed.company_a, case_id, record_body(0))
    assert saved.status_code == 200
    assert saved.json()["sensitive_screening"] == "disabled"
