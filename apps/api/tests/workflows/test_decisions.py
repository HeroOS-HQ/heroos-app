"""Decision records and the unified timeline (M2-04): pure domain checks.

The validators (fixed messages, never the value), correction chains (versions,
the current version, no branch), and the timeline's causal, total order and
cursor paging, including entries that share a timestamp and timestamps that
run against the revision order (a transaction that started first but
committed second).
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.db.models.workflow import DECISION_CATEGORIES
from app.workflows import decisions
from app.workflows.decisions import (
    CATEGORIES,
    DecisionRecord,
    EvidenceReference,
    chain_positions,
    same_request,
)
from app.workflows.history import HistoryItem
from app.workflows.progression.presentation import ProgressHistoryItem
from app.workflows.progression.records import StoredEvent
from app.workflows.timeline import compose_timeline, timeline_page

T0 = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
VIEWER = uuid.uuid4()
OTHER = uuid.uuid4()
CASE = uuid.uuid4()


def make_record(
    revision: int,
    *,
    supersedes: DecisionRecord | None = None,
    relation: decisions.Relation = "original",
    at: datetime = T0,
    by: uuid.UUID = VIEWER,
) -> DecisionRecord:
    record_id = uuid.uuid4()
    return DecisionRecord(
        id=record_id,
        chain_id=record_id if supersedes is None else supersedes.chain_id,
        supersedes_id=None if supersedes is None else supersedes.id,
        relation=relation,
        category="meeting_recorded",
        summary=f"[SYNTHETIC] Note {revision}",
        explanation="[SYNTHETIC] Explanation",
        occurred_on=date(2026, 10, 12),
        decision_maker="recorder",
        decision_maker_role=None,
        evidence_status="none",
        evidence=(),
        change_reason=None if supersedes is None else "[SYNTHETIC] Reason",
        revision=revision,
        request_key=uuid.uuid4(),
        recorded_by_user_id=by,
        intake_status="case_created",
        progression_status="unavailable",
        recorded_at=at,
    )


# --- vocabulary and validation ------------------------------------------------------------


def test_the_categories_are_the_databases_and_factual_only() -> None:
    assert tuple(c.key for c in CATEGORIES) == DECISION_CATEGORIES
    words = " ".join(f"{c.key} {c.label} {c.description}" for c in CATEGORIES).lower()
    for word in ("warning", "suspen", "penalt", "dismiss", "terminat", "approv", "misconduct"):
        assert word not in words


@pytest.mark.parametrize(
    ("validator", "value", "message"),
    [
        (decisions.single_line, "", "must not be empty"),
        (decisions.single_line, "   ", "must not be empty"),
        (decisions.single_line, " x", "must not start or end with whitespace"),
        (decisions.single_line, "a\nb", "must not contain control characters"),
        (decisions.single_line, "a​b", "must not contain control characters"),
        (decisions.multi_line, "x\n", "must not start or end with whitespace"),
        (decisions.multi_line, "a\rb", "must not contain control characters"),
        (decisions.evidence_text, "https://files.example.invalid/x", "not link to it"),
        (decisions.evidence_text, "HTTP://X.INVALID", "not link to it"),
        (decisions.evidence_text, "smb://server/share", "not link to it"),
        (decisions.evidence_text, "see www.example.invalid", "not link to it"),
        (decisions.evidence_text, "javascript:alert(1)", "not link to it"),
        (decisions.evidence_text, "data:text/html,x", "not link to it"),
    ],
)
def test_validators_refuse_with_fixed_messages(validator, value: str, message: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match=message) as caught:
        validator(value)
    assert value.strip() == "" or value not in str(caught.value)


@pytest.mark.parametrize(
    "value",
    ["File: HR-2026-014", "Data: shift handover log", "Policy 4.2 (Code of conduct)", "x"],
)
def test_plain_evidence_references_are_accepted(value: str) -> None:
    assert decisions.evidence_text(value) == value


def test_multi_line_text_keeps_line_breaks_and_tabs() -> None:
    value = "First line\n\tIndented second line"
    assert decisions.multi_line(value) == value


def test_event_dates() -> None:
    today = date(2026, 10, 18)
    assert decisions.event_date("2026-10-19", today=today) == date(2026, 10, 19)
    for value, message in (
        ("2026-10-20", "must not be in the future"),
        ("1989-12-31", "too far in the past"),
        ("2026-1-1", "YYYY-MM-DD"),
        ("2026-02-30", "YYYY-MM-DD"),
        ("20261018", "YYYY-MM-DD"),
    ):
        with pytest.raises(ValueError, match=message):
            decisions.event_date(value, today=today)


# --- chains ------------------------------------------------------------------------------


def test_chain_positions_number_versions_and_mark_the_current_one() -> None:
    first = make_record(1)
    second = make_record(3, supersedes=first, relation="correction")
    third = make_record(4, supersedes=second, relation="clarification")
    alone = make_record(2)
    positions = chain_positions([third, alone, first, second])
    assert positions[first.id].version == 1 and positions[first.id].superseded_by == second.id
    assert positions[second.id].version == 2 and not positions[second.id].current
    assert positions[third.id].version == 3 and positions[third.id].current
    assert positions[alone.id].version == 1 and positions[alone.id].current


def test_a_retry_matches_only_the_same_request() -> None:
    record = make_record(1)
    fields = {
        "user_id": VIEWER,
        "supersedes_id": None,
        "relation": "original",
        "category": record.category,
        "summary": record.summary,
        "explanation": record.explanation,
        "occurred_on": record.occurred_on,
        "decision_maker": "recorder",
        "decision_maker_role": None,
        "evidence_status": "none",
        "evidence": [],
        "change_reason": None,
    }
    assert same_request(record, **fields)  # type: ignore[arg-type]
    for change in (
        {"user_id": OTHER},
        {"summary": "[SYNTHETIC] Other"},
        {"evidence_status": "held", "evidence": [EvidenceReference("policy", "x", None)]},
        {"relation": "correction"},
        {"supersedes_id": uuid.uuid4()},
    ):
        assert not same_request(record, **{**fields, **change})  # type: ignore[arg-type]


# --- the unified timeline ----------------------------------------------------------------


def _history(submission: uuid.UUID, revision: int, at: datetime) -> list[HistoryItem]:
    return [
        HistoryItem("created", "case_created", T0, True, "Case created", None, 0),
        HistoryItem(
            f"submission:{submission}", "answers_saved", at, True, "Answers saved", None, revision
        ),
        HistoryItem(
            f"evaluation:{submission}:hold",
            "hold_placed",
            at,
            True,
            "Case held for specialist review",
            None,
            revision,
        ),
        HistoryItem(
            f"evaluation:{submission}:screening",
            "screening",
            at,
            True,
            "High-risk factor reported",
            None,
            revision,
        ),
    ]


def _event(kind: str, revision: int, at: datetime, decision: str = "allow") -> StoredEvent:
    return StoredEvent(
        id=uuid.uuid4(),
        kind=kind,  # type: ignore[arg-type]
        transition="pathway:less_serious" if kind == "pathway_selected" else "start:test_stage",
        pathway="less_serious",
        previous_pathway=None,
        stage=None if kind == "pathway_selected" else "test_stage",
        decision=decision,  # type: ignore[arg-type]
        reasons=[],
        acknowledged=[],
        revision=revision,
        request_key=None if kind == "escalation_recorded" else uuid.uuid4(),
        actor_user_id=OTHER,
        bundle_version="synthetic.1",
        occurred_at=at,
    )


def _progress_items(events: list[StoredEvent]) -> list[ProgressHistoryItem]:
    return [
        ProgressHistoryItem(f"progress:{e.id}", e.kind, e.occurred_at, False, e.kind, None)
        for e in events
    ]


def test_the_timeline_is_causal_even_when_clocks_disagree() -> None:
    submission = uuid.uuid4()
    # Revision 2's transaction started first (earlier timestamp) but committed
    # after revision 1: the revision decides, not the clock.
    late_start = T0 + timedelta(seconds=5)
    early_start = T0 + timedelta(seconds=1)
    pathway = _event("pathway_selected", 1, late_start)
    record = make_record(2, at=early_start)
    refused = _event("transition_rejected", 2, early_start, decision="block")
    escalated = _event("escalation_recorded", 3, T0 + timedelta(seconds=9), decision="escalate")
    events = [pathway, refused, escalated]
    entries = compose_timeline(
        case_id=CASE,
        history=_history(submission, 3, T0 + timedelta(seconds=9)),
        events=events,
        progress_history=_progress_items(events),
        decisions=[record],
        viewer_user_id=VIEWER,
    )
    assert [e.id for e in entries] == [
        "created",
        f"progress:{pathway.id}",
        f"decision:{record.id}",
        f"progress:{refused.id}",
        f"submission:{submission}",
        f"evaluation:{submission}:hold",
        f"evaluation:{submission}:screening",
        f"progress:{escalated.id}",
    ]
    by_id = {e.id: e for e in entries}
    assert by_id["created"].nature == "workflow_change" and by_id["created"].source_id == CASE
    assert by_id[f"submission:{submission}"].nature == "employer_record"
    assert by_id[f"evaluation:{submission}:hold"].nature == "system_check"
    assert by_id[f"evaluation:{submission}:hold"].status == "on_hold"
    assert by_id[f"evaluation:{submission}:hold"].source_id == submission
    assert by_id[f"progress:{refused.id}"].nature == "refused_request"
    assert by_id[f"progress:{refused.id}"].status == "refused"
    assert by_id[f"progress:{escalated.id}"].status == "specialist_review"
    assert by_id[f"progress:{pathway.id}"].status == "applied"
    assert by_id[f"decision:{record.id}"].by_viewer is True
    assert by_id[f"progress:{pathway.id}"].by_viewer is False


def test_entries_sharing_a_timestamp_keep_one_order() -> None:
    first = make_record(1)
    records = [first]
    for revision in range(2, 7):
        records.append(make_record(revision, supersedes=records[-1], relation="correction"))
    composed = [
        compose_timeline(
            case_id=CASE,
            history=[HistoryItem("created", "case_created", T0, True, "Case created", None, 0)],
            events=[],
            progress_history=[],
            decisions=list(shuffled),
            viewer_user_id=VIEWER,
        )
        for shuffled in (records, list(reversed(records)), records[3:] + records[:3])
    ]
    assert composed[0] == composed[1] == composed[2]
    assert [e.revision for e in composed[0]] == [0, 1, 2, 3, 4, 5, 6]
    statuses = [e.status for e in composed[0][1:]]
    assert statuses == ["superseded"] * 5 + ["current"]
    assert composed[0][2].link is not None
    assert composed[0][2].link.supersedes == f"decision:{first.id}"


def test_pages_are_newest_first_and_cover_every_entry_once() -> None:
    records = [make_record(revision) for revision in range(1, 8)]
    entries = compose_timeline(
        case_id=CASE,
        history=[HistoryItem("created", "case_created", T0, True, "Case created", None, 0)],
        events=[],
        progress_history=[],
        decisions=records,
        viewer_user_id=VIEWER,
    )
    pages, cursor = [], None
    while True:
        page = timeline_page(entries, before=cursor, limit=3)
        assert page is not None and page.total == 8
        pages.append([e.id for e in page.entries])
        cursor = page.next_before
        if cursor is None:
            break
    assert [len(p) for p in pages] == [3, 3, 2]
    flat = [entry for page in pages for entry in page]
    assert flat == [e.id for e in reversed(entries)]
    assert timeline_page(entries, before="decision:unknown", limit=3) is None
    exact = timeline_page(entries, before=None, limit=8)
    assert exact is not None and exact.next_before is None
    assert timeline_page([], before=None, limit=3) == timeline_page([], before=None, limit=3)
