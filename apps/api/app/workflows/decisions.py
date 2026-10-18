"""Employer decision records (M2-04): vocabulary, validation and correction chains.

A decision record is the employer's own account of how it is handling a Case:
an internal review completed, information requested, a meeting held, an
observation, a pause or follow-up, or another factual note. HeroOS stores it as
entered and verifies none of it. It is never a workflow authorization: no
category is a warning, suspension, penalty, dismissal, finding or specialist
approval, and recording one never moves a stage or releases a hold (the write
path never calls the progression engine).

Corrections never overwrite. A correction (the earlier record was wrong) or a
clarification (it was incomplete) is a new complete version that supersedes
exactly one earlier version of the same chain. Only the latest version of a
chain can be superseded, so each chain is a single line: the latest version is
current, every earlier one is superseded and stays in the history.

Evidence is referenced, never held: the employer says whether it holds
supporting evidence and describes it (a document name, a meeting note, a
policy); HeroOS stores no file and accepts no link. Pure module: no database.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from app.db.models.workflow import (
    DECISION_CATEGORIES,
    DECISION_EVIDENCE_KINDS,
    DECISION_EVIDENCE_STATUSES,
    DECISION_MAKERS,
)
from app.workflows.answers import EARLIEST_DATE, TEXT_CONTROL_CHARACTERS

Relation = Literal["original", "correction", "clarification"]
DecisionMaker = Literal["recorder", "other"]
EvidenceStatus = Literal["held", "none", "not_sure"]


@dataclass(frozen=True, slots=True)
class Choice:
    key: str
    label: str
    description: str


CATEGORIES: Final = (
    Choice(
        "internal_review_completed",
        "Internal review completed",
        "Your company finished an internal review of the matter.",
    ),
    Choice(
        "information_requested",
        "Additional information requested",
        "Your company asked someone for more information about the matter.",
    ),
    Choice(
        "meeting_recorded",
        "Meeting or discussion recorded",
        "A meeting or discussion about the matter took place.",
    ),
    Choice(
        "employer_observation",
        "Employer observation",
        "Something your company observed and wants on record.",
    ),
    Choice(
        "internal_pause_or_follow_up",
        "Internal pause or follow-up decision",
        "Your company decided to pause its internal process, or to follow up later.",
    ),
    Choice(
        "other_note",
        "Other factual case note",
        "Any other factual note about how your company is handling the case.",
    ),
)
EVIDENCE_KINDS: Final = (
    Choice("internal_document", "Internal document", "A document your company holds."),
    Choice("meeting_note", "Meeting note", "Notes or minutes of a meeting or discussion."),
    Choice("policy", "Company policy", "A policy, handbook or code of conduct."),
    Choice("other", "Other evidence", "Other evidence your company holds."),
)
EVIDENCE_STATUSES: Final = (
    Choice(
        "held",
        "Yes, my company holds supporting evidence",
        "Describe each item below. Keep the evidence itself in your company's own records.",
    ),
    Choice("none", "No supporting evidence is available", "That's recorded as you say it."),
    Choice("not_sure", "Not sure yet", "You can add references later with a clarification."),
)
DECISION_MAKER_CHOICES: Final = (
    Choice("recorder", "Me", "I'm recording my own decision or observation."),
    Choice(
        "other",
        "Someone else in my company",
        "Give their role or job title, for example “Operations manager”. A name isn't needed.",
    ),
)
# The stored vocabularies are the database's; the wording must cover them exactly.
assert tuple(c.key for c in CATEGORIES) == DECISION_CATEGORIES
assert tuple(c.key for c in EVIDENCE_KINDS) == DECISION_EVIDENCE_KINDS
assert tuple(c.key for c in EVIDENCE_STATUSES) == DECISION_EVIDENCE_STATUSES
assert tuple(c.key for c in DECISION_MAKER_CHOICES) == DECISION_MAKERS

CATEGORY_LABELS: Final[Mapping[str, str]] = {c.key: c.label for c in CATEGORIES}
EVIDENCE_KIND_LABELS: Final[Mapping[str, str]] = {c.key: c.label for c in EVIDENCE_KINDS}

RECORDS_NOTICE: Final = (
    "Records here are your company's own account of what it did or decided. HeroOS stores "
    "them as you enter them and doesn't verify them. A record doesn't move the case to another "
    "stage, doesn't release a hold, and isn't a warning, a penalty or any other disciplinary "
    "outcome."
)
NOT_RECORDABLE_NOTICE: Final = (
    "Warnings, suspensions, penalties, dismissals, findings of misconduct and specialist "
    "approvals can't be recorded here. They depend on approved rules and stages that aren't "
    "available in HeroOS yet."
)
EVIDENCE_NOTICE: Final = (
    "Describe evidence your company holds, such as a document name or reference number. "
    "Don't upload or paste the evidence itself, and don't enter links. HeroOS doesn't check "
    "evidence."
)

# --- validation (fixed messages; a submitted value is never echoed) -----------------

# Anything that looks like a link: a scheme with "//" (http, https, ftp, file,
# smb...), a "www." address, or a script or data URI. HeroOS stores no link it
# might later render or open (evidence is described, never fetched). Plain
# references such as "File: HR-2026-014" stay valid.
_LINK: Final = re.compile(
    r"://|(?:^|[^a-z0-9])www\.|^\s*(?:javascript|vbscript|data):\S",
    re.IGNORECASE,
)


def single_line(value: str) -> str:
    """Text on one line, stored exactly as sent: no surrounding space, no control character."""
    if value.strip() == "":
        raise ValueError("must not be empty")
    if value != value.strip():
        raise ValueError("must not start or end with whitespace")
    if not value.isprintable():
        raise ValueError("must not contain control characters")
    return value


def multi_line(value: str) -> str:
    """Free text: line breaks and tabs allowed, nothing else invisible."""
    if value.strip() == "":
        raise ValueError("must not be empty")
    if value != value.strip():
        raise ValueError("must not start or end with whitespace")
    if any(not c.isprintable() and c not in TEXT_CONTROL_CHARACTERS for c in value):
        raise ValueError("must not contain control characters")
    return value


def evidence_text(value: str) -> str:
    """An evidence description or reference: one line, never a link."""
    single_line(value)
    if _LINK.search(value):
        raise ValueError("must describe the evidence, not link to it")
    return value


def event_date(value: str, *, today: date) -> date:
    """Exactly YYYY-MM-DD, not in the future (one day of tolerance for time zones)."""
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise ValueError("must be a date (YYYY-MM-DD)")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("must be a date (YYYY-MM-DD)") from None
    if parsed > today + timedelta(days=1):
        raise ValueError("must not be in the future")
    if parsed < EARLIEST_DATE:
        raise ValueError("is too far in the past")
    return parsed


# --- stored records and their chains -------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    kind: str
    description: str
    reference: str | None

    def stored(self) -> dict[str, str | None]:
        return {"kind": self.kind, "description": self.description, "reference": self.reference}


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """One stored ``workflow_decision_records`` row as the read path sees it."""

    id: UUID
    chain_id: UUID
    supersedes_id: UUID | None
    relation: Relation
    category: str
    summary: str
    explanation: str
    occurred_on: date
    decision_maker: DecisionMaker
    decision_maker_role: str | None
    evidence_status: EvidenceStatus
    evidence: tuple[EvidenceReference, ...]
    change_reason: str | None
    revision: int
    request_key: UUID
    recorded_by_user_id: UUID
    intake_status: str
    progression_status: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class ChainPosition:
    """Where a record sits in its correction chain."""

    version: int
    superseded_by: UUID | None

    @property
    def current(self) -> bool:
        return self.superseded_by is None


def chain_positions(records: Sequence[DecisionRecord]) -> dict[UUID, ChainPosition]:
    """Each record's version in its chain and the record that superseded it, if any.

    The database guarantees the shape (one successor per record, the same chain,
    no cycle); this only reads it.
    """
    successor = {r.supersedes_id: r.id for r in records if r.supersedes_id is not None}
    positions: dict[UUID, ChainPosition] = {}
    for root in (r for r in records if r.supersedes_id is None):
        version, current = 1, root.id
        while True:
            positions[current] = ChainPosition(version, successor.get(current))
            following = successor.get(current)
            if following is None:
                break
            version, current = version + 1, following
    return positions


def same_request(
    record: DecisionRecord,
    *,
    user_id: UUID,
    supersedes_id: UUID | None,
    relation: Relation,
    category: str,
    summary: str,
    explanation: str,
    occurred_on: date,
    decision_maker: str,
    decision_maker_role: str | None,
    evidence_status: str,
    evidence: Sequence[EvidenceReference],
    change_reason: str | None,
) -> bool:
    """A retry of the request that stored ``record`` (rather than a reused key)."""
    return (
        record.recorded_by_user_id == user_id
        and record.supersedes_id == supersedes_id
        and record.relation == relation
        and record.category == category
        and record.summary == summary
        and record.explanation == explanation
        and record.occurred_on == occurred_on
        and record.decision_maker == decision_maker
        and record.decision_maker_role == decision_maker_role
        and record.evidence_status == evidence_status
        and record.evidence == tuple(evidence)
        and record.change_reason == change_reason
    )


def timeline_title(record: DecisionRecord) -> str:
    label = CATEGORY_LABELS.get(record.category, "Case note")
    if record.relation == "correction":
        return f"Employer record corrected: {label}"
    if record.relation == "clarification":
        return f"Employer record clarified: {label}"
    return f"Employer record: {label}"


def timeline_detail(record: DecisionRecord, position: ChainPosition | None) -> str:
    detail = f"“{record.summary}”"
    if record.relation != "original":
        detail += " Replaces an earlier version, which stays in this history."
    if position is not None and not position.current:
        detail += " A later version replaced this one."
    return detail
