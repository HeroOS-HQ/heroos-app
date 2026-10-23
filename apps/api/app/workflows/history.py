"""Case history (M2-02): a traceable timeline of material intake events.

Composed on read from append-only records only, so it can't drift from them:

- the workflow instance (Case created, by whom, when);
- each saved submission (which answers changed: labels only, never values;
  for sensitive questions only how many changed); one an Ask HeroOS turn
  produced reads "Case information updated through Ask HeroOS" (M2-NEW-07);
- each stored intake evaluation, compared with the one before it: the Case
  jurisdiction confirmed or no longer confirmed (and on what basis), holds
  placed, kept or lifted (and why: a specialist-review hold is only ever kept,
  never lifted by changed answers), the screening result, cautions raised or
  no longer applying (a hold suppresses showing a caution, not its record),
  and the intake recorded.

The current state shown elsewhere is recomputed live; an entry here records
what each save produced at the time. Wording is neutral, contains no rule keys
and never restates an answer's value. Cases saved before M2-02 have no
evaluations for those saves; their history starts with the submissions.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from app.workflows.conditions import RuleSet
from app.workflows.conversation import (
    ASSISTANT_CORRECTION_TITLE,
    ASSISTANT_ORIGIN,
    ASSISTANT_UPDATE_TITLE,
    SubmissionRecord,
    caution_notices,
)
from app.workflows.definition import Step, WorkflowDefinition
from app.workflows.intake import JURISDICTION_LABELS, IntakeEvaluation

HistoryKind = Literal[
    "case_created",
    "answers_saved",
    "jurisdiction",
    "hold_placed",
    "hold_kept",
    "hold_lifted",
    "screening",
    "caution",
    "intake_recorded",
]


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    """One stored ``workflow_evaluations`` row as the read path sees it."""

    submission_id: UUID
    status: str
    hold: str | None
    hold_reason: str | None
    jurisdiction: str | None
    screening: str
    results: Sequence[Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class HistoryItem:
    id: str
    kind: HistoryKind
    at: datetime
    # True: the viewer; False: another administrator; None: not attributed.
    by_viewer: bool | None
    title: str
    detail: str | None
    # The instance revision the entry belongs to (0: the Case's creation), for
    # ordering it among other sources (app.workflows.timeline).
    revision: int = 0


def evaluation_results(evaluation: IntakeEvaluation, ruleset: RuleSet) -> list[dict[str, object]]:
    """The stored ``results`` of an evaluation: one entry per rule, in order."""
    data: list[dict[str, object]] = []
    for result in evaluation.results:
        rule = ruleset.rule(result.rule)
        data.append(
            {
                "rule": result.rule,
                "order": rule.order,
                "applies_in": list(rule.applies_in),
                "provisional": rule.provisional,
                "enforced": rule.enforced,
                "outcome": result.outcome,
                "action": result.action,
                "reason": result.reason,
                "shown": result.shown,
                "inputs": dict(result.inputs),
            }
        )
    return data


_HOLD_TEXT: Final[Mapping[str, str]] = {
    "high_risk_factors": "A screening answer needs specialist advice first.",
    "jurisdiction_different": "A different jurisdiction applies to this employee.",
    "jurisdiction_unsupported": "The company's confirmed jurisdiction isn't supported yet.",
    "screening_not_covered": "Safety screening isn't available for this jurisdiction yet.",
    "company_jurisdiction_unconfirmed": "The company's jurisdiction isn't confirmed yet.",
    "case_jurisdiction_not_sure": "The jurisdiction for this case wasn't confirmed (“Not sure”).",
    "case_jurisdiction_outdated": "The company's jurisdiction changed after it was confirmed "
    "for this case.",
    "earlier_escalation": "Changed answers don't release a specialist-review hold.",
}
_SCREENING_TEXT: Final[Mapping[str, tuple[str, str]]] = {
    "cleared": (
        "Safety screening completed",
        "No high-risk factors were reported. This isn't a legal assessment.",
    ),
    "not_cleared": (
        "Safety screening not cleared",
        "One or more answers were “Not sure”.",
    ),
    "positive": (
        "High-risk factor reported in the safety screening",
        "The case was held for specialist review. This isn't a finding about the employee.",
    ),
}


def _fired_cautions(record: EvaluationRecord, titles: Mapping[str, str]) -> list[str]:
    """Cautions whose rule fired (shown or, while held, recorded only)."""
    keys: list[str] = []
    for result in record.results:
        rule = result.get("rule")
        if (
            result.get("outcome") == "fired"
            and result.get("action") == "warn"
            and isinstance(rule, str)
            and rule in titles
        ):
            keys.append(rule)
    return keys


def _evaluation_items(
    prefix: str,
    at: datetime,
    by_viewer: bool | None,
    previous: EvaluationRecord | None,
    current: EvaluationRecord,
    revision: int,
) -> list[HistoryItem]:
    items: list[HistoryItem] = []

    def add(kind: HistoryKind, key: str, title: str, detail: str | None) -> None:
        items.append(HistoryItem(f"{prefix}:{key}", kind, at, by_viewer, title, detail, revision))

    before_jurisdiction = previous.jurisdiction if previous else None
    if current.jurisdiction != before_jurisdiction:
        if current.jurisdiction is not None:
            add(
                "jurisdiction",
                "jurisdiction",
                "Jurisdiction confirmed for this case: "
                f"{JURISDICTION_LABELS.get(current.jurisdiction, current.jurisdiction)}",
                "Based on the company's confirmed jurisdiction and the confirmation for this case.",
            )
        else:
            add(
                "jurisdiction",
                "jurisdiction",
                "Jurisdiction no longer confirmed for this case",
                None,
            )

    before_hold = (previous.hold, previous.hold_reason) if previous else (None, None)
    if (current.hold, current.hold_reason) != before_hold:
        if current.hold == "specialist_review" and before_hold[0] == "specialist_review":
            # Still escalated: a specialist-review hold is kept, never lifted.
            add(
                "hold_kept",
                "hold",
                "Hold kept after answers changed",
                _HOLD_TEXT.get(current.hold_reason or ""),
            )
        elif current.hold is not None and current.hold_reason is not None:
            title = (
                "Case held for specialist review"
                if current.hold == "specialist_review"
                else "Case paused until the jurisdiction is confirmed"
            )
            add("hold_placed", "hold", title, _HOLD_TEXT.get(current.hold_reason))
        else:
            add(
                "hold_lifted",
                "hold",
                "Hold lifted after answers changed",
                "The earlier answers stay in this history.",
            )

    before_screening = previous.screening if previous else None
    if current.screening != before_screening and current.screening in _SCREENING_TEXT:
        title, detail = _SCREENING_TEXT[current.screening]
        add("screening", "screening", title, detail)

    titles = {key: title for key, (title, _) in caution_notices().items()}
    before = set(_fired_cautions(previous, titles)) if previous else set()
    after = _fired_cautions(current, titles)
    for key in after:
        if key not in before and key in titles:
            add("caution", f"caution:{key}", f"Caution raised: {titles[key]}", None)
    for key in sorted(before - set(after)):
        if key in titles:
            add("caution", f"caution:{key}", f"Caution no longer applies: {titles[key]}", None)

    if current.status == "intake_recorded" and (
        previous is None or previous.status != current.status
    ):
        add(
            "intake_recorded",
            "intake",
            "Intake recorded",
            "Preliminary status, not a legal assessment.",
        )
    return items


@dataclass(frozen=True, slots=True)
class FactVersion:
    """One value a Case question held (answers are append-only: an earlier value is never
    erased). ``value`` None: the answer was cleared, superseded with nothing in its place."""

    value: object | None
    revision: int
    submitted_at: datetime
    origin: str
    submission_id: UUID
    # The founder message an Ask HeroOS submission came from (the correction's, for a correction).
    source_message_id: UUID | None
    status: Literal["current", "superseded"]


def fact_versions(submissions: Sequence[SubmissionRecord]) -> dict[str, list[FactVersion]]:
    """Per Case question, every value it held, oldest first: the latest is current, every earlier
    one superseded (by the employer's form, or by the founder's validated correction in Ask
    HeroOS, which names the correcting message)."""
    versions: dict[str, list[FactVersion]] = {}
    for submission in sorted(submissions, key=lambda s: s.revision):
        for key, value in submission.facts.items():
            versions.setdefault(key, []).append(
                FactVersion(
                    value,
                    submission.revision,
                    submission.submitted_at,
                    submission.origin,
                    submission.id,
                    submission.source_message_id,
                    "current",
                )
            )
    for chain in versions.values():
        chain[:-1] = [replace(v, status="superseded") for v in chain[:-1]]
    return versions


def compose_history(
    definition: WorkflowDefinition,
    *,
    created_at: datetime,
    created_by_user_id: UUID,
    submissions: Sequence[SubmissionRecord],
    evaluations: Mapping[UUID, EvaluationRecord],
    viewer_user_id: UUID,
    extra_steps: Sequence[Step] = (),
) -> list[HistoryItem]:
    """The Case timeline, oldest first.

    ``extra_steps``: the installed rules' stage checklists (M2-03), whose saves
    are labelled like any other. A checklist saved under rules that aren't
    installed any more reads as a stage checklist, with a count of answers.
    """
    extra = {step.key: step for step in extra_steps}
    steps = (*definition.steps, *extra_steps)
    labels = {q.key: q.label for s in steps for q in s.questions}
    sensitive = {q.key for s in steps for q in s.questions if q.sensitive}
    items = [
        HistoryItem(
            "created",
            "case_created",
            created_at,
            created_by_user_id == viewer_user_id,
            "Case created",
            None,
        )
    ]
    previous: EvaluationRecord | None = None
    versions = fact_versions(submissions)
    for submission in sorted(submissions, key=lambda s: s.revision):
        by_viewer = submission.submitted_by_user_id == viewer_user_id
        step = definition.step(submission.step_key) or extra.get(submission.step_key)
        changed = [labels[k] for k in labels if k in submission.facts and k not in sensitive]
        hidden = sum(1 for k in submission.facts if k in sensitive)
        if hidden:
            # Which sensitive answer changed isn't repeated in the history.
            changed.append(f"{hidden} screening answer{'s' if hidden > 1 else ''}")
        unlabelled = sum(1 for k in submission.facts if k not in labels)
        if unlabelled:
            changed.append(f"{unlabelled} answer{'s' if unlabelled > 1 else ''}")
        title = f"Answers saved: {step.title if step else 'stage checklist'}"
        if submission.origin == ASSISTANT_ORIGIN:
            # A founder's correction supersedes an earlier answer: said as such, the earlier one
            # kept (``fact_versions``), never a value restated.
            corrects = any(versions[k][0].submission_id != submission.id for k in submission.facts)
            title = ASSISTANT_CORRECTION_TITLE if corrects else ASSISTANT_UPDATE_TITLE
        items.append(
            HistoryItem(
                f"submission:{submission.id}",
                "answers_saved",
                submission.submitted_at,
                by_viewer,
                title,
                ("Changed: " + ", ".join(changed)) if changed else None,
                submission.revision,
            )
        )
        record = evaluations.get(submission.id)
        if record is not None:
            items += _evaluation_items(
                f"evaluation:{submission.id}",
                submission.submitted_at,
                by_viewer,
                previous,
                record,
                submission.revision,
            )
            previous = record
    return items
