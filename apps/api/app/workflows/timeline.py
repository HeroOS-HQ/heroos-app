"""Unified case history (M2-04): one chronological projection over every source.

Composed on read from the append-only records the earlier slices already keep,
with the wording they already use; nothing is copied into a second event store:

- the Case's creation, each saved answer group and what each save's intake
  evaluation changed (M2-01, M2-02: ``app.workflows.history``);
- progression: pathway choices, stages started and completed, refused requests
  and recorded escalations (M2-03: ``compose_progress_history``);
- employer decision records, corrections and clarifications (M2-04).

Every entry says what kind of thing it is (``nature``), so a reader never
mistakes one for another:

- ``employer_record``: something the employer entered (answers, decision
  records); HeroOS didn't verify it;
- ``system_check``: an outcome of HeroOS's fixed checks (jurisdiction, holds,
  screening, cautions, escalations);
- ``refused_request``: a request the rules refused; nothing changed;
- ``workflow_change``: a change actually recorded in the workflow (Case
  created, pathway, stages).

**Order** is causal and total. Every write that changes a Case produces one
instance revision under the instance lock, so entries are ordered by revision
first (a timestamp is the transaction's start and can be earlier than a
revision committed before it), then, within a revision: what produced it
(a save, an applied transition, a decision record), what that save's
evaluation changed, refusals decided at it, escalations recorded at it; then
time; then the sources' own order. The same rows always give the same order,
including entries with the same timestamp.

Answers are never restated (labels and counts only, as in the M2-02 history),
no rule condition or bundle content beyond the titles already shown to the
employer appears, and a decision record contributes its short summary only
(its explanation stays with the record).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from app.workflows.decisions import (
    DecisionRecord,
    chain_positions,
    timeline_detail,
    timeline_title,
)
from app.workflows.history import HistoryItem
from app.workflows.progression.presentation import ProgressHistoryItem
from app.workflows.progression.records import StoredEvent

Nature = Literal["employer_record", "system_check", "refused_request", "workflow_change"]
Category = Literal["case", "answers", "intake", "progression", "decisions"]
SourceType = Literal["case", "submission", "intake_evaluation", "progress_event", "decision_record"]
EntryStatus = Literal["applied", "refused", "specialist_review", "on_hold", "current", "superseded"]

# Page sizes for ``timeline_page`` (a bound on the response, not a product rule).
DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGE_SIZE: Final = 100

# Within one revision: what produced it, then what its evaluation changed, then
# refusals, then escalations.
_PRODUCED, _EVALUATED, _REFUSED, _ESCALATED = 0, 1, 2, 3


@dataclass(frozen=True, slots=True)
class TimelineLink:
    """A decision record's place in its correction chain (entry ids)."""

    relation: Literal["correction", "clarification"] | None
    supersedes: str | None
    superseded_by: str | None


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    id: str
    at: datetime
    category: Category
    kind: str
    nature: Nature
    title: str
    detail: str | None
    # True: the viewer; False: another administrator; None: not attributed.
    by_viewer: bool | None
    source_type: SourceType
    source_id: UUID
    status: EntryStatus | None
    link: TimelineLink | None
    # Ordering only (see the module docstring).
    revision: int
    rank: int


@dataclass(frozen=True, slots=True)
class TimelinePage:
    # Newest first.
    entries: tuple[TimelineEntry, ...]
    # Pass as ``before`` to read the next (older) page; None on the last page.
    next_before: str | None
    total: int


def decision_entry_id(record_id: UUID) -> str:
    return f"decision:{record_id}"


def _history_entry(item: HistoryItem, case_id: UUID) -> TimelineEntry:
    """An M2-01/M2-02 history item (ids: ``created``, ``submission:<id>``,
    ``evaluation:<submission id>:<what changed>``)."""
    prefix, _, rest = item.id.partition(":")
    status: EntryStatus | None = None
    if item.kind == "case_created":
        category: Category = "case"
        nature: Nature = "workflow_change"
        source: tuple[SourceType, UUID] = ("case", case_id)
        rank = _PRODUCED
    elif item.kind == "answers_saved":
        category, nature, rank = "answers", "employer_record", _PRODUCED
        source = ("submission", UUID(rest))
    else:
        category, nature, rank = "intake", "system_check", _EVALUATED
        source = ("intake_evaluation", UUID(rest.partition(":")[0]))
        if item.kind in ("hold_placed", "hold_kept"):
            status = "on_hold"
    assert prefix in ("created", "submission", "evaluation"), item.id
    return TimelineEntry(
        id=item.id,
        at=item.at,
        category=category,
        kind=item.kind,
        nature=nature,
        title=item.title,
        detail=item.detail,
        by_viewer=item.by_viewer,
        source_type=source[0],
        source_id=source[1],
        status=status,
        link=None,
        revision=item.revision,
        rank=rank,
    )


def _progress_entry(event: StoredEvent, item: ProgressHistoryItem) -> TimelineEntry:
    if event.kind == "transition_rejected":
        nature: Nature = "refused_request"
        status: EntryStatus = "specialist_review" if event.decision == "escalate" else "refused"
        rank = _REFUSED
    elif event.kind == "escalation_recorded":
        nature, status, rank = "system_check", "specialist_review", _ESCALATED
    else:
        nature, status, rank = "workflow_change", "applied", _PRODUCED
    return TimelineEntry(
        id=item.id,
        at=item.at,
        category="progression",
        kind=event.kind,
        nature=nature,
        title=item.title,
        detail=item.detail,
        by_viewer=item.by_viewer,
        source_type="progress_event",
        source_id=event.id,
        status=status,
        link=None,
        revision=event.revision,
        rank=rank,
    )


def _decision_entries(
    records: Sequence[DecisionRecord], viewer_user_id: UUID
) -> list[TimelineEntry]:
    positions = chain_positions(records)
    entries: list[TimelineEntry] = []
    for record in records:
        position = positions.get(record.id)
        superseded_by = None if position is None else position.superseded_by
        entries.append(
            TimelineEntry(
                id=decision_entry_id(record.id),
                at=record.recorded_at,
                category="decisions",
                kind={
                    "original": "decision_recorded",
                    "correction": "decision_corrected",
                    "clarification": "decision_clarified",
                }[record.relation],
                nature="employer_record",
                title=timeline_title(record),
                detail=timeline_detail(record, position),
                by_viewer=record.recorded_by_user_id == viewer_user_id,
                source_type="decision_record",
                source_id=record.id,
                status="current" if superseded_by is None else "superseded",
                link=TimelineLink(
                    relation=None if record.relation == "original" else record.relation,
                    supersedes=None
                    if record.supersedes_id is None
                    else decision_entry_id(record.supersedes_id),
                    superseded_by=None
                    if superseded_by is None
                    else decision_entry_id(superseded_by),
                ),
                revision=record.revision,
                rank=_PRODUCED,
            )
        )
    return entries


def compose_timeline(
    *,
    case_id: UUID,
    history: Sequence[HistoryItem],
    events: Sequence[StoredEvent],
    progress_history: Sequence[ProgressHistoryItem],
    decisions: Sequence[DecisionRecord],
    viewer_user_id: UUID,
) -> list[TimelineEntry]:
    """Every entry of the Case, oldest first (causal order; see the module docstring).

    ``history`` is ``compose_history``'s output; ``progress_history`` is
    ``compose_progress_history(events)`` (one item per event, same order).
    """
    if len(events) != len(progress_history):  # pragma: no cover - one item per event
        raise ValueError("progress history doesn't match the events")
    entries = [_history_entry(item, case_id) for item in history]
    entries += [_progress_entry(e, i) for e, i in zip(events, progress_history, strict=True)]
    entries += _decision_entries(sorted(decisions, key=lambda r: r.revision), viewer_user_id)
    # Python's sort is stable: equal keys keep the sources' own (causal) order.
    order = {entry.id: index for index, entry in enumerate(entries)}
    return sorted(entries, key=lambda e: (e.revision, e.rank, e.at, order[e.id]))


def timeline_page(
    entries: Sequence[TimelineEntry], *, before: str | None, limit: int
) -> TimelinePage | None:
    """A page of the timeline, newest first; None if ``before`` names no entry.

    ``before`` is the id of the last entry of the previous page: entries never
    change or disappear (append-only sources), so a cursor stays valid while
    new entries are added on top.
    """
    newest = list(reversed(entries))
    start = 0
    if before is not None:
        index = next((i for i, e in enumerate(newest) if e.id == before), None)
        if index is None:
            return None
        start = index + 1
    page = newest[start : start + limit]
    more = start + limit < len(newest)
    return TimelinePage(
        entries=tuple(page),
        next_before=page[-1].id if more and page else None,
        total=len(newest),
    )
