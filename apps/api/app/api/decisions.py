"""Employer decision records and the unified case history (M2-04): models and composition.

The request models accept only the safe, factual record categories (a warning,
suspension, penalty, dismissal, finding or specialist approval isn't in the
vocabulary, so it is a 422 here and refused by the database too) and forbid
any other field: there is no actor, approval or status a client could send.
The authenticated administrator is taken from the session by the route.

Text is validated, never normalized, and never echoed in errors. Evidence is a
reference the employer describes: a link is refused, nothing is fetched.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

from app.db.models.workflow import (
    MAX_DECISION_CHANGE_REASON,
    MAX_DECISION_EVIDENCE_ITEMS,
    MAX_DECISION_EXPLANATION,
    MAX_DECISION_MAKER_ROLE,
    MAX_DECISION_SUMMARY,
    MAX_EVIDENCE_DESCRIPTION,
    MAX_EVIDENCE_REFERENCE,
)
from app.workflows import decisions
from app.workflows.decisions import (
    CATEGORIES,
    CATEGORY_LABELS,
    DECISION_MAKER_CHOICES,
    EVIDENCE_KIND_LABELS,
    EVIDENCE_KINDS,
    EVIDENCE_STATUSES,
    Choice,
    DecisionRecord,
    EvidenceReference,
    chain_positions,
)
from app.workflows.timeline import TimelineEntry, TimelinePage

# --- requests ------------------------------------------------------------------------

Category = Literal[
    "internal_review_completed",
    "information_requested",
    "meeting_recorded",
    "employer_observation",
    "internal_pause_or_follow_up",
    "other_note",
]
EvidenceKind = Literal["internal_document", "meeting_note", "policy", "other"]
DecisionMaker = Literal["recorder", "other"]
EvidenceStatus = Literal["held", "none", "not_sure"]
CorrectionRelation = Literal["correction", "clarification"]


def _event_date(value: object) -> date:
    # Exactly the JSON string YYYY-MM-DD (no timestamps, no other formats).
    if not isinstance(value, str):
        raise ValueError("must be a date (YYYY-MM-DD)")
    return decisions.event_date(value, today=datetime.now(UTC).date())


Summary = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=MAX_DECISION_SUMMARY),
    AfterValidator(decisions.single_line),
]
Explanation = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=MAX_DECISION_EXPLANATION),
    AfterValidator(decisions.multi_line),
]
Role = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=MAX_DECISION_MAKER_ROLE),
    AfterValidator(decisions.responsible_role),
]
ChangeReason = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=MAX_DECISION_CHANGE_REASON),
    AfterValidator(decisions.multi_line),
]
EventDate = Annotated[date, BeforeValidator(_event_date)]


class EvidenceIn(BaseModel):
    """A reference to evidence the employer holds (never the evidence itself)."""

    model_config = ConfigDict(extra="forbid")

    kind: EvidenceKind
    description: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=MAX_EVIDENCE_DESCRIPTION),
        AfterValidator(decisions.evidence_text),
    ]
    # Where the employer keeps it (a reference number, a folder); optional.
    reference: (
        Annotated[
            StrictStr,
            StringConstraints(min_length=1, max_length=MAX_EVIDENCE_REFERENCE),
            AfterValidator(decisions.evidence_text),
        ]
        | None
    ) = None

    def domain(self) -> EvidenceReference:
        return EvidenceReference(self.kind, self.description, self.reference)


class DecisionIn(BaseModel):
    """A new employer decision record or observation."""

    model_config = ConfigDict(extra="forbid")

    # The Case revision the form was based on; a record is refused if it changed.
    expected_revision: Annotated[StrictInt, Field(ge=0)]
    # Client-generated per request; a retry sends the same key.
    request_key: UUID
    category: Category
    summary: Summary
    explanation: Explanation
    # The date the employer says it happened (YYYY-MM-DD).
    occurred_on: EventDate
    decision_maker: DecisionMaker
    # Required when someone else is responsible: their role, as the employer states it.
    decision_maker_role: Annotated[Role | None, Field(validate_default=True)] = None
    evidence_status: EvidenceStatus
    evidence: Annotated[
        list[EvidenceIn],
        Field(max_length=MAX_DECISION_EVIDENCE_ITEMS, validate_default=True),
    ] = []

    @field_validator("decision_maker_role")
    @classmethod
    def _role_matches(cls, value: str | None, info: ValidationInfo) -> str | None:
        maker = info.data.get("decision_maker")
        if maker == "other" and value is None:
            raise ValueError("is required when someone else is responsible")
        if maker == "recorder" and value is not None:
            raise ValueError("must be empty when you are responsible")
        return value

    @field_validator("evidence")
    @classmethod
    def _evidence_matches(cls, value: list[EvidenceIn], info: ValidationInfo) -> list[EvidenceIn]:
        status = info.data.get("evidence_status")
        if status == "held" and not value:
            raise ValueError("must describe at least one item when evidence is held")
        if status in ("none", "not_sure") and value:
            raise ValueError("must be empty unless evidence is held")
        return value

    def evidence_references(self) -> list[EvidenceReference]:
        return [item.domain() for item in self.evidence]


class CorrectionIn(DecisionIn):
    """A new complete version of an earlier record: a correction or a clarification."""

    relation: CorrectionRelation
    # Why the earlier version is corrected or clarified.
    change_reason: ChangeReason


# --- responses -----------------------------------------------------------------------


class ChoiceOut(BaseModel):
    key: str
    label: str
    description: str


class DecisionLimitsOut(BaseModel):
    """Maximum lengths (characters) and counts the API accepts."""

    summary: int
    explanation: int
    decision_maker_role: int
    change_reason: int
    evidence_items: int
    evidence_description: int
    evidence_reference: int


class DecisionOptionsOut(BaseModel):
    """What an administrator can record, and how (safe factual categories only)."""

    categories: list[ChoiceOut]
    decision_makers: list[ChoiceOut]
    evidence_statuses: list[ChoiceOut]
    evidence_kinds: list[ChoiceOut]
    limits: DecisionLimitsOut
    # What a record is (the employer's account) and isn't (an authorization).
    notice: str
    # What can't be recorded here, and why.
    not_recordable: str
    evidence_notice: str


class EvidenceOut(BaseModel):
    kind: EvidenceKind
    kind_label: str
    description: str
    reference: str | None


class DecisionContextOut(BaseModel):
    """The workflow when the record was made (codes; the record changed none of it)."""

    revision: int
    intake_status: str
    progression_status: str


class DecisionRecordOut(BaseModel):
    id: UUID
    chain_id: UUID
    # 1 for the first record of a chain; each correction or clarification adds one.
    version: int
    relation: Literal["original", "correction", "clarification"]
    supersedes: UUID | None
    superseded_by: UUID | None
    # The latest version of its chain (only the current version can be corrected).
    current: bool
    category: Category
    category_label: str
    summary: str
    explanation: str
    occurred_on: date
    # recorder: the administrator who recorded it; other: someone the employer
    # names by role (``decision_maker_role``, an unverified employer statement).
    decision_maker: DecisionMaker
    decision_maker_role: str | None
    evidence_status: EvidenceStatus
    evidence: list[EvidenceOut]
    change_reason: str | None
    recorded_at: datetime
    # The authenticated administrator who recorded it is the viewer.
    recorded_by_viewer: bool
    context: DecisionContextOut


class DecisionsOut(BaseModel):
    options: DecisionOptionsOut
    # Newest first; earlier versions of a chain are included (superseded).
    records: list[DecisionRecordOut]
    # The caller may record (server-side role).
    can_record: bool
    # On a write response: the record this request saved (or, for a retry, had saved).
    saved: UUID | None


class TimelineSourceOut(BaseModel):
    type: Literal["case", "submission", "intake_evaluation", "progress_event", "decision_record"]
    id: UUID


class TimelineLinkOut(BaseModel):
    """A decision record's correction chain, as entry ids of this timeline."""

    relation: CorrectionRelation | None
    supersedes: str | None
    superseded_by: str | None


TimelineKind = Literal[
    "case_created",
    "answers_saved",
    "jurisdiction",
    "hold_placed",
    "hold_kept",
    "hold_lifted",
    "screening",
    "caution",
    "intake_recorded",
    "pathway_selected",
    "stage_started",
    "stage_completed",
    "transition_rejected",
    "escalation_recorded",
    "decision_recorded",
    "decision_corrected",
    "decision_clarified",
]


class TimelineEntryOut(BaseModel):
    # Stable; also the ``before`` cursor of the next page.
    id: str
    at: datetime
    category: Literal["case", "answers", "intake", "progression", "decisions"]
    kind: TimelineKind
    # employer_record: entered by the employer (not verified); system_check: an
    # outcome of HeroOS's fixed checks; refused_request: refused, nothing
    # changed; workflow_change: recorded in the workflow.
    nature: Literal["employer_record", "system_check", "refused_request", "workflow_change"]
    title: str
    detail: str | None
    by_viewer: bool | None
    source: TimelineSourceOut
    status: (
        Literal["applied", "refused", "specialist_review", "on_hold", "current", "superseded"]
        | None
    )
    link: TimelineLinkOut | None


class TimelinePageOut(BaseModel):
    # Newest first.
    entries: list[TimelineEntryOut]
    # Pass as ``before`` for the next (older) page; None on the last page.
    next_before: str | None
    total: int


def _choices(choices: Sequence[Choice]) -> list[ChoiceOut]:
    return [ChoiceOut(key=c.key, label=c.label, description=c.description) for c in choices]


def decision_options() -> DecisionOptionsOut:
    return DecisionOptionsOut(
        categories=_choices(CATEGORIES),
        decision_makers=_choices(DECISION_MAKER_CHOICES),
        evidence_statuses=_choices(EVIDENCE_STATUSES),
        evidence_kinds=_choices(EVIDENCE_KINDS),
        limits=DecisionLimitsOut(
            summary=MAX_DECISION_SUMMARY,
            explanation=MAX_DECISION_EXPLANATION,
            decision_maker_role=MAX_DECISION_MAKER_ROLE,
            change_reason=MAX_DECISION_CHANGE_REASON,
            evidence_items=MAX_DECISION_EVIDENCE_ITEMS,
            evidence_description=MAX_EVIDENCE_DESCRIPTION,
            evidence_reference=MAX_EVIDENCE_REFERENCE,
        ),
        notice=decisions.RECORDS_NOTICE,
        not_recordable=decisions.NOT_RECORDABLE_NOTICE,
        evidence_notice=decisions.EVIDENCE_NOTICE,
    )


def decisions_out(
    records: Sequence[DecisionRecord],
    *,
    viewer_user_id: UUID,
    can_record: bool,
    saved: UUID | None = None,
) -> DecisionsOut:
    positions = chain_positions(records)
    return DecisionsOut(
        options=decision_options(),
        records=[
            DecisionRecordOut(
                id=record.id,
                chain_id=record.chain_id,
                version=positions[record.id].version,
                relation=record.relation,
                supersedes=record.supersedes_id,
                superseded_by=positions[record.id].superseded_by,
                current=positions[record.id].current,
                category=record.category,  # type: ignore[arg-type]  # CHECK constraint
                category_label=CATEGORY_LABELS[record.category],
                summary=record.summary,
                explanation=record.explanation,
                occurred_on=record.occurred_on,
                decision_maker=record.decision_maker,
                decision_maker_role=record.decision_maker_role,
                evidence_status=record.evidence_status,
                evidence=[
                    EvidenceOut(
                        kind=item.kind,  # type: ignore[arg-type]  # validated on write
                        kind_label=EVIDENCE_KIND_LABELS.get(item.kind, "Evidence"),
                        description=item.description,
                        reference=item.reference,
                    )
                    for item in record.evidence
                ],
                change_reason=record.change_reason,
                recorded_at=record.recorded_at,
                recorded_by_viewer=record.recorded_by_user_id == viewer_user_id,
                context=DecisionContextOut(
                    revision=record.revision,
                    intake_status=record.intake_status,
                    progression_status=record.progression_status,
                ),
            )
            for record in sorted(records, key=lambda r: r.revision, reverse=True)
        ],
        can_record=can_record,
        saved=saved,
    )


def _entry_out(entry: TimelineEntry) -> TimelineEntryOut:
    return TimelineEntryOut(
        id=entry.id,
        at=entry.at,
        category=entry.category,
        kind=entry.kind,  # type: ignore[arg-type]  # the sources' vocabularies
        nature=entry.nature,
        title=entry.title,
        detail=entry.detail,
        by_viewer=entry.by_viewer,
        source=TimelineSourceOut(type=entry.source_type, id=entry.source_id),
        status=entry.status,
        link=None
        if entry.link is None
        else TimelineLinkOut(
            relation=entry.link.relation,
            supersedes=entry.link.supersedes,
            superseded_by=entry.link.superseded_by,
        ),
    )


def timeline_out(page: TimelinePage) -> TimelinePageOut:
    return TimelinePageOut(
        entries=[_entry_out(entry) for entry in page.entries],
        next_before=page.next_before,
        total=page.total,
    )
