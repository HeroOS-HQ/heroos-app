"""The Disciplinary intake through the real application (M2-02).

Same harness as test_workflow_api.py: ``create_app`` with staging settings,
Cognito tokens verified by the production provider and in-memory SQLite built
from the real models (no RLS; the database layer, grants, isolation and
concurrency are proven on PostgreSQL in tests/tenant_isolation).

Covers the intake journey for a UAE Federal Company (jurisdiction confirmed for
the Case, incident context, safety screening, intake recorded), the holds
(unconfirmed or different jurisdiction, a high-risk answer, a DIFC Case with no
approved screening), "Not sure" never clearing anything, correcting answers,
the stored evaluation per save, the history, M2-01 Cases continuing into the
intake, and that a hold creates nothing but its own trace (no expert ticket).
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import (
    Case,
    CaseFact,
    CompanyBlueprint,
    Membership,
    WorkflowEvaluation,
    WorkflowInstance,
    WorkflowSubmission,
)
from app.workflows.definition import SAFETY_SCREENING
from tests.auth.conftest import SeedData
from tests.auth.test_workflow_api import (  # noqa: F401  (pytest fixtures)
    CONFLICT,
    FORBIDDEN,
    NARRATIVE,
    admin_alice,
    alice,
    client,
    create,
    sessions,
)

INITIAL = {
    "incident.narrative": NARRATIVE,
    "incident.date": "2026-10-10",
    "incident.history": "new",
    "incident.discussed_with_employee": "yes",
    "incident.evidence_available": "yes",
}
CONTEXT = {
    "context.location": "at_work",
    "history.same_incident_sanction": "no",
    "context.policy_awareness": "yes",
    "evidence.witnesses": "yes",
}
CLEAR = {q.key: "no" for q in SAFETY_SCREENING.questions}
FEDERAL_LABEL = "UAE Federal (MOHRE)"


def confirm_jurisdiction(
    sessions: sessionmaker[Session],  # noqa: F811
    company: uuid.UUID,
    jurisdiction: str,
) -> None:
    """An operator-confirmed Company jurisdiction (synthetic licensing answer)."""
    location, authority = (
        ("difc", None) if jurisdiction == "difc" else ("other", "[SYNTHETIC] Licensing authority")
    )
    with sessions() as db:
        db.add(
            CompanyBlueprint(
                company_id=company,
                licensing_location=location,
                licensing_authority=authority,
                employment_jurisdiction=jurisdiction,
                confirmed_licensing_location=location,
                confirmed_licensing_authority=authority,
                jurisdiction_confirmed_at=datetime(2026, 10, 1, tzinfo=UTC),
            )
        )
        db.commit()


def view(client: TestClient, headers: dict[str, str], company: uuid.UUID, case_id: str) -> Any:  # noqa: F811
    response = client.get(f"/companies/{company}/cases/{case_id}/workflow", headers=headers)
    assert response.status_code == 200
    return response.json()


def put(
    client: TestClient,  # noqa: F811
    headers: dict[str, str],
    company: uuid.UUID,
    case_id: str,
    step: str,
    answers: dict[str, object],
    *,
    revision: int,
    key: str | None = None,
) -> Any:
    return client.put(
        f"/companies/{company}/cases/{case_id}/workflow/steps/{step}/answers",
        headers=headers,
        json={
            "expected_revision": revision,
            "submission_key": key or str(uuid.uuid4()),
            "answers": answers,
        },
    )


def stored_evaluations(sessions: sessionmaker[Session]) -> list[WorkflowEvaluation]:  # noqa: F811
    with sessions() as db:
        return list(
            db.scalars(select(WorkflowEvaluation).order_by(WorkflowEvaluation.evaluated_at)).all()
        )


def count(sessions: sessionmaker[Session], model: type[Base]) -> int:  # noqa: F811
    with sessions() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


def fed_case(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    headers: dict[str, str],
) -> str:
    """A UAE Federal Case with the initial facts and the Case jurisdiction saved (revision 2)."""
    confirm_jurisdiction(sessions, seed.company_a, "uae_federal")
    case_id: str = create(client, headers, seed.company_a).json()["id"]
    assert (
        put(
            client, headers, seed.company_a, case_id, "initial_facts", INITIAL, revision=0
        ).status_code
        == 200
    )
    confirmed = put(
        client,
        headers,
        seed.company_a,
        case_id,
        "jurisdiction",
        {"jurisdiction.case_confirmation": "uae_federal"},
        revision=1,
    )
    assert confirmed.status_code == 200
    return case_id


# --- the UAE Federal intake -----------------------------------------------------------


def test_a_uae_federal_intake_is_recorded_after_a_clear_screening(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    confirm_jurisdiction(sessions, seed.company_a, "uae_federal")
    case_id = create(client, admin_alice, seed.company_a).json()["id"]
    fresh = view(client, admin_alice, seed.company_a, case_id)
    assert fresh["status"]["code"] == "case_created"
    jurisdiction_step = next(s for s in fresh["steps"] if s["key"] == "jurisdiction")
    assert jurisdiction_step["available"] is True
    assert jurisdiction_step["questions"][0]["options"] == [
        {"value": "uae_federal", "label": f"Yes, {FEDERAL_LABEL}"},
        {"value": "different", "label": "No, a different jurisdiction applies"},
        {"value": "not_sure", "label": "Not sure"},
    ]

    put(client, admin_alice, seed.company_a, case_id, "initial_facts", INITIAL, revision=0)
    confirmed = put(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        "jurisdiction",
        {"jurisdiction.case_confirmation": "uae_federal"},
        revision=1,
    ).json()
    assert confirmed["answer_labels"]["jurisdiction.case_confirmation"] == f"Yes, {FEDERAL_LABEL}"
    assert confirmed["answer_labels"]["incident.date"] == "10 October 2026"
    assert confirmed["intake"]["case_jurisdiction"] == {
        "status": "resolved",
        "jurisdiction": "uae_federal",
        "label": FEDERAL_LABEL,
        "company_jurisdiction": "uae_federal",
    }
    assert {s["key"]: s["available"] for s in confirmed["steps"]}["safety_screening"] is True
    put(client, admin_alice, seed.company_a, case_id, "incident_context", CONTEXT, revision=2)
    done = put(client, admin_alice, seed.company_a, case_id, "safety_screening", CLEAR, revision=3)

    assert done.status_code == 200
    body = done.json()
    assert body["status"] == {"code": "intake_recorded", "label": "Intake recorded"}
    assert body["intake"]["screening"] == "cleared"
    assert body["intake"]["hold"] is None
    assert body["intake"]["cautions"] == []
    assert body["intake"]["next_stage_open"] is True
    assert (body["missing"], body["uncertain"]) == ([], [])
    recorded = next(m for m in body["conversation"] if m["id"] == "intake_recorded")
    assert "not a legal assessment" in recorded["body"]

    # One stored evaluation per save, the last one matching the live state.
    evaluations = stored_evaluations(sessions)
    assert len(evaluations) == 4
    last = evaluations[-1]
    assert (last.status, last.hold, last.jurisdiction, last.screening) == (
        "intake_recorded",
        None,
        "uae_federal",
        "cleared",
    )
    assert (last.definition_version, last.ruleset_version) == (2, "disciplinary-intake.1")
    assert [r["condition"] for r in last.results][0] == "JURISDICTION-ROUTING-001"
    assert [h["kind"] for h in body["history"]][-3:] == [
        "answers_saved",
        "screening",
        "intake_recorded",
    ]

    # Reopened (a new request, as after a reload or a new sign-in): the same.
    reopened = view(client, admin_alice, seed.company_a, case_id)
    assert reopened["status"]["code"] == "intake_recorded"
    assert reopened["answers"] == {
        **INITIAL,
        "jurisdiction.case_confirmation": "uae_federal",
        **CONTEXT,
        **CLEAR,
    }
    listed = client.get(
        f"/companies/{seed.company_a}/workflows/disciplinary/cases", headers=admin_alice
    ).json()
    assert (listed[0]["status"]["code"], listed[0]["answered"], listed[0]["total"]) == (
        "intake_recorded",
        19,
        19,
    )


def test_a_high_risk_answer_holds_the_case_and_creates_no_ticket(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    case_id = fed_case(client, sessions, seed, admin_alice)
    put(client, admin_alice, seed.company_a, case_id, "incident_context", CONTEXT, revision=2)
    tables_before = set(inspect(sessions.kw["bind"]).get_table_names())

    held = put(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        "safety_screening",
        {**CLEAR, "screening.pregnancy_maternity": "yes"},
        revision=3,
    ).json()

    assert held["status"]["code"] == "held_for_specialist_review"
    hold = held["intake"]["hold"]
    assert (hold["action"], hold["reason"], hold["provisional"]) == (
        "escalate",
        "high_risk_factors",
        True,
    )
    assert hold["items"] == ["Pregnancy or maternity leave"]
    assert "isn't a finding about the employee" in hold["body"]
    assert "hasn't contacted anyone" in hold["body"]
    assert held["intake"]["next_stage_open"] is False
    assert held["answers"]["screening.pregnancy_maternity"] == "yes"
    assert next(p for p in held["progress"] if p["key"] == "next_stages")["status"] == "blocked"
    # Recorded: why the Case was held, with the inputs that caused it.
    last = stored_evaluations(sessions)[-1]
    assert (last.hold, last.hold_reason) == ("specialist_review", "high_risk_factors")
    stop = next(r for r in last.results if r["condition"] == "UAE-STOP-CALL-FIRST")
    assert (stop["outcome"], stop["action"]) == ("fired", "escalate")
    assert stop["inputs"]["screening.pregnancy_maternity"] == "yes"
    # Nothing else: no new table, no ticket, no message to anyone.
    assert set(inspect(sessions.kw["bind"]).get_table_names()) == tables_before
    assert not any("ticket" in t or "escalation" in t for t in tables_before)
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "Workflow case held" in logged
    assert "pregnan" not in logged.lower() and "high_risk" not in logged

    # Answers stay correctable; the hold lifts and the history keeps both.
    corrected = put(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        "safety_screening",
        {"screening.pregnancy_maternity": "no"},
        revision=4,
    ).json()
    assert corrected["status"]["code"] == "intake_recorded"
    kinds = [h["kind"] for h in corrected["history"]]
    assert kinds.index("hold_placed") < kinds.index("hold_lifted")


def test_an_uncertain_screening_answer_never_clears_the_screening(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = fed_case(client, sessions, seed, admin_alice)
    put(client, admin_alice, seed.company_a, case_id, "incident_context", CONTEXT, revision=2)

    body = put(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        "safety_screening",
        {**CLEAR, "screening.senior_employee": "not_sure"},
        revision=3,
    ).json()

    assert body["status"]["code"] == "screening_not_cleared"
    assert body["intake"]["screening"] == "not_cleared"
    assert body["intake"]["hold"] is None
    assert body["intake"]["next_stage_open"] is False
    assert body["uncertain"] == ["screening.senior_employee"]
    assert stored_evaluations(sessions)[-1].screening == "not_cleared"


def test_an_unanswered_screening_factor_never_clears_the_screening(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = fed_case(client, sessions, seed, admin_alice)
    put(client, admin_alice, seed.company_a, case_id, "incident_context", CONTEXT, revision=2)
    partial = {k: v for k, v in CLEAR.items() if k != "screening.criminal_allegation"}

    body = put(
        client, admin_alice, seed.company_a, case_id, "safety_screening", partial, revision=3
    ).json()

    assert body["intake"]["screening"] == "incomplete"
    assert body["status"]["code"] == "intake_in_progress"
    assert body["missing"] == ["screening.criminal_allegation"]
    assert body["intake"]["next_stage_open"] is False


def test_cautions_follow_the_answers_and_can_be_corrected(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = fed_case(client, sessions, seed, admin_alice)
    outside = {
        **CONTEXT,
        "context.location": "outside_work",
        "context.work_connection": "not_sure",
        "context.policy_awareness": "no",
        "history.same_incident_sanction": "yes",
    }
    body = put(
        client, admin_alice, seed.company_a, case_id, "incident_context", outside, revision=2
    ).json()
    cautions = {c["id"]: c for c in body["intake"]["cautions"]}
    assert list(cautions) == [
        "caution:policy_awareness",
        "caution:same_incident_sanction",
        "caution:off_duty_connection",
    ]
    assert cautions["caution:policy_awareness"]["provisional"] is True
    assert cautions["caution:off_duty_connection"]["provisional"] is False
    # A caution informs: it doesn't hold the Case.
    assert body["intake"]["hold"] is None

    corrected = put(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        "incident_context",
        {"context.location": "at_work", "context.policy_awareness": "yes"},
        revision=3,
    ).json()
    assert [c["id"] for c in corrected["intake"]["cautions"]] == ["caution:same_incident_sanction"]
    # The earlier connection answer is kept but no longer asked.
    assert corrected["answers"]["context.work_connection"] == "not_sure"
    assert "context.work_connection" not in corrected["asked"]
    titles = [h["title"] for h in corrected["history"] if h["kind"] == "caution"]
    assert "Caution no longer applies: Conduct outside work" in titles


def test_follow_ups_and_the_case_jurisdiction_are_validated_against_the_case(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = fed_case(client, sessions, seed, admin_alice)
    unasked = put(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        "incident_context",
        {"context.work_connection": "yes"},
        revision=2,
    )
    assert unasked.status_code == 422
    assert [e["loc"] for e in unasked.json()["detail"]] == [
        ["body", "answers", "context.work_connection"]
    ]
    other = put(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        "jurisdiction",
        {"jurisdiction.case_confirmation": "difc"},
        revision=2,
    )
    assert other.status_code == 422
    assert "difc" not in other.text
    assert count(sessions, WorkflowSubmission) == 2


# --- holds that come from the jurisdiction --------------------------------------------


def test_an_unconfirmed_company_jurisdiction_holds_jurisdiction_dependent_steps(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = create(client, admin_alice, seed.company_a).json()["id"]
    for step, answers in (
        ("jurisdiction", {"jurisdiction.case_confirmation": "uae_federal"}),
        ("safety_screening", CLEAR),
    ):
        assert (
            put(client, admin_alice, seed.company_a, case_id, step, answers, revision=0).json()
            == CONFLICT[1]
        )
    assert count(sessions, WorkflowSubmission) == 0
    # Jurisdiction-neutral facts can still be recorded.
    saved = put(
        client, admin_alice, seed.company_a, case_id, "incident_context", CONTEXT, revision=0
    )
    assert saved.status_code == 200
    assert saved.json()["status"]["code"] == "awaiting_jurisdiction"
    assert saved.json()["intake"]["cautions"] == []


@pytest.mark.parametrize(
    ("answer", "status", "hold", "reason"),
    [
        ("different", "held_for_specialist_review", "escalate", "jurisdiction_different"),
        ("not_sure", "awaiting_jurisdiction", "block", "case_jurisdiction_not_sure"),
    ],
)
def test_an_unresolved_case_jurisdiction_holds_the_intake(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    answer: str,
    status: str,
    hold: str,
    reason: str,
) -> None:
    confirm_jurisdiction(sessions, seed.company_a, "uae_federal")
    case_id = create(client, admin_alice, seed.company_a).json()["id"]
    body = put(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        "jurisdiction",
        {"jurisdiction.case_confirmation": answer},
        revision=0,
    ).json()
    assert body["status"]["code"] == status
    assert (body["intake"]["hold"]["action"], body["intake"]["hold"]["reason"]) == (hold, reason)
    assert {s["key"]: s["available"] for s in body["steps"]}["safety_screening"] is False
    screening = put(
        client, admin_alice, seed.company_a, case_id, "safety_screening", CLEAR, revision=1
    )
    assert screening.status_code == 409
    assert stored_evaluations(sessions)[-1].hold_reason == reason


def test_a_difc_case_gets_no_uae_federal_guidance_and_is_held(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    confirm_jurisdiction(sessions, seed.company_a, "difc")
    case_id = create(client, admin_alice, seed.company_a).json()["id"]
    put(client, admin_alice, seed.company_a, case_id, "initial_facts", INITIAL, revision=0)
    put(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        "jurisdiction",
        {"jurisdiction.case_confirmation": "difc"},
        revision=1,
    )
    # Facts that would raise every UAE Federal caution.
    body = put(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        "incident_context",
        {
            **CONTEXT,
            "context.location": "outside_work",
            "context.work_connection": "no",
            "context.policy_awareness": "no",
            "history.same_incident_sanction": "yes",
        },
        revision=2,
    ).json()

    assert body["intake"]["case_jurisdiction"]["jurisdiction"] == "difc"
    assert body["status"]["code"] == "held_for_specialist_review"
    assert body["intake"]["hold"]["reason"] == "screening_not_covered"
    assert body["intake"]["cautions"] == []
    assert body["intake"]["screening"] == "not_applicable"
    assert {s["key"]: s["available"] for s in body["steps"]}["safety_screening"] is False
    said = " ".join(
        f"{m.get('title', '')} {m.get('body', '')}"
        for m in body["conversation"]
        if m["kind"] != "answer_confirmation"
    )
    for federal in ("UAE Federal", "MOHRE", "Article"):
        assert federal not in said
    screening = put(
        client, admin_alice, seed.company_a, case_id, "safety_screening", CLEAR, revision=3
    )
    assert screening.status_code == 409
    last = stored_evaluations(sessions)[-1]
    assert {r["condition"]: r["reason"] for r in last.results} == {
        "JURISDICTION-ROUTING-001": "screening_not_covered",
        "POLICY-ACK-CASE": "other_jurisdiction",
        "UAE-ONE-PENALTY-SAME-INCIDENT": "other_jurisdiction",
        "UAE-OFFDUTY-CONNECTION": "other_jurisdiction",
        "UAE-STOP-CALL-FIRST": "other_jurisdiction",
    }


# --- compatibility, idempotency, access ------------------------------------------------


def test_an_m2_01_case_continues_into_the_intake(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    confirm_jurisdiction(sessions, seed.company_a, "uae_federal")
    # A Case created and answered by the M2-01 API (definition version 1).
    with sessions() as db:
        case = Case(
            company_id=seed.company_a, case_type="disciplinary", title="[SYNTHETIC] Earlier"
        )
        db.add(case)
        db.flush()
        instance = WorkflowInstance(
            company_id=seed.company_a,
            case_id=case.id,
            workflow_key="disciplinary",
            definition_version=1,
            revision=1,
            request_key=uuid.uuid4(),
            created_by_user_id=seed.alice,
        )
        db.add(instance)
        db.flush()
        submission = WorkflowSubmission(
            company_id=seed.company_a,
            instance_id=instance.id,
            step_key="initial_facts",
            revision=1,
            idempotency_key=uuid.uuid4(),
            submitted_by_user_id=seed.alice,
        )
        db.add(submission)
        db.flush()
        db.add_all(
            CaseFact(
                company_id=seed.company_a,
                instance_id=instance.id,
                submission_id=submission.id,
                fact_key=key,
                value=value,
            )
            for key, value in INITIAL.items()
        )
        db.commit()
        case_id, instance_id = str(case.id), instance.id

    opened = view(client, admin_alice, seed.company_a, case_id)
    assert opened["answers"] == INITIAL
    assert not any(key.startswith("incident.") for key in opened["missing"])
    assert [h["kind"] for h in opened["history"]] == ["case_created", "answers_saved"]
    saved = put(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        "jurisdiction",
        {"jurisdiction.case_confirmation": "uae_federal"},
        revision=1,
    )
    assert saved.status_code == 200
    with sessions() as db:
        stored = db.get(WorkflowInstance, instance_id)
        assert stored is not None and stored.definition_version == 1  # started with v1
    assert stored_evaluations(sessions)[-1].definition_version == 2  # evaluated with v2


def test_a_retried_save_records_one_evaluation(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = fed_case(client, sessions, seed, admin_alice)
    key = str(uuid.uuid4())
    first = put(
        client, admin_alice, seed.company_a, case_id, "safety_screening", CLEAR, revision=2, key=key
    )
    again = put(
        client, admin_alice, seed.company_a, case_id, "safety_screening", CLEAR, revision=2, key=key
    )
    assert first.status_code == again.status_code == 200
    assert again.json()["workflow"]["revision"] == 3
    assert count(sessions, WorkflowEvaluation) == 3
    # Nothing new to save: no submission, no evaluation.
    put(client, admin_alice, seed.company_a, case_id, "safety_screening", CLEAR, revision=3)
    assert (count(sessions, WorkflowSubmission), count(sessions, WorkflowEvaluation)) == (3, 3)


def test_members_cannot_answer_any_intake_step(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = fed_case(client, sessions, seed, admin_alice)
    # alice is demoted to an ordinary member of Company A.
    with sessions() as db:
        db.execute(
            update(Membership)
            .where(Membership.company_id == seed.company_a, Membership.user_id == seed.alice)
            .values(role="member")
        )
        db.commit()
    for step, answers in (
        ("jurisdiction", {"jurisdiction.case_confirmation": "uae_federal"}),
        ("incident_context", CONTEXT),
        ("safety_screening", CLEAR),
    ):
        response = put(client, admin_alice, seed.company_a, case_id, step, answers, revision=2)
        assert (response.status_code, response.json()) == FORBIDDEN
    denied = client.get(
        f"/companies/{seed.company_a}/cases/{case_id}/workflow", headers=admin_alice
    )
    assert (denied.status_code, denied.json()) == FORBIDDEN
    assert count(sessions, WorkflowEvaluation) == 2
