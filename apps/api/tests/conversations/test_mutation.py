"""The shared Case mutation pipeline: the form and Ask HeroOS change a Case the same way.

On SQLite stand-ins (the database-level guarantees are in tests/tenant_isolation).
The structured route's own behaviour is covered by tests/auth (unchanged by the
refactor); here: origins, provenance, refusals, corrections, and how an Ask
HeroOS update reads in the guided conversation and the Case history.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.models import AuthenticatedCompanyContext
from app.cases.mutation import (
    AssistantOrigin,
    FormOrigin,
    apply_case_fact_changes,
    evaluate_case,
)
from app.db.models import CaseFact, WorkflowEvaluation, WorkflowInstance, WorkflowSubmission
from app.repositories import workflows
from app.tenancy.scope import open_company_scope
from app.workflows.definition import DISCIPLINARY_V2
from app.workflows.progress import FactRecord, latest_answers
from tests.auth.test_workflow_api import (  # noqa: F401  (pytest fixtures)
    admin_alice,
    alice,
    client,
)
from tests.conversations.conftest import counts

QUESTION = "context.policy_awareness"


def new_case(db: sessionmaker[Session], context: AuthenticatedCompanyContext) -> uuid.UUID:
    with db() as session:
        scope = open_company_scope(session, context)
        item = workflows.create_workflow_case(
            scope,
            DISCIPLINARY_V2,
            title="[SYNTHETIC] Case",
            request_key=uuid.uuid4(),
            user_id=context.user_id,
        )
        scope.commit()
        return item.case.id


def apply(
    db: sessionmaker[Session],
    context: AuthenticatedCompanyContext,
    case_id: uuid.UUID,
    changes: dict[str, object],
    origin: FormOrigin | AssistantOrigin,
    *,
    expected: int | None = None,
) -> int | None:
    with db() as session:
        scope = open_company_scope(session, context)
        item = workflows.get_workflow_case(scope, case_id, for_update=True)
        assert item is not None
        state = evaluate_case(scope, item, "disabled", None)
        applied = apply_case_fact_changes(
            scope,
            item,
            state,
            origin=origin,
            changes=changes,
            expected_revision=item.instance.revision if expected is None else expected,
            idempotency_key=uuid.uuid4(),
            user_id=context.user_id,
            policy="disabled",
            bundle=None,
        )
        if applied is None:
            scope.rollback()
            return None
        scope.commit()
        return applied.revision


def stored(db: sessionmaker[Session], model: Any) -> list[Any]:
    with db() as session:
        found = list(session.scalars(select(model)).all())
        session.expunge_all()
        return found


def test_the_form_and_ask_heroos_write_through_the_same_pipeline(
    db: sessionmaker[Session], alice_context: AuthenticatedCompanyContext
) -> None:
    case_id = new_case(db, alice_context)
    message = uuid.uuid4()  # SQLite doesn't enforce the reference; PostgreSQL does
    assert (
        apply(db, alice_context, case_id, {"incident.history": "new"}, FormOrigin("initial_facts"))
        == 1
    )
    assert apply(db, alice_context, case_id, {QUESTION: "yes"}, AssistantOrigin(message)) == 2
    submissions = sorted(stored(db, WorkflowSubmission), key=lambda s: s.revision)
    assert [(s.origin, s.step_key, s.source_message_id) for s in submissions] == [
        ("structured", "initial_facts", None),
        ("assistant", "ask_heroos", message),
    ]
    # Both get the same side effects: the intake evaluation trace, the revision.
    assert {e.submission_id for e in stored(db, WorkflowEvaluation)} == {s.id for s in submissions}
    (instance,) = stored(db, WorkflowInstance)
    assert instance.revision == 2


def test_nothing_unchanged_or_empty_is_ever_stored(
    db: sessionmaker[Session], alice_context: AuthenticatedCompanyContext
) -> None:
    case_id = new_case(db, alice_context)
    apply(db, alice_context, case_id, {QUESTION: "yes"}, AssistantOrigin(uuid.uuid4()))
    before = counts(db)
    with pytest.raises(ValueError, match="repeat"):
        apply(db, alice_context, case_id, {QUESTION: "yes"}, AssistantOrigin(uuid.uuid4()))
    with pytest.raises(ValueError, match="no fact changes"):
        apply(db, alice_context, case_id, {}, FormOrigin("incident_context"))
    assert counts(db) == before


def test_a_stale_revision_writes_nothing(
    db: sessionmaker[Session], alice_context: AuthenticatedCompanyContext
) -> None:
    case_id = new_case(db, alice_context)
    before = counts(db)
    assert apply(db, alice_context, case_id, {QUESTION: "no"}, FormOrigin("x"), expected=7) is None
    assert counts(db) == before


def test_corrections_append_and_the_latest_wins(
    db: sessionmaker[Session], alice_context: AuthenticatedCompanyContext
) -> None:
    case_id = new_case(db, alice_context)
    apply(db, alice_context, case_id, {QUESTION: "yes"}, AssistantOrigin(uuid.uuid4()))
    apply(db, alice_context, case_id, {QUESTION: "no"}, AssistantOrigin(uuid.uuid4()))
    facts = stored(db, CaseFact)
    assert sorted(f.value for f in facts) == ["no", "yes"]  # the old fact stays
    with db() as session:
        found = session.execute(
            select(WorkflowSubmission.revision, CaseFact.fact_key, CaseFact.value).join(
                WorkflowSubmission, WorkflowSubmission.id == CaseFact.submission_id
            )
        ).all()
    assert latest_answers(FactRecord(r, k, v) for r, k, v in found) == {QUESTION: "no"}


def test_an_ask_heroos_update_never_reads_as_a_form_the_employer_filled_in(
    db: sessionmaker[Session],
    alice_context: AuthenticatedCompanyContext,
    client: TestClient,  # noqa: F811
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = new_case(db, alice_context)
    apply(db, alice_context, case_id, {QUESTION: "yes"}, AssistantOrigin(uuid.uuid4()))
    (submission,) = stored(db, WorkflowSubmission)
    view = client.get(
        f"/companies/{alice_context.company_id}/cases/{case_id}/workflow", headers=admin_alice
    ).json()
    kinds = {m["id"]: m for m in view["conversation"]}
    notice = kinds[f"assistant:{submission.id}"]
    assert (notice["kind"], notice["tone"], notice["title"]) == (
        "status_notice",
        "info",
        "Case information updated through Ask HeroOS",
    )
    # Labels only, never the value.
    assert notice["body"] == "Updated: Expected standard explained."
    assert f"submission:{submission.id}" not in kinds
    assert not any(m["kind"] == "answer_confirmation" for m in view["conversation"])
    (entry,) = [h for h in view["history"] if h["id"] == f"submission:{submission.id}"]
    assert entry["title"] == "Case information updated through Ask HeroOS"
    assert entry["detail"] == "Changed: Expected standard explained"
    assert view["answers"][QUESTION] == "yes"


def test_a_form_save_keeps_its_own_wording(
    db: sessionmaker[Session],
    alice_context: AuthenticatedCompanyContext,
    client: TestClient,  # noqa: F811
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = new_case(db, alice_context)
    saved = client.put(
        f"/companies/{alice_context.company_id}/cases/{case_id}/workflow/steps/initial_facts/answers",
        headers=admin_alice,
        json={
            "expected_revision": 0,
            "submission_key": str(uuid.uuid4()),
            "answers": {"incident.history": "new"},
        },
    ).json()
    (submission,) = stored(db, WorkflowSubmission)
    assert (submission.origin, submission.source_message_id) == ("structured", None)
    (entry,) = [h for h in saved["history"] if h["id"] == f"submission:{submission.id}"]
    assert entry["title"] == "Answers saved: Initial facts"
    assert any(
        m["kind"] == "answer_confirmation" and m["id"] == f"submission:{submission.id}"
        for m in saved["conversation"]
    )
