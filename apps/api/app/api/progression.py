"""The ``progression`` block of the workflow view (M2-03): models and composition.

Everything here is derived from the progression evaluation the backend
computed (``app.workflows.progression.engine``); the browser only renders it.
What is offered is exactly what the backend would accept: a transition the
evaluation doesn't allow is shown with its reasons, never as an alternative
route. While an engine gate applies to the whole Case (no installed rules, a
hold, an incomplete intake, an uncovered jurisdiction), only the gate's own
explanation is shown: no bundle guidance is offered for a held Case.

Answers are never echoed: missing information is listed by question label.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.workflows.definition import Option
from app.workflows.progression.bundle import JurisdictionProgram
from app.workflows.progression.engine import (
    ProgressionEvaluation,
    RuleResult,
    TransitionEvaluation,
)
from app.workflows.progression.presentation import (
    GATE_TEXT,
    STATUS_LABELS,
    compose_progress_history,
    label_for,
    transition_label,
)
from app.workflows.progression.records import StoredEvent
from app.workflows.progression.spec import ProgressionSpec

DecisionOut = Literal["allow", "warn", "block", "escalate"]


class ProgressStatusOut(BaseModel):
    code: str
    label: str


class ProgressMessageOut(BaseModel):
    # An engine gate code or a bundle rule key (stable; never an answer).
    code: str
    action: Literal["warn", "block", "escalate"]
    source: Literal["engine", "bundle"]
    title: str
    body: str
    # Content still under review: never presented as approved advice.
    provisional: bool


class TransitionOut(BaseModel):
    # Send it back to request the transition.
    key: str
    kind: Literal["pathway", "start", "complete"]
    label: str
    decision: DecisionOut
    # The backend would apply it now (with the warnings acknowledged, if any).
    allowed: bool
    # Why it is refused (blocked or escalated); empty when allowed.
    reasons: list[ProgressMessageOut]
    # Cautions that apply; when allowed, they must be acknowledged (``acknowledge``).
    warnings: list[ProgressMessageOut]
    acknowledge: list[str]
    # Labels of answers that are missing or "Not sure" behind a refusal.
    missing: list[str]


class PathwayOptionOut(BaseModel):
    key: str
    label: str
    description: str
    # False: recorded like any choice, but never opens a stage.
    unlocks_stages: bool
    current: bool
    # The transition recording this choice (None for the current choice).
    transition: TransitionOut | None


class PathwayChoiceOut(BaseModel):
    key: str
    label: str
    description: str
    decided_at: datetime
    by_viewer: bool
    previous: str | None


class StageOut(BaseModel):
    key: str
    title: str
    summary: str
    optional: bool
    terminal: bool
    status: Literal["completed", "in_progress", "next", "later"]


class ChecklistOptionOut(BaseModel):
    value: str
    label: str


class ChecklistQuestionOut(BaseModel):
    key: str
    prompt: str
    label: str
    help: str | None
    options: list[ChecklistOptionOut]


class ChecklistOut(BaseModel):
    """The stage in progress' checklist, saved through the step answers route."""

    step_key: str
    title: str
    intro: str
    questions: list[ChecklistQuestionOut]


class RulesOut(BaseModel):
    bundle: str
    version: str
    # "synthetic": fictional test rules (always announced as such).
    provenance: Literal["synthetic", "private"]
    notice: ProgressMessageOut | None


class GateOut(BaseModel):
    code: str
    title: str
    body: str


class EscalationRecordOut(BaseModel):
    """A recorded need for specialist review: unresolved (no release exists)."""

    transition: str
    label: str
    since: datetime


class AttemptOut(BaseModel):
    """What happened to the request this response answers."""

    request_key: UUID
    transition: str
    label: str
    outcome: Literal["applied", "rejected"]
    decision: DecisionOut
    title: str
    body: str


class ProgressHistoryItemOut(BaseModel):
    id: str
    kind: Literal[
        "pathway_selected",
        "stage_started",
        "stage_completed",
        "transition_rejected",
        "escalation_recorded",
    ]
    at: datetime
    by_viewer: bool
    title: str
    detail: str | None


class ProgressionOut(BaseModel):
    status: ProgressStatusOut
    # Applies to every transition (None: progression is open).
    gate: GateOut | None
    rules: RulesOut | None
    pathway: PathwayChoiceOut | None
    pathway_options: list[PathwayOptionOut]
    stages: list[StageOut]
    actions: list[TransitionOut]
    checklist: ChecklistOut | None
    escalations: list[EscalationRecordOut]
    not_available: list[str]
    history: list[ProgressHistoryItemOut]
    attempt: AttemptOut | None


def _message(result: RuleResult) -> ProgressMessageOut:
    if result.source == "engine":
        title, body = GATE_TEXT[result.rule]
    elif result.message is None:
        title, body = GATE_TEXT["information_needed"]
    else:
        title, body = result.message.title, result.message.body
    action: Literal["warn", "block", "escalate"] = (
        "block"
        if result.action == "block"
        else "escalate"
        if result.action == "escalate"
        else "warn"
    )
    return ProgressMessageOut(
        code=result.rule,
        action=action,
        source=result.source,
        title=title,
        body=body,
        provisional=result.provisional,
    )


def transition_out(
    spec: ProgressionSpec,
    evaluation: ProgressionEvaluation,
    transition: TransitionEvaluation,
    labels: Mapping[str, str],
) -> TransitionOut:
    fired = transition.fired
    gated = evaluation.gate is not None
    if gated:
        # A gate on the whole Case: only its explanation (and a recorded
        # escalation), no other guidance.
        fired = tuple(r for r in fired if r.rule in (evaluation.gate, "earlier_escalation"))
    reasons = [_message(r) for r in fired if r.action in ("block", "escalate")]
    warnings = [_message(r) for r in fired if r.action == "warn"]
    return TransitionOut(
        key=transition.key,
        kind=transition.kind,
        label=label_for(spec, evaluation.program, transition),
        decision=transition.decision,
        allowed=transition.allowed,
        reasons=reasons,
        warnings=warnings,
        acknowledge=list(transition.warnings),
        missing=[] if gated else [labels.get(key, "An answer") for key in transition.missing],
    )


def _options(options: Sequence[Option]) -> list[ChecklistOptionOut]:
    return [ChecklistOptionOut(value=o.value, label=o.label) for o in options]


def _first_escalations(
    events: Sequence[StoredEvent],
) -> list[StoredEvent]:
    first: dict[str, StoredEvent] = {}
    for event in events:  # causal order
        if event.kind == "escalation_recorded" and event.transition not in first:
            first[event.transition] = event
    return list(first.values())


def attempt_out(
    spec: ProgressionSpec, program: JurisdictionProgram | None, event: StoredEvent
) -> AttemptOut:
    kind, _, target = event.transition.partition(":")
    label = transition_label(spec, program, kind, target)
    applied = event.kind != "transition_rejected"
    if applied:
        title, body = "Recorded", f"{label}. This is recorded in the case history."
    elif event.decision == "escalate":
        title = "Not allowed: specialist review needed"
        body = (
            f"{label} needs specialist review first, so the case didn't move on. This is "
            "recorded in the case history."
        )
    else:
        title = "Not allowed"
        body = f"{label} isn't allowed right now, so the case didn't move on."
    return AttemptOut(
        request_key=event.request_key or UUID(int=0),
        transition=event.transition,
        label=label,
        outcome="applied" if applied else "rejected",
        decision=event.decision,
        title=title,
        body=body,
    )


def progression_out(
    spec: ProgressionSpec,
    evaluation: ProgressionEvaluation,
    events: Sequence[StoredEvent],
    labels: Mapping[str, str],
    *,
    viewer_user_id: UUID,
    attempt: StoredEvent | None = None,
) -> ProgressionOut:
    bundle = evaluation.bundle
    program = evaluation.program
    gate = evaluation.gate
    by_key = {t.key: t for t in evaluation.pathway_transitions}
    selections = [e for e in events if e.kind == "pathway_selected"]
    latest = max(selections, key=lambda e: e.revision, default=None)
    current = None if latest is None or latest.pathway is None else spec.pathway(latest.pathway)
    checklist_step = evaluation.checklist_step
    active = evaluation.active_stage
    return ProgressionOut(
        status=ProgressStatusOut(code=evaluation.status, label=STATUS_LABELS[evaluation.status]),
        gate=None
        if gate is None
        else GateOut(code=gate, title=GATE_TEXT[gate][0], body=GATE_TEXT[gate][1]),
        rules=None
        if bundle is None
        else RulesOut(
            bundle=bundle.bundle_id,
            version=bundle.version,
            provenance=bundle.provenance,
            notice=None
            if bundle.notice is None
            else ProgressMessageOut(
                code="rules_notice",
                action="warn",
                source="bundle",
                title=bundle.notice.title,
                body=bundle.notice.body,
                provisional=bundle.provenance == "synthetic",
            ),
        ),
        pathway=None
        if latest is None or current is None
        else PathwayChoiceOut(
            key=current.key,
            label=current.label,
            description=current.description,
            decided_at=latest.occurred_at,
            by_viewer=latest.actor_user_id == viewer_user_id,
            previous=None
            if latest.previous_pathway is None
            else (spec.pathway(latest.previous_pathway) or current).label,
        ),
        pathway_options=[]
        if bundle is None
        else [
            PathwayOptionOut(
                key=option.key,
                label=option.label,
                description=option.description,
                unlocks_stages=option.unlocks_stages,
                current=current is not None and option.key == current.key,
                transition=None
                if (t := by_key.get(f"pathway:{option.key}")) is None
                else transition_out(spec, evaluation, t, labels),
            )
            for option in spec.pathways
        ],
        stages=[
            StageOut(
                key=stage.key,
                title=stage.title,
                summary=stage.summary,
                optional=stage.optional,
                terminal=stage.terminal,
                status=status,
            )
            for stage, status in evaluation.stages
        ],
        actions=[transition_out(spec, evaluation, t, labels) for t in evaluation.stage_transitions],
        checklist=None
        if checklist_step is None or active is None
        else ChecklistOut(
            step_key=checklist_step.key,
            title=active.title,
            intro=active.summary,
            questions=[
                ChecklistQuestionOut(
                    key=item.fact_key,
                    prompt=item.prompt,
                    label=item.label,
                    help=item.help,
                    options=_options(item.options),
                )
                for item in active.checklist
            ],
        ),
        escalations=[
            EscalationRecordOut(
                transition=event.transition,
                label=transition_label(spec, program, *event.transition.split(":", 1)),
                since=event.occurred_at,
            )
            for event in _first_escalations(events)
        ],
        not_available=list(spec.not_available),
        history=[
            ProgressHistoryItemOut(
                id=item.id,
                kind=item.kind,
                at=item.at,
                by_viewer=item.by_viewer,
                title=item.title,
                detail=item.detail,
            )
            for item in compose_progress_history(
                spec, program, events, viewer_user_id=viewer_user_id
            )
        ],
        attempt=None if attempt is None else attempt_out(spec, program, attempt),
    )
