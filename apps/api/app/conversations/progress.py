"""The Case's workflow position for Ask HeroOS (M2-NEW-08): read-only, from the Case's records.

Ask HeroOS and the Case's formal progression (M2-03) are one product with one
workflow authority, the progression engine (``app.workflows.progression``).
Each turn of a conversation with a Case reads the Case's authoritative position
again, never the AI's earlier words about it:

- ``CaseProgress`` is the deterministic evaluation's input: the stages the
  employer completed and the stage checklist answers they saved, under the
  jurisdiction the Case's progression runs under. An employer decision's
  prerequisite rule may read them (``app.evaluation``), so "the investigation
  is done" in the chat never satisfies one;
- the model's view (``case_progress``) is labels only: the recorded pathway
  (the employer's own judgement, never HeroOS's classification), the stage in
  progress, the stages completed and next, what the stage in progress still
  needs, what the company can do next in the Case and what isn't possible yet,
  and a transition the progression rules held for specialist review (the
  gateway adds the decisions whose Expert Review the conversation found, by
  title, from the turn's own snapshot). Never a stage key, a rule, a raw row,
  an answer value or the bundle itself;
- ``Position`` is the status's workflow-position dimension (``status``).

Nothing here writes. The employer chooses the pathway, starts and completes
stages and answers checklists through the Case's own controls (the progression
routes); the next turn reads what they recorded.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from app.assistant.gateway.service import CaseContext
from app.cases.mutation import CaseState
from app.conversations.checkpoint import Reviews
from app.evaluation.model import CHECKLIST_PREFIX, CaseProgress
from app.workflows.progression.engine import TransitionEvaluation
from app.workflows.progression.presentation import (
    GATE_TEXT,
    STATUS_LABELS,
    label_for,
    transition_label,
)

# Bounds on the view (input to a model, never a product rule).
MAX_ITEMS: Final = 12
MAX_REASONS: Final = 3
MAX_TEXT: Final = 160
EMPLOYER_OWNS: Final = (
    "Only the employer changes this, through the case's own controls (its Next steps). It "
    "can't be changed from the chat."
)
PATHWAY_OWNER: Final = (
    "Recorded by the employer as their own judgement. HeroOS didn't classify the conduct."
)
NO_PROGRESSION: Final = "Workflow stages aren't available for this case here."


@dataclass(frozen=True, slots=True)
class Position:
    """Where the Case's formal workflow stands: the employer's records, never the AI's words."""

    # The progression status code (awaiting_pathway, ready, in_stage...); "unavailable" if none.
    state: str
    label: str
    # The recorded pathway's label (the employer's decision); None: not chosen yet.
    pathway: str | None
    # The stage in progress, else the next stage that can start.
    stage: str | None
    stage_in_progress: bool
    # Case steps (transitions) the progression rules recorded as needing specialist review.
    held_steps: tuple[str, ...]


def _short(text: str) -> str:
    return text if len(text) <= MAX_TEXT else f"{text[: MAX_TEXT - 1].rstrip()}…"


def _progress(state: CaseState) -> CaseProgress:
    """The authoritative input: completed stages and checklist answers, per jurisdiction."""
    case = state.intake.jurisdiction
    jurisdiction = case.jurisdiction if case.resolved else None
    progression = state.progression
    program = None if progression is None else progression.program
    stages = (
        set()
        if program is None
        else {s.key for p in program.pathways for s in p.stages}  # this jurisdiction's only
    )
    completed = frozenset(
        () if progression is None else (k for k in progression.completed if k in stages)
    )
    checklist = {
        key: value
        for key, value in state.answers.items()
        if key.startswith(CHECKLIST_PREFIX) and isinstance(value, str)
    }
    return CaseProgress(jurisdiction=jurisdiction, completed=completed, checklist=checklist)


def _why(transition: TransitionEvaluation) -> list[str]:
    reasons: list[str] = []
    for result in transition.fired:
        if result.action not in ("block", "escalate"):
            continue
        if result.source == "engine":
            title = GATE_TEXT[result.rule][0]
        elif result.message is None:
            title = GATE_TEXT["information_needed"][0]
        else:
            title = result.message.title
        if title not in reasons:
            reasons.append(_short(title))
    return reasons[:MAX_REASONS]


def position(state: CaseState) -> Position:
    """The status's workflow-position dimension."""
    progression, spec = state.progression, state.spec
    if progression is None or spec is None or progression.status == "unavailable":
        return Position("unavailable", NO_PROGRESSION, None, None, False, ())
    recorded = (
        None if progression.state.pathway is None else spec.pathway(progression.state.pathway)
    )
    active = progression.active_stage
    upcoming = next((s for s, status in progression.stages if status == "next"), None)
    stage = active or upcoming
    return Position(
        state=progression.status,
        label=STATUS_LABELS[progression.status],
        pathway=None if recorded is None else recorded.label,
        stage=None if stage is None else stage.title,
        stage_in_progress=active is not None,
        held_steps=tuple(
            transition_label(spec, progression.program, *key.split(":", 1))
            for key in sorted(progression.state.escalated)
        )[:MAX_ITEMS],
    )


def case_context(state: CaseState, *, reviews: Reviews) -> CaseContext:
    """The Case's position for one turn: the evaluation's input and the model's view."""
    progress = _progress(state)
    progression, spec = state.progression, state.spec
    hold = state.intake.hold
    view: dict[str, object] = {
        "case_lifecycle": "paused: the whole matter is held for specialist review"
        if hold is not None and hold.kind == "specialist_review"
        else "in progress",
        "who_changes_it": EMPLOYER_OWNS,
    }
    signature: tuple[object, ...] = ("none",)
    if progression is not None and spec is not None and progression.status != "unavailable":
        program = progression.program
        recorded = (
            None if progression.state.pathway is None else spec.pathway(progression.state.pathway)
        )
        active = progression.active_stage
        completed = [stage.title for stage, status in progression.stages if status == "completed"]
        upcoming = [stage.title for stage, status in progression.stages if status == "next"]
        still_needed = (
            []
            if active is None
            else [i.label for i in active.checklist if state.answers.get(i.fact_key) is None]
        )
        allowed = [t for t in progression.stage_transitions if t.allowed]
        refused = [t for t in progression.stage_transitions if not t.allowed]
        view.update(
            {
                "workflow_status": STATUS_LABELS[progression.status],
                "pathway": None
                if recorded is None
                else {"label": recorded.label, "decided_by": PATHWAY_OWNER},
                "stage_in_progress": None if active is None else active.title,
                "stages_completed": completed[:MAX_ITEMS],
                "next_stages": upcoming[:MAX_ITEMS],
                "stage_still_needs": still_needed[:MAX_ITEMS],
                "company_can_do_now_in_case": [label_for(spec, program, t) for t in allowed][
                    :MAX_ITEMS
                ],
                "not_possible_yet_in_case": [
                    {"step": label_for(spec, program, t), "why": _why(t)}
                    for t in refused
                    if progression.gate is None  # a whole-workflow wait is said once, below
                ][:MAX_ITEMS],
                "held_for_specialist_review_in_case": list(position(state).held_steps),
            }
        )
        if progression.gate is not None:
            view["whole_workflow_waits_for"] = GATE_TEXT[progression.gate][0]
        if recorded is None and progression.gate is None:
            # The employer's choices, in HeroOS's neutral public wording (never a suggestion).
            view["pathway_choices_for_the_employer"] = [
                {"label": p.label, "meaning": p.description} for p in spec.pathways
            ]
        signature = (
            progression.status,
            progression.gate,
            progression.state.pathway,
            progression.state.active,
            progression.completed,
            tuple(upcoming),
            tuple(still_needed),
            tuple(sorted(progression.state.escalated)),
            tuple(t.key for t in allowed),
        )
    else:
        view["workflow_status"] = NO_PROGRESSION
    return CaseContext(
        progress=progress,
        view=view,
        texts=tuple(_texts(view)),
        signature=(*signature, view["case_lifecycle"]),
        reviews=reviews.actions,
        matter_review=reviews.matter,
    )


def _texts(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [t for item in value.values() for t in _texts(item)]
    if isinstance(value, list):
        return [t for item in value for t in _texts(item)]
    return []
