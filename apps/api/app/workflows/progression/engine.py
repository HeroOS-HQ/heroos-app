"""The progression state machine (M2-03): position, transitions and decisions.

Pure and deterministic: the same rule bundle, intake evaluation, answers and
stored progress events always give the same evaluation. The backend is the
only authority: a client may *ask* for a transition, and the API applies it
only if this evaluation allows it.

**Position.** Derived from the append-only progress events, never stored as a
mutable snapshot: the employer's latest pathway choice, the stage in progress,
the stages completed (in order) and, once a terminal stage is completed, the
end of the workflow. A pathway change ends the stage in progress without
completing it; nothing earlier is erased.

**Transitions** are offered from the current position only:

- ``pathway:<key>`` records the employer's pathway choice (any pathway other
  than the current one, until the workflow ends);
- ``start:<stage>`` starts one of the next stages of the current pathway (its
  entry stages, or the successors of the stage completed last);
- ``complete:<stage>`` completes the stage in progress.

Anything else (a later stage, a stage of another pathway, a completed stage,
completing a stage that isn't in progress) is refused as not available from
the current position: that is how skipping is prevented.

**Decisions.** Every transition gets one decision from all its results, with a
fixed precedence: ESCALATE > BLOCK > WARN > ALLOW.

- ESCALATE: refused; the need for specialist review is recorded. Escalations
  are sticky per transition: once recorded they are never released by changed
  answers (no release exists yet).
- BLOCK: refused; the reasons say what is missing or why it isn't available.
  A rule whose inputs are unknown (unanswered or "Not sure") fires all the
  same; an escalating rule with unknown inputs blocks for missing information
  until they are known, and is never recorded as an escalation.
- WARN: allowed only when the employer acknowledges exactly the warnings shown.
  A warning never overrides a block or an escalation.
- ALLOW: no rule fired.

Engine gates apply before any bundle rule and to every transition: no
installed bundle, a bundle that doesn't serve the version this Case used, a
specialist-review hold or jurisdiction pause from the intake, an intake whose
gate is closed (a disabled or incomplete screening never counts as cleared),
or a jurisdiction the bundle doesn't cover (no rule of another jurisdiction
is ever used instead).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from app.workflows.conditions import Tri
from app.workflows.definition import Step
from app.workflows.intake import IntakeEvaluation
from app.workflows.progression import predicates
from app.workflows.progression.bundle import (
    BundleRule,
    JurisdictionProgram,
    Message,
    PathwayProgram,
    RuleBundle,
    Stage,
)
from app.workflows.progression.spec import ProgressionSpec

Decision = Literal["allow", "warn", "block", "escalate"]
TransitionKind = Literal["pathway", "start", "complete"]
EventKind = Literal[
    "pathway_selected", "stage_started", "stage_completed", "transition_rejected",
    "escalation_recorded",
]  # fmt: skip
APPLIED_KINDS: Final = ("pathway_selected", "stage_started", "stage_completed")
EVENT_KINDS: Final = (*APPLIED_KINDS, "transition_rejected", "escalation_recorded")
DECISIONS: Final = ("allow", "warn", "block", "escalate")
SEVERITY: Final[Mapping[str, int]] = {"allow": 0, "warn": 1, "block": 2, "escalate": 3}

Status = Literal[
    "unavailable",
    "incompatible",
    "held",
    "paused",
    "intake_incomplete",
    "not_covered",
    "awaiting_pathway",
    "undetermined",
    "pathway_not_covered",
    "ready",
    "in_stage",
    # Every stage the rules define so far is done, but the workflow isn't
    # closed: what comes next (e.g. an outcome decision) isn't available yet.
    "no_further_stage",
    "closed",
]
StageStatus = Literal["completed", "in_progress", "next", "later"]

# Engine gates: fixed codes with a fixed action (public, generic wording in
# app.workflows.progression.presentation).
GATES: Final[Mapping[str, Decision]] = {
    "rules_unavailable": "block",
    "rules_version_incompatible": "block",
    "case_held": "escalate",
    "jurisdiction_paused": "block",
    "intake_incomplete": "block",
    "jurisdiction_not_covered": "block",
    "pathway_not_covered": "block",
    "pathway_unchanged": "block",
    "workflow_closed": "block",
    "stage_not_available": "block",
    "stage_already_completed": "block",
    "stage_in_progress": "block",
    "stage_not_active": "block",
    "checklist_incomplete": "block",
    "earlier_escalation": "escalate",
}

# Keys: "pathway:<key>", "start:<stage>", "complete:<stage>".
MAX_TRANSITION_KEY: Final = 100


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """One stored progress event as the engine reads it (codes only)."""

    kind: EventKind
    transition: str
    pathway: str | None
    stage: str | None
    decision: Decision
    revision: int
    bundle_version: str


@dataclass(frozen=True, slots=True)
class ProgressState:
    pathway: str | None
    active: str | None
    # Completed stages, in the order they were completed.
    completed: tuple[str, ...]
    # The bundle version of the Case's latest progress event.
    bundle_version: str | None
    # Transitions with a recorded escalation (sticky).
    escalated: frozenset[str]


def derive_state(events: Sequence[ProgressEvent]) -> ProgressState:
    """The current position from the stored events (applied ones in revision order)."""
    pathway: str | None = None
    active: str | None = None
    completed: list[str] = []
    for event in sorted((e for e in events if e.kind in APPLIED_KINDS), key=lambda e: e.revision):
        if event.kind == "pathway_selected":
            pathway, active = event.pathway, None
        elif event.kind == "stage_started":
            active = event.stage
        elif event.stage is not None:
            completed.append(event.stage)
            active = None
    latest = max(events, key=lambda e: e.revision, default=None)
    return ProgressState(
        pathway=pathway,
        active=active,
        completed=tuple(completed),
        bundle_version=None if latest is None else latest.bundle_version,
        escalated=frozenset(e.transition for e in events if e.kind == "escalation_recorded"),
    )


@dataclass(frozen=True, slots=True)
class RuleResult:
    # A bundle rule key, or an engine gate code.
    rule: str
    source: Literal["engine", "bundle"]
    action: Decision
    fired: bool
    # met: the condition held; unknown_inputs: information missing or "Not
    # sure" (always fires); not_met: definitely not; gate: an engine gate.
    reason: Literal["met", "unknown_inputs", "not_met", "gate"]
    provisional: bool
    message: Message | None
    # Answers whose absence or uncertainty made the rule fire.
    unknown: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TransitionEvaluation:
    key: str
    kind: TransitionKind
    pathway: str | None
    stage: str | None
    decision: Decision
    results: tuple[RuleResult, ...]

    @property
    def allowed(self) -> bool:
        return self.decision in ("allow", "warn")

    @property
    def fired(self) -> tuple[RuleResult, ...]:
        return tuple(r for r in self.results if r.fired)

    @property
    def warnings(self) -> tuple[str, ...]:
        """The warnings an employer must acknowledge (only when nothing stronger fired)."""
        if self.decision != "warn":
            return ()
        return tuple(r.rule for r in self.fired if r.action == "warn")

    @property
    def missing(self) -> tuple[str, ...]:
        """Answers missing or uncertain behind the blocking or escalating results."""
        keys: list[str] = []
        for result in self.fired:
            if result.action in ("block", "escalate"):
                keys += [k for k in result.unknown if k not in keys]
        return tuple(keys)

    @property
    def gates(self) -> tuple[str, ...]:
        return tuple(r.rule for r in self.fired if r.source == "engine")

    @property
    def new_escalation(self) -> bool:
        """A bundle rule escalates it now (and it isn't recorded as escalated yet)."""
        return (
            any(r.source == "bundle" and r.action == "escalate" for r in self.fired)
            and "earlier_escalation" not in self.gates
        )


@dataclass(frozen=True, slots=True)
class ProgressionEvaluation:
    status: Status
    bundle: RuleBundle | None
    program: JurisdictionProgram | None
    state: ProgressState
    # The engine gate that applies to every transition, if any.
    gate: str | None
    pathway_program: PathwayProgram | None
    # The current pathway's stages and where each one stands.
    stages: tuple[tuple[Stage, StageStatus], ...]
    pathway_transitions: tuple[TransitionEvaluation, ...]
    stage_transitions: tuple[TransitionEvaluation, ...]
    # Every completed stage, in order (any pathway), with its bundle stage if known.
    completed: tuple[str, ...]

    @property
    def open(self) -> bool:
        """Progression is possible now (no engine gate applies to everything)."""
        return self.gate is None

    @property
    def active_stage(self) -> Stage | None:
        if self.program is None or self.state.active is None:
            return None
        return self.program.stage(self.state.active)

    @property
    def checklist_step(self) -> Step | None:
        """The checklist that can be answered now: the stage in progress, while open."""
        stage = self.active_stage
        if not self.open or stage is None or not stage.checklist:
            return None
        return stage.checklist_step()

    @property
    def transitions(self) -> tuple[TransitionEvaluation, ...]:
        return self.stage_transitions + self.pathway_transitions

    def transition(self, key: str) -> TransitionEvaluation | None:
        return next((t for t in self.transitions if t.key == key), None)


def _severity(decision: str) -> int:
    return SEVERITY[decision]


def _decide(results: Sequence[RuleResult]) -> Decision:
    fired = [r.action for r in results if r.fired]
    if not fired:
        return "allow"
    strongest = max(fired, key=_severity)
    return strongest


def _gate(code: str) -> RuleResult:
    return RuleResult(code, "engine", GATES[code], True, "gate", False, None)


def _bundle_results(rules: Sequence[BundleRule], context: predicates.Context) -> list[RuleResult]:
    results: list[RuleResult] = []
    for rule in rules:
        truth = predicates.evaluate(rule.trigger, context)
        if truth is Tri.FALSE:
            results.append(
                RuleResult(rule.key, "bundle", rule.action, False, "not_met", rule.provisional,
                           rule.message)
            )  # fmt: skip
            continue
        if truth is Tri.TRUE:
            results.append(
                RuleResult(rule.key, "bundle", rule.action, True, "met", rule.provisional,
                           rule.message)
            )  # fmt: skip
            continue
        # Unknown inputs: refused all the same (never a false negative). An
        # escalation needs its condition to be met, so until the answers are
        # known it blocks for missing information instead of being recorded.
        action: Decision = "block" if rule.action == "escalate" else rule.action
        results.append(
            RuleResult(
                rule.key,
                "bundle",
                action,
                True,
                "unknown_inputs",
                rule.provisional,
                None if rule.action == "escalate" else rule.message,
                predicates.unknown_keys(rule.trigger, context),
            )
        )
    return results


def _transition(
    key: str,
    kind: TransitionKind,
    pathway: str | None,
    stage: str | None,
    results: Sequence[RuleResult],
) -> TransitionEvaluation:
    return TransitionEvaluation(key, kind, pathway, stage, _decide(results), tuple(results))


def _global_gate(
    bundle: RuleBundle | None,
    state: ProgressState,
    intake: IntakeEvaluation,
) -> tuple[Status, str] | None:
    if bundle is None:
        return "unavailable", "rules_unavailable"
    if state.bundle_version is not None and not bundle.serves(state.bundle_version):
        return "incompatible", "rules_version_incompatible"
    if intake.hold is not None and intake.hold.kind == "specialist_review":
        return "held", "case_held"
    if intake.hold is not None:
        return "paused", "jurisdiction_paused"
    if not intake.next_stage_open:
        # A disabled, incomplete or "Not sure" screening never counts as cleared.
        return "intake_incomplete", "intake_incomplete"
    if bundle.program(intake.jurisdiction.jurisdiction) is None:
        return "not_covered", "jurisdiction_not_covered"
    return None


def _frontier(program: PathwayProgram, completed: Sequence[str]) -> tuple[str, ...]:
    """The stages that can start next: successors of the last completed one, or the entry."""
    own = [key for key in completed if any(s.key == key for s in program.stages)]
    if not own:
        candidates = program.entry
    else:
        last = next(s for s in program.stages if s.key == own[-1])
        candidates = last.next
    return tuple(key for key in candidates if key not in completed)


def transition_key(kind: TransitionKind, target: str) -> str:
    return f"{kind}:{target}"


def parse_transition_key(key: str) -> tuple[TransitionKind, str] | None:
    kind, separator, target = key.partition(":")
    if not separator or not target or len(key) > MAX_TRANSITION_KEY:
        return None
    if kind == "pathway":
        return "pathway", target
    if kind == "start":
        return "start", target
    if kind == "complete":
        return "complete", target
    return None


def evaluate_progression(
    spec: ProgressionSpec,
    bundle: RuleBundle | None,
    intake: IntakeEvaluation,
    answers: Mapping[str, object],
    events: Sequence[ProgressEvent],
) -> ProgressionEvaluation:
    """Where the Case stands and what each transition offered now would decide."""
    state = derive_state(events)
    if bundle is not None and bundle.workflow_key != spec.workflow_key:
        bundle = None
    gate = _global_gate(bundle, state, intake)
    # Nothing is evaluated against a bundle that doesn't serve this Case.
    usable = bundle is not None and (gate is None or gate[1] != "rules_version_incompatible")
    program = bundle.program(intake.jurisdiction.jurisdiction) if usable and bundle else None
    context = predicates.Context(answers, frozenset(state.completed))
    closed = program is not None and any(
        (stage := program.stage(key)) is not None and stage.terminal for key in state.completed
    )
    if gate is None and closed:
        gate = ("closed", "workflow_closed")

    def gated(results: list[RuleResult], key: str) -> list[RuleResult]:
        prefix = [] if gate is None else [_gate(gate[1])]
        if key in state.escalated:
            prefix.append(_gate("earlier_escalation"))
        return prefix + results

    pathway_transitions: list[TransitionEvaluation] = []
    if usable:
        for option in spec.pathways:
            if option.key == state.pathway:
                continue
            key = transition_key("pathway", option.key)
            results: list[RuleResult] = []
            if option.unlocks_stages and program is not None:
                selected = program.pathway(option.key)
                if selected is None:
                    results.append(_gate("pathway_not_covered"))
                else:
                    results += _bundle_results(selected.select_rules, context)
            pathway_transitions.append(
                _transition(key, "pathway", option.key, None, gated(results, key))
            )

    choice = None if state.pathway is None else spec.pathway(state.pathway)
    current = (
        None
        if program is None or choice is None or not choice.unlocks_stages
        else program.pathway(choice.key)
    )
    stage_transitions: list[TransitionEvaluation] = []
    stages: list[tuple[Stage, StageStatus]] = []
    active: str | None = None
    frontier: tuple[str, ...] = ()
    if current is not None:
        active = state.active if state.active in {s.key for s in current.stages} else None
        if active is not None:
            stage = next(s for s in current.stages if s.key == active)
            key = transition_key("complete", stage.key)
            results = []
            missing = tuple(i.fact_key for i in stage.checklist if answers.get(i.fact_key) is None)
            if missing:
                results.append(
                    RuleResult(
                        "checklist_incomplete", "engine", "block", True, "gate", False, None,
                        missing,
                    )
                )  # fmt: skip
            results += _bundle_results(stage.complete_rules, context)
            stage_transitions.append(
                _transition(key, "complete", current.pathway, stage.key, gated(results, key))
            )
        elif not closed:
            frontier = _frontier(current, state.completed)
            for target in frontier:
                stage = next(s for s in current.stages if s.key == target)
                key = transition_key("start", stage.key)
                results = _bundle_results(stage.start_rules, context)
                stage_transitions.append(
                    _transition(key, "start", current.pathway, stage.key, gated(results, key))
                )
        for stage in current.stages:
            status: StageStatus
            if stage.key in state.completed:
                status = "completed"
            elif stage.key == active:
                status = "in_progress"
            elif stage.key in frontier:
                status = "next"
            else:
                status = "later"
            stages.append((stage, status))

    status_code: Status
    if gate is not None:
        status_code = gate[0]
    elif choice is None:
        # No pathway chosen yet (or a stored choice this code doesn't know).
        status_code = "awaiting_pathway" if state.pathway is None else "pathway_not_covered"
    elif not choice.unlocks_stages:
        status_code = "undetermined"
    elif current is None:
        status_code = "pathway_not_covered"
    elif active is not None:
        status_code = "in_stage"
    elif not frontier:
        status_code = "no_further_stage"
    else:
        status_code = "ready"

    return ProgressionEvaluation(
        status=status_code,
        bundle=bundle,
        program=program,
        state=state,
        gate=None if gate is None else gate[1],
        pathway_program=current,
        stages=tuple(stages),
        pathway_transitions=tuple(pathway_transitions),
        stage_transitions=tuple(stage_transitions),
        completed=state.completed,
    )


def resolve_attempt(
    evaluation: ProgressionEvaluation, spec: ProgressionSpec, key: str
) -> TransitionEvaluation | None:
    """The decision for a requested transition; None if the key names nothing known.

    A known transition that isn't offered from the current position (skipping
    ahead, another pathway's stage, a completed stage, completing a stage that
    isn't in progress, choosing the current pathway again) is refused with
    the reason, never applied.
    """
    offered = evaluation.transition(key)
    if offered is not None:
        return offered
    parsed = parse_transition_key(key)
    if parsed is None:
        return None
    kind, target = parsed
    state = evaluation.state
    prefix = [] if evaluation.gate is None else [_gate(evaluation.gate)]
    if kind == "pathway":
        if spec.pathway(target) is None:
            return None
        # Offered for every other pathway: this is the current one.
        return _transition(key, kind, target, None, [*prefix, _gate("pathway_unchanged")])
    program = evaluation.program
    stage = None if program is None else program.stage(target)
    if stage is None:
        return None
    if kind == "start":
        if target in state.completed:
            reason = "stage_already_completed"
        elif state.active is not None and state.active != target:
            reason = "stage_in_progress"
        else:
            reason = "stage_not_available"
    else:
        reason = "stage_not_active"
    return _transition(key, kind, stage.pathway, target, [*prefix, _gate(reason)])
