"""Workflow progression (M2-03) through the real application.

Same harness as test_intake_api.py: ``create_app`` with staging settings,
Cognito tokens verified by the production provider, in-memory SQLite built from
the real models (RLS, grants and real concurrency are proven on PostgreSQL in
tests/tenant_isolation/test_workflow_progression.py), and the fictional
synthetic rule bundle installed the way a deployment installs one (path and
pinned SHA-256).

Covers: M2-01 and M2-02 Cases still opening and the intake unchanged; the
employer's pathway choice (less serious, serious, undetermined) and changing
it; stage checklists through the answers route; transitions refused for
missing prerequisites, an intake hold, a disabled screening, a skipped stage
or a stage that isn't in progress (recorded, nothing moves); warnings that
must be acknowledged and never override a block; escalations recorded and
never released; idempotent retries, stale revisions and reused keys; members
and other Companies; DIFC and unconfirmed jurisdictions; no installed rules
(fail closed) and a bundle that fails its pin (startup refused); history after
refresh and a new sign-in; and that nothing decides a penalty.
"""

import json
import logging
import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import get_authentication_provider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.db.base import Base
from app.db.models import (
    CaseFact,
    Membership,
    WorkflowInstance,
    WorkflowProgressEvent,
    WorkflowSubmission,
)
from app.db.session import get_db
from app.main import create_app
from app.workflows.definition import SAFETY_SCREENING
from app.workflows.progression.bundle import RuleBundleError
from tests.auth.conftest import SeedData
from tests.auth.test_company_admin_api import make_admin
from tests.auth.test_company_api import staging_settings
from tests.auth.test_intake_api import (
    CLEAR,
    CONTEXT,
    INITIAL,
    confirm_jurisdiction,
    put,
    view,
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
from tests.fixtures import SYNTHETIC_BUNDLE, synthetic_bundle_pin

SYNTHETIC_TITLES = ("Test stage 1: Check-in conversation", "Test stage A: Written notice")


def progression_client(
    sessions: sessionmaker[Session],  # noqa: F811
    provider: CognitoAccessTokenProvider,
    *,
    screening: str = "synthetic_demo",
    rules: bool = True,
) -> TestClient:
    update_ = {"heroos_sensitive_screening": screening}
    if rules:
        update_ |= {
            "heroos_rule_bundle_path": SYNTHETIC_BUNDLE,
            "heroos_rule_bundle_sha256": synthetic_bundle_pin(),
        }
    app = create_app(staging_settings().model_copy(update=update_))

    def _db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_authentication_provider] = lambda: provider
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


@pytest.fixture
def client(
    sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
) -> TestClient:
    """Synthetic demo data only, with the synthetic test rules installed."""
    return progression_client(sessions, cognito_provider)


@pytest.fixture
def no_rules_client(
    sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
) -> TestClient:
    return progression_client(sessions, cognito_provider, rules=False)


@pytest.fixture
def disabled_client(
    sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
) -> TestClient:
    """Rules installed, but the sensitive screening is not enabled (the default)."""
    return progression_client(sessions, cognito_provider, screening="disabled")


def recorded_case(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    headers: dict[str, str],
    *,
    screening: dict[str, str] | None = None,
    initial: dict[str, str] | None = None,
) -> tuple[str, int]:
    """A UAE Federal Case through the whole intake: (case id, revision)."""
    confirm_jurisdiction(sessions, seed.company_a, "uae_federal")
    case_id: str = create(client, headers, seed.company_a).json()["id"]
    steps = [
        ("initial_facts", initial or INITIAL),
        ("jurisdiction", {"jurisdiction.case_confirmation": "uae_federal"}),
        ("incident_context", CONTEXT),
        ("safety_screening", screening or CLEAR),
    ]
    revision = 0
    for step, answers in steps:
        response = put(client, headers, seed.company_a, case_id, step, answers, revision=revision)
        assert response.status_code == 200, response.json()
        revision = response.json()["workflow"]["revision"]
    return case_id, revision


def pathway(
    client: TestClient,
    headers: dict[str, str],
    company: uuid.UUID,
    case_id: str,
    choice: str,
    *,
    revision: int,
    key: str | None = None,
    acknowledged: list[str] | None = None,
) -> Any:
    body: dict[str, Any] = {
        "expected_revision": revision,
        "request_key": key or str(uuid.uuid4()),
        "pathway": choice,
    }
    if acknowledged is not None:
        body["acknowledged_warnings"] = acknowledged
    return client.post(
        f"/companies/{company}/cases/{case_id}/workflow/progression/pathway",
        headers=headers,
        json=body,
    )


def transition(
    client: TestClient,
    headers: dict[str, str],
    company: uuid.UUID,
    case_id: str,
    key_: str,
    *,
    revision: int,
    key: str | None = None,
    acknowledged: list[str] | None = None,
) -> Any:
    body: dict[str, Any] = {
        "expected_revision": revision,
        "request_key": key or str(uuid.uuid4()),
        "transition": key_,
    }
    if acknowledged is not None:
        body["acknowledged_warnings"] = acknowledged
    return client.post(
        f"/companies/{company}/cases/{case_id}/workflow/progression/transitions",
        headers=headers,
        json=body,
    )


def events(sessions: sessionmaker[Session]) -> list[WorkflowProgressEvent]:  # noqa: F811
    with sessions() as db:
        return list(
            db.scalars(
                select(WorkflowProgressEvent).order_by(
                    WorkflowProgressEvent.occurred_at, WorkflowProgressEvent.revision
                )
            ).all()
        )


def count(sessions: sessionmaker[Session], model: type[Base]) -> int:  # noqa: F811
    with sessions() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


def action(body: Any, key: str) -> Any:
    return next(a for a in body["progression"]["actions"] if a["key"] == key)


def option(body: Any, key: str) -> Any:
    return next(o for o in body["progression"]["pathway_options"] if o["key"] == key)


def ok(response: Any) -> Any:
    assert response.status_code == 200, response.json()
    return response.json()


def into_stage(
    client: TestClient,
    headers: dict[str, str],
    company: uuid.UUID,
    case_id: str,
    revision: int,
    choice: str = "less_serious",
    stage: str = "test_check_in",
) -> Any:
    chosen = ok(pathway(client, headers, company, case_id, choice, revision=revision))
    return ok(
        transition(
            client,
            headers,
            company,
            case_id,
            f"start:{stage}",
            revision=chosen["workflow"]["revision"],
        )
    )


def checklist(
    client: TestClient,
    headers: dict[str, str],
    company: uuid.UUID,
    case_id: str,
    stage: str,
    answers: dict[str, object],
    *,
    revision: int,
) -> Any:
    return put(client, headers, company, case_id, stage, answers, revision=revision)


def complete_stage(
    client: TestClient,
    headers: dict[str, str],
    company: uuid.UUID,
    case_id: str,
    stage: str,
    answers: dict[str, object],
    body: Any,
    acknowledged: list[str] | None = None,
) -> Any:
    saved = ok(
        checklist(
            client,
            headers,
            company,
            case_id,
            stage,
            answers,
            revision=body["workflow"]["revision"],
        )
    )
    return ok(
        transition(
            client,
            headers,
            company,
            case_id,
            f"complete:{stage}",
            revision=saved["workflow"]["revision"],
            acknowledged=acknowledged,
        )
    )


# --- earlier milestones keep working ---------------------------------------------------


def test_an_m2_01_case_still_opens_with_the_rules_installed(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = create(client, admin_alice, seed.company_a).json()["id"]
    with sessions() as db:
        db.execute(update(WorkflowInstance).values(definition_version=1))
        db.commit()
    body = view(client, admin_alice, seed.company_a, case_id)
    assert body["workflow"]["definition_version"] == 2
    progression = body["progression"]
    assert progression["status"]["code"] == "paused"
    assert progression["gate"]["code"] == "jurisdiction_paused"
    assert progression["rules"]["provenance"] == "synthetic"
    assert progression["rules"]["notice"]["title"] == "Synthetic test rules"


def test_the_intake_is_unchanged_without_rules(
    no_rules_client: TestClient,
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, _ = recorded_case(no_rules_client, sessions, seed, admin_alice)
    without = view(no_rules_client, admin_alice, seed.company_a, case_id)
    assert without["status"]["code"] == "intake_recorded"
    assert without["intake"]["next_stage_open"] is True
    assert without["not_available"] == [
        "Classification of the incident",
        "Options and decisions",
        "Issuing documents",
        "Expert review",
    ]
    assert without["progress"][-1]["key"] == "next_stages"
    assert without["conversation"][-1]["title"] == "What happens next"
    progression = without["progression"]
    assert progression["status"]["code"] == "unavailable"
    assert progression["gate"]["code"] == "rules_unavailable"
    assert (progression["rules"], progression["pathway_options"], progression["actions"]) == (
        None,
        [],
        [],
    )
    # The intake part of the view is identical with the rules installed.
    with_rules = view(client, admin_alice, seed.company_a, case_id)
    for key in ("status", "intake", "steps", "answers", "asked", "missing", "history"):
        assert with_rules[key] == without[key], key


# --- no rules: fail closed -------------------------------------------------------------


def test_without_rules_progression_is_refused_and_nothing_is_recorded(
    no_rules_client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(no_rules_client, sessions, seed, admin_alice)
    chosen = pathway(
        no_rules_client, admin_alice, seed.company_a, case_id, "less_serious", revision=revision
    )
    assert (chosen.status_code, chosen.json()) == CONFLICT
    started = transition(
        no_rules_client, admin_alice, seed.company_a, case_id, "start:test_check_in",
        revision=revision,
    )  # fmt: skip
    assert (started.status_code, started.json()) == CONFLICT
    answered = put(
        no_rules_client,
        admin_alice,
        seed.company_a,
        case_id,
        "test_check_in",
        {"progress.test_check_in.conversation_held": "yes"},
        revision=revision,
    )
    assert (answered.status_code, answered.json()) == NOT_FOUND
    assert count(sessions, WorkflowProgressEvent) == 0


def test_a_bundle_that_fails_its_pin_stops_startup(tmp_path: Any) -> None:
    changed = tmp_path / "bundle.json"
    data = json.loads(SYNTHETIC_BUNDLE.read_bytes())
    data["version"] = "synthetic.9"
    changed.write_text(json.dumps(data))
    settings = staging_settings().model_copy(
        update={
            "heroos_rule_bundle_path": changed,
            "heroos_rule_bundle_sha256": synthetic_bundle_pin(),
        }
    )
    with pytest.raises(RuleBundleError) as refused:
        create_app(settings)
    assert refused.value.code == "checksum_mismatch"


# --- the employer's pathway choice -----------------------------------------------------


def test_an_administrator_records_a_less_serious_pathway(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    before = view(client, admin_alice, seed.company_a, case_id)
    progression = before["progression"]
    assert progression["status"]["code"] == "awaiting_pathway"
    assert progression["gate"] is None
    assert progression["pathway"] is None
    assert [o["key"] for o in progression["pathway_options"]] == [
        "less_serious",
        "serious",
        "undetermined",
    ]
    assert all(o["transition"]["allowed"] for o in progression["pathway_options"])
    assert progression["actions"] == []

    body = ok(
        pathway(client, admin_alice, seed.company_a, case_id, "less_serious", revision=revision)
    )
    assert body["workflow"]["revision"] == revision + 1
    progression = body["progression"]
    assert progression["attempt"]["outcome"] == "applied"
    assert progression["pathway"]["key"] == "less_serious"
    assert progression["pathway"]["by_viewer"] is True
    assert progression["status"]["code"] == "ready"
    assert [a["key"] for a in progression["actions"]] == ["start:test_check_in"]
    assert [(s["key"], s["status"]) for s in progression["stages"]] == [
        ("test_check_in", "next"),
        ("test_written_note", "later"),
        ("test_final_review", "later"),
    ]
    assert option(body, "less_serious")["current"] is True
    assert progression["history"][-1]["title"] == "Pathway recorded: Less serious (your decision)"
    assert "didn't classify" in progression["history"][-1]["detail"]
    [event] = events(sessions)
    assert (event.kind, event.pathway, event.previous_pathway, event.decision) == (
        "pathway_selected",
        "less_serious",
        None,
        "allow",
    )
    assert (event.bundle_version, event.intake_status, event.revision) == (
        "synthetic.1",
        "intake_recorded",
        revision + 1,
    )
    assert body["progress"][-3:] == [
        {
            "key": "pathway",
            "label": "Pathway",
            "status": "completed",
            "detail": "Less serious (your decision)",
        },
        {
            "key": "stage",
            "label": "Stages",
            "status": "needs_information",
            "detail": "Next: Test stage 1: Check-in conversation",
        },
        {
            "key": "later",
            "label": "Not available yet",
            "status": "coming_later",
            "detail": "Penalty and outcome decisions, Issuing documents, Expert review",
        },
    ]


def test_an_administrator_records_a_serious_pathway(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    body = ok(pathway(client, admin_alice, seed.company_a, case_id, "serious", revision=revision))
    assert body["progression"]["pathway"]["label"] == "Serious misconduct"
    assert [a["key"] for a in body["progression"]["actions"]] == ["start:test_notice"]


def test_an_undetermined_choice_unlocks_nothing(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    body = ok(
        pathway(client, admin_alice, seed.company_a, case_id, "undetermined", revision=revision)
    )
    progression = body["progression"]
    assert progression["status"]["code"] == "undetermined"
    assert (progression["actions"], progression["stages"], progression["checklist"]) == (
        [],
        [],
        None,
    )
    refused = ok(
        transition(
            client, admin_alice, seed.company_a, case_id, "start:test_check_in",
            revision=body["workflow"]["revision"],
        )
    )  # fmt: skip
    assert refused["progression"]["attempt"]["outcome"] == "rejected"
    assert refused["workflow"]["revision"] == body["workflow"]["revision"]
    assert events(sessions)[-1].kind == "transition_rejected"


def test_changing_the_pathway_keeps_every_earlier_record(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    body = into_stage(client, admin_alice, seed.company_a, case_id, revision)
    body = complete_stage(
        client, admin_alice, seed.company_a, case_id, "test_check_in",
        {"progress.test_check_in.conversation_held": "yes",
         "progress.test_check_in.employee_heard": "yes"},
        body,
    )  # fmt: skip
    changed = ok(
        pathway(
            client, admin_alice, seed.company_a, case_id, "serious",
            revision=body["workflow"]["revision"],
        )
    )  # fmt: skip
    progression = changed["progression"]
    assert progression["pathway"]["previous"] == "Less serious"
    assert [a["key"] for a in progression["actions"]] == ["start:test_notice"]
    titles = [h["title"] for h in progression["history"]]
    assert titles == [
        "Pathway recorded: Less serious (your decision)",
        "Stage started: Test stage 1: Check-in conversation",
        "Stage completed: Test stage 1: Check-in conversation",
        "Pathway recorded: Serious misconduct (your decision)",
    ]
    assert "Changed from: Less serious" in progression["history"][-1]["detail"]
    # The checklist answers and their history are still there.
    assert changed["answers"]["progress.test_check_in.conversation_held"] == "yes"
    saved = [h["title"] for h in changed["history"] if h["kind"] == "answers_saved"]
    assert saved[-1] == "Answers saved: Test stage 1: Check-in conversation"
    # Back to less serious: the completed stage still counts.
    back = ok(
        pathway(
            client, admin_alice, seed.company_a, case_id, "less_serious",
            revision=changed["workflow"]["revision"],
        )
    )  # fmt: skip
    assert [a["key"] for a in back["progression"]["actions"]] == ["start:test_written_note"]
    assert [e.kind for e in events(sessions)].count("pathway_selected") == 3


def test_a_pathway_caution_must_be_acknowledged_exactly(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(
        client,
        sessions,
        seed,
        admin_alice,
        initial={**INITIAL, "incident.history": "raised_before"},
    )
    # raised_before asks one more context question.
    body = ok(
        put(client, admin_alice, seed.company_a, case_id, "incident_context",
            {"history.documented_action": "yes"}, revision=revision)
    )  # fmt: skip
    revision = body["workflow"]["revision"]
    less = option(body, "less_serious")["transition"]
    assert (less["decision"], less["allowed"], less["acknowledge"]) == (
        "warn",
        True,
        ["test_select_history_caution"],
    )
    assert less["warnings"][0]["title"] == "Test caution: the issue was raised before"
    for wrong in (None, [], ["test_other"], ["test_select_history_caution", "test_other"]):
        response = pathway(
            client, admin_alice, seed.company_a, case_id, "less_serious", revision=revision,
            acknowledged=wrong,
        )  # fmt: skip
        assert (response.status_code, response.json()) == CONFLICT, wrong
    assert count(sessions, WorkflowProgressEvent) == 0
    applied = ok(
        pathway(
            client, admin_alice, seed.company_a, case_id, "less_serious", revision=revision,
            acknowledged=["test_select_history_caution"],
        )
    )  # fmt: skip
    assert applied["progression"]["attempt"]["decision"] == "warn"
    [event] = events(sessions)
    assert (event.decision, event.acknowledged) == ("warn", ["test_select_history_caution"])


# --- prerequisites, holds, skips -------------------------------------------------------


def test_a_missing_prerequisite_blocks_and_nothing_moves(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    body = into_stage(client, admin_alice, seed.company_a, case_id, revision)
    progression = body["progression"]
    assert progression["status"]["code"] == "in_stage"
    assert progression["checklist"]["step_key"] == "test_check_in"
    complete = action(body, "complete:test_check_in")
    assert (complete["allowed"], complete["decision"]) == (False, "block")
    assert complete["reasons"][0]["code"] == "checklist_incomplete"
    assert complete["missing"] == ["Test check-in held", "Employee's view heard (test)"]

    refused = ok(
        transition(
            client, admin_alice, seed.company_a, case_id, "complete:test_check_in",
            revision=body["workflow"]["revision"],
        )
    )  # fmt: skip
    assert refused["progression"]["attempt"]["outcome"] == "rejected"
    assert refused["workflow"]["revision"] == body["workflow"]["revision"]
    assert refused["progression"]["status"]["code"] == "in_stage"
    rejected = events(sessions)[-1]
    assert (rejected.kind, rejected.decision, rejected.revision) == (
        "transition_rejected",
        "block",
        body["workflow"]["revision"],
    )
    fired = [r["rule"] for r in rejected.reasons if r["fired"]]
    assert fired == ["checklist_incomplete", "test_check_in_confirmed"]
    assert refused["progression"]["history"][-1]["title"].startswith("Not allowed: Mark complete")

    # "No" doesn't meet the requirement either.
    saved = ok(
        checklist(
            client, admin_alice, seed.company_a, case_id, "test_check_in",
            {"progress.test_check_in.conversation_held": "yes",
             "progress.test_check_in.employee_heard": "no"},
            revision=body["workflow"]["revision"],
        )
    )  # fmt: skip
    blocked = action(saved, "complete:test_check_in")
    assert [r["code"] for r in blocked["reasons"]] == ["test_check_in_confirmed"]
    assert blocked["reasons"][0]["provisional"] is True


def test_an_intake_hold_blocks_every_transition(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    body = into_stage(client, admin_alice, seed.company_a, case_id, revision)
    held = ok(
        put(
            client, admin_alice, seed.company_a, case_id, "safety_screening",
            {**CLEAR, "screening.sick_leave": "yes"}, revision=body["workflow"]["revision"],
        )
    )  # fmt: skip
    assert held["status"]["code"] == "held_for_specialist_review"
    progression = held["progression"]
    assert (progression["status"]["code"], progression["gate"]["code"]) == ("held", "case_held")
    assert progression["checklist"] is None
    assert all(not a["allowed"] for a in progression["actions"])
    assert all([r["code"] for r in a["reasons"]] == ["case_held"] for a in progression["actions"])
    # No bundle guidance is shown while held.
    assert all(a["warnings"] == [] for a in progression["actions"])
    refused = ok(
        transition(
            client, admin_alice, seed.company_a, case_id, "complete:test_check_in",
            revision=held["workflow"]["revision"],
        )
    )  # fmt: skip
    assert refused["progression"]["attempt"]["decision"] == "escalate"
    # Checklists can't be answered while held.
    answered = checklist(
        client, admin_alice, seed.company_a, case_id, "test_check_in",
        {"progress.test_check_in.conversation_held": "yes"},
        revision=held["workflow"]["revision"],
    )  # fmt: skip
    assert (answered.status_code, answered.json()) == CONFLICT
    # Correcting the screening answer doesn't release the hold.
    corrected = ok(
        put(
            client, admin_alice, seed.company_a, case_id, "safety_screening", CLEAR,
            revision=held["workflow"]["revision"],
        )
    )  # fmt: skip
    assert corrected["progression"]["gate"]["code"] == "case_held"
    # The intake hold is the record: no progression escalation, no ticket.
    assert [e.kind for e in events(sessions)] == [
        "pathway_selected",
        "stage_started",
        "transition_rejected",
    ]


def test_a_disabled_screening_never_counts_as_cleared(
    disabled_client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    confirm_jurisdiction(sessions, seed.company_a, "uae_federal")
    case_id = create(disabled_client, admin_alice, seed.company_a).json()["id"]
    revision = 0
    for step, answers in (
        ("initial_facts", INITIAL),
        ("jurisdiction", {"jurisdiction.case_confirmation": "uae_federal"}),
        ("incident_context", CONTEXT),
    ):
        revision = ok(
            put(disabled_client, admin_alice, seed.company_a, case_id, step, answers,
                revision=revision)
        )["workflow"]["revision"]  # fmt: skip
    body = view(disabled_client, admin_alice, seed.company_a, case_id)
    assert body["status"]["code"] == "screening_unavailable"
    assert body["missing"] == []
    progression = body["progression"]
    assert progression["gate"]["code"] == "intake_incomplete"
    assert all(not o["transition"]["allowed"] for o in progression["pathway_options"])
    refused = ok(
        pathway(disabled_client, admin_alice, seed.company_a, case_id, "less_serious",
                revision=revision)
    )  # fmt: skip
    assert refused["progression"]["attempt"]["outcome"] == "rejected"
    assert refused["progression"]["pathway"] is None


def test_skipping_ahead_is_refused_and_recorded(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    body = ok(
        pathway(client, admin_alice, seed.company_a, case_id, "less_serious", revision=revision)
    )
    revision = body["workflow"]["revision"]
    for skip in ("start:test_final_review", "start:test_written_note", "start:test_notice",
                 "complete:test_check_in"):  # fmt: skip
        refused = ok(
            transition(client, admin_alice, seed.company_a, case_id, skip, revision=revision)
        )
        assert refused["progression"]["attempt"]["outcome"] == "rejected", skip
        assert refused["workflow"]["revision"] == revision
    assert [e.kind for e in events(sessions)][1:] == ["transition_rejected"] * 4
    assert sorted(r["rule"] for e in events(sessions)[1:] for r in e.reasons) == [
        "stage_not_active",
        "stage_not_available",
        "stage_not_available",
        "stage_not_available",
    ]
    # Unknown or malformed transitions name nothing: 404 / 422, nothing recorded.
    unknown = transition(client, admin_alice, seed.company_a, case_id, "start:dismissal",
                         revision=revision)  # fmt: skip
    assert (unknown.status_code, unknown.json()) == NOT_FOUND
    for bad in ("pathway:serious", "approve:test_check_in", "start:Test", "start:"):
        response = transition(client, admin_alice, seed.company_a, case_id, bad, revision=revision)
        assert response.status_code == 422, bad
    for bad_pathway in ("dismissal", "Less", ""):
        response = pathway(client, admin_alice, seed.company_a, case_id, bad_pathway,
                           revision=revision)  # fmt: skip
        assert response.status_code in (404, 422), bad_pathway
    assert count(sessions, WorkflowProgressEvent) == 5


# --- warnings, escalations -------------------------------------------------------------


def test_a_warning_never_overrides_a_block(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(
        client, sessions, seed, admin_alice,
        initial={**INITIAL, "incident.evidence_available": "no"},
    )  # fmt: skip
    body = into_stage(client, admin_alice, seed.company_a, case_id, revision)
    body = complete_stage(
        client, admin_alice, seed.company_a, case_id, "test_check_in",
        {"progress.test_check_in.conversation_held": "yes",
         "progress.test_check_in.employee_heard": "yes"},
        body,
    )  # fmt: skip
    body = ok(
        transition(client, admin_alice, seed.company_a, case_id, "start:test_written_note",
                   revision=body["workflow"]["revision"])
    )  # fmt: skip
    saved = ok(
        checklist(client, admin_alice, seed.company_a, case_id, "test_written_note",
                  {"progress.test_written_note.note_shared": "no"},
                  revision=body["workflow"]["revision"])
    )  # fmt: skip
    blocked = action(saved, "complete:test_written_note")
    assert (blocked["decision"], blocked["allowed"], blocked["acknowledge"]) == ("block", False, [])
    assert [w["code"] for w in blocked["warnings"]] == ["test_note_evidence_caution"]
    # Acknowledging the warning doesn't get past the block.
    refused = ok(
        transition(client, admin_alice, seed.company_a, case_id, "complete:test_written_note",
                   revision=saved["workflow"]["revision"],
                   acknowledged=["test_note_evidence_caution"])
    )  # fmt: skip
    assert refused["progression"]["attempt"]["outcome"] == "rejected"
    assert refused["progression"]["status"]["code"] == "in_stage"
    shared = ok(
        checklist(client, admin_alice, seed.company_a, case_id, "test_written_note",
                  {"progress.test_written_note.note_shared": "yes"},
                  revision=saved["workflow"]["revision"])
    )  # fmt: skip
    warned = action(shared, "complete:test_written_note")
    assert (warned["decision"], warned["allowed"], warned["acknowledge"]) == (
        "warn",
        True,
        ["test_note_evidence_caution"],
    )
    done = ok(
        transition(client, admin_alice, seed.company_a, case_id, "complete:test_written_note",
                   revision=shared["workflow"]["revision"],
                   acknowledged=["test_note_evidence_caution"])
    )  # fmt: skip
    assert done["progression"]["history"][-1]["detail"] == "1 caution acknowledged."


def _to_final_review(
    client: TestClient, headers: dict[str, str], company: uuid.UUID, case_id: str, revision: int
) -> Any:
    body = into_stage(client, headers, company, case_id, revision)
    body = complete_stage(
        client, headers, company, case_id, "test_check_in",
        {"progress.test_check_in.conversation_held": "yes",
         "progress.test_check_in.employee_heard": "yes"},
        body,
    )  # fmt: skip
    body = ok(
        transition(client, headers, company, case_id, "start:test_written_note",
                   revision=body["workflow"]["revision"])
    )  # fmt: skip
    body = complete_stage(
        client, headers, company, case_id, "test_written_note",
        {"progress.test_written_note.note_shared": "yes"}, body,
    )  # fmt: skip
    return ok(
        transition(client, headers, company, case_id, "start:test_final_review",
                   revision=body["workflow"]["revision"])
    )  # fmt: skip


def test_an_escalation_is_recorded_and_cannot_be_bypassed(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    body = _to_final_review(client, admin_alice, seed.company_a, case_id, revision)
    escalated = ok(
        checklist(client, admin_alice, seed.company_a, case_id, "test_final_review",
                  {"progress.test_final_review.review_done": "yes",
                   "progress.test_final_review.outside_help_needed": "yes"},
                  revision=body["workflow"]["revision"])
    )  # fmt: skip
    # Recorded when the answers were saved, before anyone asked to complete.
    recorded = [e for e in events(sessions) if e.kind == "escalation_recorded"]
    assert len(recorded) == 1
    assert (recorded[0].transition, recorded[0].request_key) == (
        "complete:test_final_review",
        None,
    )
    assert recorded[0].submission_id is not None
    progression = escalated["progression"]
    assert [e["transition"] for e in progression["escalations"]] == ["complete:test_final_review"]
    complete = action(escalated, "complete:test_final_review")
    assert (complete["decision"], complete["allowed"]) == ("escalate", False)
    assert [r["code"] for r in complete["reasons"]] == ["earlier_escalation", "test_outside_help"]
    assert complete["reasons"][1]["title"] == "Test escalation: specialist review needed"

    # Changing the answer doesn't release it; neither do acknowledgments.
    changed = ok(
        checklist(client, admin_alice, seed.company_a, case_id, "test_final_review",
                  {"progress.test_final_review.outside_help_needed": "no"},
                  revision=escalated["workflow"]["revision"])
    )  # fmt: skip
    still = action(changed, "complete:test_final_review")
    assert still["decision"] == "escalate"
    assert [r["code"] for r in still["reasons"]] == ["earlier_escalation"]
    refused = ok(
        transition(client, admin_alice, seed.company_a, case_id, "complete:test_final_review",
                   revision=changed["workflow"]["revision"],
                   acknowledged=["earlier_escalation"])
    )  # fmt: skip
    assert refused["progression"]["attempt"]["decision"] == "escalate"
    assert refused["progression"]["status"]["code"] == "in_stage"
    assert [e.kind for e in events(sessions)].count("escalation_recorded") == 1
    # Nothing else is created: no expert ticket, no clearance.
    assert refused["progression"]["attempt"]["body"].endswith("recorded in the case history.")


# --- idempotency and concurrency -------------------------------------------------------


def test_a_retried_transition_is_applied_once(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    key = str(uuid.uuid4())
    first = ok(pathway(client, admin_alice, seed.company_a, case_id, "less_serious",
                       revision=revision, key=key))  # fmt: skip
    again = ok(pathway(client, admin_alice, seed.company_a, case_id, "less_serious",
                       revision=revision, key=key))  # fmt: skip
    assert again["workflow"]["revision"] == first["workflow"]["revision"]
    assert again["progression"]["attempt"] == first["progression"]["attempt"]
    assert count(sessions, WorkflowProgressEvent) == 1
    # The same key for another transition is a conflict, not a replay.
    reused = pathway(client, admin_alice, seed.company_a, case_id, "serious",
                     revision=first["workflow"]["revision"], key=key)  # fmt: skip
    assert (reused.status_code, reused.json()) == CONFLICT
    # A refused request replays its refusal too.
    skip_key = str(uuid.uuid4())
    for _ in range(2):
        refused = ok(
            transition(client, admin_alice, seed.company_a, case_id, "start:test_final_review",
                       revision=first["workflow"]["revision"], key=skip_key)
        )  # fmt: skip
        assert refused["progression"]["attempt"]["outcome"] == "rejected"
    assert count(sessions, WorkflowProgressEvent) == 2


def test_a_stale_revision_is_a_conflict(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    ok(pathway(client, admin_alice, seed.company_a, case_id, "less_serious", revision=revision))
    stale = transition(client, admin_alice, seed.company_a, case_id, "start:test_check_in",
                       revision=revision)  # fmt: skip
    assert (stale.status_code, stale.json()) == CONFLICT
    stale_pathway = pathway(client, admin_alice, seed.company_a, case_id, "serious",
                            revision=revision)  # fmt: skip
    assert (stale_pathway.status_code, stale_pathway.json()) == CONFLICT
    assert count(sessions, WorkflowProgressEvent) == 1


# --- access ----------------------------------------------------------------------------


def test_members_cannot_read_or_change_progression(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    with sessions() as db:
        db.execute(update(Membership).values(role="member"))
        db.commit()
    reads = client.get(f"/companies/{seed.company_a}/cases/{case_id}/workflow", headers=admin_alice)
    assert (reads.status_code, reads.json()) == FORBIDDEN
    for response in (
        pathway(client, admin_alice, seed.company_a, case_id, "less_serious", revision=revision),
        transition(client, admin_alice, seed.company_a, case_id, "start:test_check_in",
                   revision=revision),
    ):  # fmt: skip
        assert (response.status_code, response.json()) == FORBIDDEN
    assert count(sessions, WorkflowProgressEvent) == 0


def test_another_company_cannot_read_or_change_progression(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    bob: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    make_admin(sessions, seed.company_b, seed.bob)
    # Bob through Company B's routes: A's Case is not found (like a random id).
    for case in (case_id, str(uuid.uuid4())):
        for response in (
            client.get(f"/companies/{seed.company_b}/cases/{case}/workflow", headers=bob),
            pathway(client, bob, seed.company_b, case, "less_serious", revision=revision),
            transition(client, bob, seed.company_b, case, "start:test_check_in",
                       revision=revision),
        ):  # fmt: skip
            assert (response.status_code, response.json()) == NOT_FOUND
    # Bob through Company A's routes: forbidden.
    response = pathway(client, bob, seed.company_a, case_id, "less_serious", revision=revision)
    assert (response.status_code, response.json()) == FORBIDDEN
    assert count(sessions, WorkflowProgressEvent) == 0


# --- jurisdictions ---------------------------------------------------------------------


def test_a_difc_case_gets_no_federal_rules(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    confirm_jurisdiction(sessions, seed.company_a, "difc")
    case_id = create(client, admin_alice, seed.company_a).json()["id"]
    ok(put(client, admin_alice, seed.company_a, case_id, "initial_facts", INITIAL, revision=0))
    body = ok(
        put(client, admin_alice, seed.company_a, case_id, "jurisdiction",
            {"jurisdiction.case_confirmation": "difc"}, revision=1)
    )  # fmt: skip
    # The intake holds a DIFC Case (no approved screening): progression with it.
    progression = body["progression"]
    assert (progression["status"]["code"], progression["gate"]["code"]) == ("held", "case_held")
    text = json.dumps(body)
    for title in SYNTHETIC_TITLES:
        assert title not in text
    assert "test_check_in" not in text
    refused = ok(pathway(client, admin_alice, seed.company_a, case_id, "less_serious", revision=2))
    assert refused["progression"]["attempt"]["decision"] == "escalate"
    assert refused["progression"]["pathway"] is None


def test_an_unconfirmed_jurisdiction_fails_safely(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = create(client, admin_alice, seed.company_a).json()["id"]
    ok(put(client, admin_alice, seed.company_a, case_id, "initial_facts", INITIAL, revision=0))
    body = view(client, admin_alice, seed.company_a, case_id)
    assert body["progression"]["gate"]["code"] == "jurisdiction_paused"
    refused = ok(pathway(client, admin_alice, seed.company_a, case_id, "serious", revision=1))
    assert refused["progression"]["attempt"]["outcome"] == "rejected"
    assert [r["rule"] for r in events(sessions)[0].reasons] == ["jurisdiction_paused"]


# --- persistence, history, no decisions ------------------------------------------------


def test_stage_and_history_survive_a_refresh_and_a_new_sign_in(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    make_cognito_token: Any,
) -> None:
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    body = into_stage(client, admin_alice, seed.company_a, case_id, revision)
    ok(
        checklist(client, admin_alice, seed.company_a, case_id, "test_check_in",
                  {"progress.test_check_in.conversation_held": "yes"},
                  revision=body["workflow"]["revision"])
    )  # fmt: skip
    first = view(client, admin_alice, seed.company_a, case_id)
    # A new application instance and a new token: the same state, from the database.
    fresh = progression_client(sessions, cognito_provider)
    signed_in = {"Authorization": f"Bearer {make_cognito_token('alice-subject')}"}
    again = view(fresh, signed_in, seed.company_a, case_id)
    assert again["progression"] == first["progression"]
    assert again["progression"]["status"]["code"] == "in_stage"
    assert again["answers"]["progress.test_check_in.conversation_held"] == "yes"


def test_checklist_answers_are_corrected_without_erasing_history(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    body = into_stage(client, admin_alice, seed.company_a, case_id, revision)
    first = ok(
        checklist(client, admin_alice, seed.company_a, case_id, "test_check_in",
                  {"progress.test_check_in.conversation_held": "no"},
                  revision=body["workflow"]["revision"])
    )  # fmt: skip
    ok(
        checklist(client, admin_alice, seed.company_a, case_id, "test_check_in",
                  {"progress.test_check_in.conversation_held": "yes"},
                  revision=first["workflow"]["revision"])
    )  # fmt: skip
    with sessions() as db:
        values = db.scalars(
            select(CaseFact.value).where(
                CaseFact.fact_key == "progress.test_check_in.conversation_held"
            )
        ).all()
    assert sorted(values) == ["no", "yes"]
    # Only the stage in progress takes checklist answers; other stages are refused.
    current = first["workflow"]["revision"] + 1
    other = checklist(
        client, admin_alice, seed.company_a, case_id, "test_written_note",
        {"progress.test_written_note.note_shared": "yes"}, revision=current,
    )  # fmt: skip
    assert (other.status_code, other.json()) == CONFLICT
    wrong_key = checklist(
        client, admin_alice, seed.company_a, case_id, "test_check_in",
        {"progress.test_written_note.note_shared": "yes"}, revision=current,
    )  # fmt: skip
    assert wrong_key.status_code == 422
    assert count(sessions, WorkflowSubmission) == 6


def test_nothing_decides_a_penalty_or_ends_employment(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    case_id, revision = recorded_case(client, sessions, seed, admin_alice)
    body = _to_final_review(client, admin_alice, seed.company_a, case_id, revision)
    done = complete_stage(
        client, admin_alice, seed.company_a, case_id, "test_final_review",
        {"progress.test_final_review.review_done": "yes",
         "progress.test_final_review.outside_help_needed": "no"},
        body,
    )  # fmt: skip
    progression = done["progression"]
    assert (progression["status"]["code"], progression["gate"]["code"]) == (
        "closed",
        "workflow_closed",
    )
    assert progression["actions"] == []
    assert all(not o["transition"] or not o["transition"]["allowed"]
               for o in progression["pathway_options"])  # fmt: skip
    assert "Penalty and outcome decisions" in done["not_available"]
    # Progression carries no outcome, penalty or termination field or wording
    # (the intake's own screening question about dismissal is M2-02 wording).
    text = json.dumps(done["progression"]).lower()
    for word in ("dismiss", "terminat", "sanction", "penalty imposed", "approved by heroos"):
        assert word not in text, word
    # Logs carry event kinds and decisions only: no stage, rule or answer.
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "test_" not in logged
    assert "Test stage" not in logged
    assert "Workflow progression stage_completed" in logged
    assert {q.key for q in SAFETY_SCREENING.questions}.isdisjoint(logged.split())
