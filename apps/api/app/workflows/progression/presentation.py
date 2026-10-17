"""Customer-facing wording for progression (generic, neutral, public).

Only the engine's own wording lives here: statuses, the engine gates, the
transition labels and the progression history. A bundle rule brings its own
(private) title and body. Nothing here assesses the incident or the employee,
recommends a step or describes a choice as legally validated, and nothing
promises an expert review that doesn't exist.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from app.workflows.progress import ProgressItem
from app.workflows.progression.bundle import JurisdictionProgram
from app.workflows.progression.engine import ProgressionEvaluation, Status, TransitionEvaluation
from app.workflows.progression.records import StoredEvent
from app.workflows.progression.spec import ProgressionSpec

NO_EXPERT_SERVICE: Final = (
    "HeroOS doesn't offer expert review in the app yet and hasn't contacted anyone about this case."
)

STATUS_LABELS: Final[Mapping[Status, str]] = {
    "unavailable": "Not available here",
    "incompatible": "Paused: the rules have changed",
    "held": "On hold: specialist review needed",
    "paused": "Paused: jurisdiction not confirmed",
    "intake_incomplete": "Waiting for the intake",
    "not_covered": "Not available for this jurisdiction",
    "awaiting_pathway": "Choose a pathway",
    "undetermined": "Pathway not determined",
    "pathway_not_covered": "Pathway not available",
    "ready": "Ready for the next stage",
    "in_stage": "Stage in progress",
    "no_further_stage": "No further stage available yet",
    "closed": "Workflow completed",
}

GATE_TEXT: Final[Mapping[str, tuple[str, str]]] = {
    "rules_unavailable": (
        "Workflow progression isn't available here",
        "The approved rules that guide the next stages aren't installed in this environment, "
        "so HeroOS can't offer any stage. Nothing has been assessed or decided. Your answers "
        "stay saved.",
    ),
    "rules_version_incompatible": (
        "Paused: the rules have changed",
        "This case was started under a version of the rules that this environment doesn't "
        "use. HeroOS won't continue it under different rules. Your answers and history stay "
        "saved.",
    ),
    "case_held": (
        "On hold: specialist review needed",
        "This case is held for specialist review, so no stage can be started or completed. "
        "Seek advice from an employment-law specialist before taking any disciplinary step. "
        f"{NO_EXPERT_SERVICE}",
    ),
    "jurisdiction_paused": (
        "Paused until the jurisdiction is confirmed",
        "No stage is available until the employment jurisdiction for this case is confirmed.",
    ),
    "intake_incomplete": (
        "Complete the intake first",
        "The next stages open only once the intake is recorded: every question answered and "
        "the safety screening completed with no high-risk factors. A screening that isn't "
        "enabled, isn't complete or has “Not sure” answers doesn't count as cleared.",
    ),
    "jurisdiction_not_covered": (
        "Not available for this jurisdiction yet",
        "HeroOS has no approved stages for this case's jurisdiction yet, so it won't guide the "
        "next steps, and it never uses another jurisdiction's rules instead. Seek specialist "
        "advice before taking any disciplinary step.",
    ),
    "pathway_not_covered": (
        "Not available for this pathway yet",
        "HeroOS has no approved stages for this pathway in this case's jurisdiction yet.",
    ),
    "pathway_unchanged": ("Already recorded", "This pathway is already your recorded choice."),
    "workflow_closed": (
        "Workflow completed",
        "The last stage of this workflow is complete, so no further step can be taken here. "
        "The history stays saved.",
    ),
    "stage_not_available": (
        "Not the next stage",
        "Stages follow a fixed order: only the next stages shown can be started. Stages can't "
        "be skipped by going straight to a later one.",
    ),
    "stage_already_completed": ("Already completed", "This stage is already complete."),
    "stage_in_progress": (
        "Another stage is in progress",
        "Complete the stage in progress before starting another one.",
    ),
    "stage_not_active": ("Not in progress", "Only the stage in progress can be completed."),
    "checklist_incomplete": (
        "Checklist not complete",
        "Answer every checklist question for this stage first.",
    ),
    "information_needed": (
        "More information needed",
        "This step depends on answers that are missing or “Not sure”. Answer them first.",
    ),
    "earlier_escalation": (
        "Specialist review needed",
        "This step was escalated for specialist review earlier. Changed answers don't release "
        "it, and HeroOS can't release it in the app yet. Seek advice from an employment-law "
        f"specialist. {NO_EXPERT_SERVICE}",
    ),
}

HistoryKind = Literal[
    "pathway_selected",
    "stage_started",
    "stage_completed",
    "transition_rejected",
    "escalation_recorded",
]


@dataclass(frozen=True, slots=True)
class ProgressHistoryItem:
    id: str
    kind: HistoryKind
    at: datetime
    by_viewer: bool
    title: str
    detail: str | None


def pathway_label(spec: ProgressionSpec, key: str | None) -> str:
    pathway = None if key is None else spec.pathway(key)
    return "an earlier choice" if pathway is None else pathway.label


def stage_title(program: JurisdictionProgram | None, key: str | None) -> str:
    stage = None if program is None or key is None else program.stage(key)
    return "a stage" if stage is None else stage.title


def transition_label(
    spec: ProgressionSpec, program: JurisdictionProgram | None, kind: str, target: str
) -> str:
    if kind == "pathway":
        return f"Record pathway: {pathway_label(spec, target)}"
    if kind == "start":
        return f"Start: {stage_title(program, target)}"
    return f"Mark complete: {stage_title(program, target)}"


def label_for(
    spec: ProgressionSpec, program: JurisdictionProgram | None, transition: TransitionEvaluation
) -> str:
    target = transition.pathway if transition.kind == "pathway" else transition.stage
    return transition_label(spec, program, transition.kind, target or "")


def _target(key: str) -> tuple[str, str]:
    kind, _, target = key.partition(":")
    return kind, target


def _rejection_detail(reasons: Sequence[Mapping[str, object]]) -> str:
    fired = [r for r in reasons if r.get("fired")]
    if any(r.get("action") == "escalate" for r in fired):
        return "Specialist review needed. The case didn't move on."
    gates = [r.get("rule") for r in fired if r.get("source") == "engine"]
    for gate in gates:
        if isinstance(gate, str) and gate in GATE_TEXT:
            return f"{GATE_TEXT[gate][0]}. The case didn't move on."
    return "A requirement wasn't met. The case didn't move on."


def compose_progress_history(
    spec: ProgressionSpec,
    program: JurisdictionProgram | None,
    events: Sequence[StoredEvent],
    *,
    viewer_user_id: UUID,
) -> list[ProgressHistoryItem]:
    """The progression timeline, oldest first (labels only; never an answer).

    ``events`` must be in causal order: by instance revision, the event that
    produced a revision before refusals and escalations decided at it.
    """
    items: list[ProgressHistoryItem] = []
    # ``events`` are in causal order (revision, then the event that produced it).
    for event in events:
        kind, target = _target(event.transition)
        label = transition_label(spec, program, kind, target)
        title: str
        detail: str | None = None
        if event.kind == "pathway_selected":
            title = f"Pathway recorded: {pathway_label(spec, event.pathway)} (your decision)"
            detail = (
                f"Changed from: {pathway_label(spec, event.previous_pathway)}. Earlier stages "
                "and answers stay in this history."
                if event.previous_pathway is not None
                else "Recorded as the employer's judgement. HeroOS didn't classify the incident."
            )
        elif event.kind == "stage_started":
            title = f"Stage started: {stage_title(program, event.stage)}"
        elif event.kind == "stage_completed":
            title = f"Stage completed: {stage_title(program, event.stage)}"
            count = len(event.acknowledged)
            if count:
                detail = f"{count} caution{'s' if count > 1 else ''} acknowledged."
        elif event.kind == "transition_rejected":
            title = f"Not allowed: {label}"
            detail = _rejection_detail(event.reasons)
        else:
            title = f"Specialist review needed: {label}"
            detail = f"Recorded when it first applied. {NO_EXPERT_SERVICE}"
        items.append(
            ProgressHistoryItem(
                f"progress:{event.id}",
                event.kind,
                event.occurred_at,
                event.actor_user_id == viewer_user_id,
                title,
                detail,
            )
        )
    return items


def progress_items(
    spec: ProgressionSpec, evaluation: ProgressionEvaluation
) -> list[ProgressItem] | None:
    """The progress list's pathway and stage items; None while no rules are installed."""
    if evaluation.status == "unavailable":
        return None
    label = STATUS_LABELS[evaluation.status]
    pathway = None if evaluation.state.pathway is None else spec.pathway(evaluation.state.pathway)
    if pathway is not None:
        chosen = ProgressItem("pathway", "Pathway", "completed", f"{pathway.label} (your decision)")
    elif evaluation.open:
        chosen = ProgressItem("pathway", "Pathway", "needs_information", "Not chosen yet")
    else:
        chosen = ProgressItem("pathway", "Pathway", "blocked", label)
    active = evaluation.active_stage
    upcoming = [stage for stage, status in evaluation.stages if status == "next"]
    if evaluation.status in ("closed", "no_further_stage"):
        stage = ProgressItem("stage", "Stages", "completed", label)
    elif not evaluation.open:
        stage = ProgressItem("stage", "Stages", "blocked", label)
    elif active is not None:
        stage = ProgressItem("stage", "Stages", "in_progress", active.title)
    elif upcoming:
        stage = ProgressItem("stage", "Stages", "needs_information", f"Next: {upcoming[0].title}")
    else:
        stage = ProgressItem("stage", "Stages", "blocked", label)
    later = ProgressItem(
        "later", "Not available yet", "coming_later", ", ".join(spec.not_available)
    )
    return [chosen, stage, later]
