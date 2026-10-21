"""The generic, deterministic conversation evaluator (pure: no I/O, no clock, no randomness).

``ConversationEvaluationService.evaluate(snapshot, request)`` gives the same
``ConversationEvaluation`` for the same snapshot, trusted facts, requested
actions and two-state answers, every time. It knows no workflow by name: what
a workflow's Conditions, decisions and rules are comes from its approved
knowledge, its definition, its rule bundle and its execution profile.

Per turn, in order:

1. **Matter.** Another HR matter HeroOS's approved content doesn't cover is
   a specialist-review requirement for the matter; a request outside HeroOS's
   scope gets no outcome at all.
2. **Availability.** No compatible execution for the workflow: a technical
   state with no business outcome (never a fake Block or Expert Review).
3. **Jurisdiction gate.** The Blueprint's confirmed jurisdiction, made less
   certain (never more) by the conversation: the AI noticing another employer
   (``conversation_conflict``) or the founder's trusted answer about this
   employee (``case_different`` escalates, ``case_not_sure`` blocks). While it
   is unresolved, no jurisdiction-specific step gets a jurisdiction-specific
   result; shared guidance continues.
4. **Conditions**, narrowly (the topics raised, the decisions asked about):
   only ENGINE_TRUSTED facts enter a bound rule. Three-valued logic: an
   unknown input never becomes false; an escalating rule whose inputs are
   unknown holds the step for missing information instead of recording an
   escalation. A two-state Condition takes its stronger action only once the
   employer has explicitly insisted (ENGINE_TRUSTED), or, when trusted state
   was lost, until they confirm again.
5. **Actions**, each on its own: the approved availability (review required
   -> escalate; not available -> block), its mandatory-prerequisite rules,
   the Conditions linked to it, and its coverage. A safeguard that can't be
   evaluated keeps the step ``unknown``, never clear.
6. **Presentation** by fixed precedence over the requested steps and the
   matter-level cautions: ESCALATE > BLOCK > UNKNOWN > WARN > ALLOW, mapped to
   Expert Review, Block, Warning, Warning, Guidance. Ordinary missing context
   with nothing requested is Guidance with a question, never a Block.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from app.evaluation.facts import candidate
from app.evaluation.model import (
    PRESENTATIONS,
    ActionEvaluation,
    Caution,
    ConditionEvaluation,
    ConversationEvaluation,
    Disposition,
    FollowUpState,
    JurisdictionState,
    Matter,
    MissingRequirement,
    NextStep,
    Note,
    ReviewRequirement,
    TrustedFactState,
    TwoState,
    strongest,
)
from app.evaluation.snapshot import (
    BoundRule,
    ExecutionRuntime,
    ExecutionSnapshot,
    WorkflowExecution,
)
from app.knowledge.bundle import Condition
from app.workflows.conditions import Tri
from app.workflows.definition import NOT_SURE

# The jurisdiction gate's action per unresolved state (the routing precondition's
# action, and its specialist-review alternate when the employee is employed elsewhere).
GATE: Final[Mapping[JurisdictionState, Disposition]] = {
    "company_unconfirmed": "block",
    "conversation_conflict": "block",
    "case_not_sure": "block",
    "case_different": "escalate",
}
INSISTENCE: Final = "insistence"
JURISDICTION: Final = "jurisdiction"
MAX_TWO_STATE: Final = 8


@dataclass(frozen=True, slots=True)
class EvaluationRequest:
    matter: Matter
    workflow: str | None = None
    # The Blueprint's operator-confirmed employment jurisdiction, while guidance is allowed.
    company_jurisdiction: str | None = None
    # The AI noticed the founder's words point to another employer (tightening only).
    jurisdiction_conflict: bool = False
    # The founder's trusted answer about this employee: confirmed, different or not_sure.
    clarification: str | None = None
    facts: TrustedFactState = field(default_factory=TrustedFactState)
    # Requested employer decisions (option ids, validated against the catalog).
    requested: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    two_state: Mapping[str, TwoState] = field(default_factory=dict)
    reconfirm: bool = False
    multiple_matters: bool = False
    pathway_candidate: str | None = None
    # Candidates the founder declined this turn.
    declined: frozenset[str] = frozenset()


def _jurisdiction(
    execution: WorkflowExecution, request: EvaluationRequest
) -> tuple[JurisdictionState, str | None]:
    company = request.company_jurisdiction
    if company is None or company not in execution.jurisdictions:
        return "company_unconfirmed", None
    if request.clarification == "different":
        return "case_different", None
    if request.clarification == "not_sure":
        return "case_not_sure", None
    if request.clarification != "confirmed" and request.jurisdiction_conflict:
        return "conversation_conflict", None
    return "resolved", company


def _answers(execution: WorkflowExecution, facts: TrustedFactState) -> dict[str, object]:
    """ENGINE_TRUSTED values, by knowledge fact key and by definition question key."""
    answers: dict[str, object] = {}
    for key, value in facts.engine.items():
        answers[key] = value
        schema = execution.schemas.get(key)
        if schema is not None and schema.question is not None:
            answers[schema.question] = value
    return answers


def _note(condition: Condition, jurisdiction: str | None) -> Note:
    scopes = {"shared", "global"} | ({jurisdiction} if jurisdiction else set())
    text = (
        ()
        if condition.guidance_status == "withheld"
        else tuple(s.text for s in condition.segments if s.scope in scopes)
    )
    return Note(condition.title, text, not condition.legal_basis_confirmed)


@dataclass(frozen=True, slots=True)
class _Result:
    status: str
    action: str | None
    follow_up: FollowUpState
    missing: tuple[str, ...]
    reasons: tuple[str, ...]


def _run(
    rule: BoundRule,
    execution: WorkflowExecution,
    answers: Mapping[str, object],
    two_state: Mapping[str, TwoState],
    reconfirm: bool,
) -> _Result:
    """One bound rule on the trusted answers (three-valued; unknown never clears)."""
    truth = rule.truth(answers)
    missing = tuple(dict.fromkeys(execution.fact_key(k) for k in rule.unknown(answers)))
    if truth is Tri.FALSE:
        return _Result("not_fired", None, "not_applicable", (), ("not_met",))
    if truth is Tri.UNKNOWN:
        # Fires all the same; an escalation needs its condition met, so it holds for
        # missing information instead of being recorded.
        action = "block" if rule.action == "escalate" else rule.action
        return _Result("unknown", action, "not_applicable", missing, ("unknown_inputs",))
    if rule.follow_up_when == "employer_insists":
        state = two_state.get(rule.key)
        # Not stated yet: the caution comes first. Lost with the trusted state: unknown.
        insists = state.insists if state is not None else (Tri.UNKNOWN if reconfirm else Tri.FALSE)
        if insists is Tri.TRUE:
            return _Result(
                "fired", rule.follow_up_action, "applied", (), ("met", "employer_insists")
            )
        if insists is Tri.UNKNOWN:
            # Trusted state was lost: the stronger action holds until the founder confirms.
            return _Result("fired", rule.follow_up_action, "reconfirm", (), ("met", "reconfirm"))
        return _Result("fired", rule.action, "pending", (), ("met",))
    if rule.follow_up_when == "condition_specific" and rule.follow_up_truth is not None:
        follow = rule.follow_up_truth(answers)
        if follow is Tri.TRUE:
            return _Result("fired", rule.follow_up_action, "applied", (), ("met", "follow_up_met"))
        if follow is Tri.UNKNOWN:
            held = "block" if rule.follow_up_action == "escalate" else rule.follow_up_action
            extra = tuple(dict.fromkeys(k for k in rule.reads if k not in answers))
            return _Result("fired", held, "applied", extra, ("met", "follow_up_unknown"))
    return _Result("fired", rule.action, "not_applicable", (), ("met",))


def _condition(
    execution: WorkflowExecution,
    condition: Condition,
    jurisdiction: str | None,
    answers: Mapping[str, object],
    request: EvaluationRequest,
) -> ConditionEvaluation:
    category = execution.categories[condition.id]
    linked = (
        ()
        if jurisdiction is None
        else execution.condition_options.get((condition.id, jurisdiction), ())
    )
    provisional = not condition.legal_basis_confirmed
    rule = None if jurisdiction is None else execution.bound.get((condition.id, jurisdiction))
    if category != "executable" or rule is None:
        reason = category if jurisdiction is not None or condition.scope == "global" else (
            "jurisdiction_unresolved"
        )  # fmt: skip
        return ConditionEvaluation(
            condition.id, category, "not_evaluated", condition.action_policy.initial, None,
            "not_applicable", (reason,), (), provisional, linked,
        )  # fmt: skip
    incapable = execution.incapable.get(condition.id)
    if incapable is not None:
        # Never collected here (privacy) or never collectable: unavailable, never a result.
        return ConditionEvaluation(
            condition.id, category, "unavailable", condition.action_policy.initial, None,
            "not_applicable", (incapable,), (), provisional, linked,
        )  # fmt: skip
    result = _run(rule, execution, answers, request.two_state, request.reconfirm)
    return ConditionEvaluation(
        condition.id, category, result.status, condition.action_policy.initial,  # type: ignore[arg-type]
        result.action, result.follow_up, result.reasons, result.missing, provisional, linked,
    )  # fmt: skip


def _relevant(
    execution: WorkflowExecution, request: EvaluationRequest, jurisdiction: str | None
) -> list[Condition]:
    """Only this matter's Conditions: the topics raised and the decisions asked about."""
    topics = set(request.topics)
    linked = {
        c
        for a in request.requested
        for c in (
            () if jurisdiction is None else execution.option_conditions.get((a, jurisdiction), ())
        )
    }
    scopes = {"shared", "global"} | ({jurisdiction} if jurisdiction else set())
    return [
        c
        for c in execution.conditions.values()
        if c.scope in scopes and (c.id in linked or bool(topics & set(c.topics)))
    ]


def _action(
    execution: WorkflowExecution,
    action: str,
    state: JurisdictionState,
    jurisdiction: str | None,
    answers: Mapping[str, object],
    conditions: Mapping[str, ConditionEvaluation],
    request: EvaluationRequest,
) -> ActionEvaluation:
    option = execution.options[action]
    results: list[tuple[Disposition, str]] = []
    missing: list[str] = []
    notes: list[Note] = []
    provisional = False
    review_reasons: list[str] = []
    if jurisdiction is None:
        gate = GATE[state]
        results.append((gate, f"jurisdiction:{state}"))
        if gate == "escalate":
            review_reasons.append("jurisdiction_different")
        else:
            missing.append(JURISDICTION)
        linked: tuple[str, ...] = ()
    else:
        entry = option.jurisdictions[jurisdiction]
        availability = entry.availability
        reason = entry.reason
        if ("option", option.id) in execution.quarantined:
            availability, reason = "review_required", "quarantined"
        if availability == "review_required":
            results.append(("escalate", f"review_required:{reason}"))
            review_reasons.append(reason)
        elif availability == "not_available":
            results.append(("block", f"not_available:{reason}"))
        for rule in execution.action_rules.get((action, jurisdiction), ()):
            outcome = _run(rule, execution, answers, request.two_state, request.reconfirm)
            if outcome.status == "not_fired" or outcome.action is None:
                continue
            results.append((outcome.action, f"rule:{rule.key}"))  # type: ignore[arg-type]
            missing += outcome.missing
            provisional |= rule.provisional
            if rule.note is not None:
                notes.append(rule.note)
        linked = execution.option_conditions.get((action, jurisdiction), ())
        for condition_id in linked:
            evaluation = conditions.get(condition_id)
            if evaluation is None:
                continue
            condition = execution.conditions[condition_id]
            if evaluation.category in ("question_only", "quarantined"):
                results.append(("unknown", f"not_executable:{condition_id}"))
            elif evaluation.status == "unavailable":
                results.append(("unknown", f"{evaluation.reasons[0]}:{condition_id}"))
            elif evaluation.status in ("fired", "unknown") and evaluation.action is not None:
                results.append((evaluation.action, f"condition:{condition_id}"))  # type: ignore[arg-type]
                missing += evaluation.missing
                provisional |= evaluation.provisional
                if evaluation.status == "fired":
                    notes.append(_note(condition, jurisdiction))
                if evaluation.action == "escalate":
                    review_reasons.append(f"condition:{condition_id}")
        if action not in execution.covered:
            results.append(("unknown", "action_not_covered"))
    disposition = strongest([d for d, _ in results])
    review = (
        ReviewRequirement(True, "action", action, tuple(dict.fromkeys(review_reasons)))
        if disposition == "escalate"
        else None
    )
    unique_missing = tuple(dict.fromkeys(missing))
    return ActionEvaluation(
        action=action,
        title=option.title,
        disposition=disposition,
        reasons=tuple(dict.fromkeys(r for _, r in results)),
        missing=unique_missing,
        provisional=provisional,
        review=review,
        next_step=_next_step(disposition, unique_missing),
        conditions=linked,
        notes=tuple(dict.fromkeys(notes)),
    )


def _next_step(disposition: Disposition, missing: tuple[str, ...]) -> NextStep:
    if disposition == "escalate":
        return "obtain_specialist_review"
    if disposition == "block":
        return "confirm_jurisdiction" if JURISDICTION in missing else "establish_prerequisite"
    if disposition == "unknown":
        return "establish_prerequisite"
    if disposition == "warn":
        return "consider_caution"
    return "answer_question" if missing else "continue_methodology"


def _requirements(
    execution: WorkflowExecution,
    request: EvaluationRequest,
    state: JurisdictionState,
    jurisdiction: str | None,
    actions: tuple[ActionEvaluation, ...],
    conditions: tuple[ConditionEvaluation, ...],
) -> tuple[MissingRequirement, ...]:
    """What must be established, in order: jurisdiction, insistence, the steps' facts, the rest."""
    found: list[MissingRequirement] = []
    seen: set[str] = set()
    requested = tuple(a.action for a in actions)
    if state in ("conversation_conflict", "case_not_sure", "company_unconfirmed"):
        found.append(
            MissingRequirement(JURISDICTION, "jurisdiction", "employment jurisdiction", requested)
        )
        seen.add(JURISDICTION)
    for evaluation in conditions:
        rule = None if jurisdiction is None else execution.bound.get(
            (evaluation.condition, jurisdiction)
        )  # fmt: skip
        if rule is None or evaluation.follow_up not in ("pending", "reconfirm"):
            continue
        key = f"{INSISTENCE}:{rule.key}"
        if key not in seen:
            seen.add(key)
            title = execution.conditions[evaluation.condition].title
            holding = tuple(a for a in evaluation.linked_actions if a in requested)
            found.append(MissingRequirement(key, "insistence", title, holding))
    keys = [k for a in actions for k in a.missing] + [k for c in conditions for k in c.missing]
    for key in keys:
        schema = execution.schemas.get(key)
        if key in seen or schema is None or schema.kind == "blueprint":
            continue
        if request.facts.engine.get(key) == NOT_SURE:
            continue  # answered "not sure": the founder must find out, not be asked again
        holding = tuple(a.action for a in actions if key in a.missing)
        if not holding and key in request.facts.conversational:
            # Already said: the conversation reuses it. Confirmation is only ever asked
            # for what a requested step's deterministic decision needs.
            continue
        seen.add(key)
        value = None if key in request.declined else candidate(schema, request.facts)
        found.append(
            MissingRequirement(
                key, "confirmation" if value is not None else "fact", schema.label, holding, value
            )
        )
    return tuple(found)


def _two_state(
    execution: WorkflowExecution,
    request: EvaluationRequest,
    conditions: tuple[ConditionEvaluation, ...],
    jurisdiction: str | None,
) -> tuple[TwoState, ...]:
    states = dict(request.two_state)
    for evaluation in conditions:
        rule = None if jurisdiction is None else execution.bound.get(
            (evaluation.condition, jurisdiction)
        )  # fmt: skip
        if rule is None or rule.follow_up_when != "employer_insists":
            continue
        if evaluation.status == "fired":
            previous = states.get(rule.key)
            insists = (
                previous.insists
                if previous is not None
                else (Tri.UNKNOWN if request.reconfirm else Tri.FALSE)
            )
            acknowledged = previous.acknowledged if previous is not None else False
            states[rule.key] = TwoState(rule.key, True, acknowledged, insists)
    return tuple(sorted(states.values(), key=lambda s: s.rule))[:MAX_TWO_STATE]


class ConversationEvaluationService:
    """The one entry point the Ask HeroOS gateway depends on (workflow-neutral)."""

    def __init__(self, runtime: ExecutionRuntime) -> None:
        self._runtime = runtime

    def snapshot(self) -> ExecutionSnapshot:
        """The snapshot a whole founder turn uses (taken once, at its start)."""
        return self._runtime.current()

    def evaluate(
        self, snapshot: ExecutionSnapshot, request: EvaluationRequest
    ) -> ConversationEvaluation:
        return evaluate_conversation(snapshot, request)


def evaluate_conversation(
    snapshot: ExecutionSnapshot, request: EvaluationRequest
) -> ConversationEvaluation:
    """The deterministic evaluation of one founder turn (pure)."""
    if request.matter == "unsupported_hr":
        review = ReviewRequirement(True, "matter", None, ("unsupported_hr",))
        return ConversationEvaluation(
            availability="ready", matter="unsupported_hr", reviews=(review,),
            presentation="expert_review", next_step="seek_specialist_advice",
        )  # fmt: skip
    if request.matter != "supported" or request.workflow is None:
        return ConversationEvaluation(availability="ready", matter=request.matter)
    execution = snapshot.execution(request.workflow)
    if execution is None:
        return ConversationEvaluation(
            availability=snapshot.availability(request.workflow),
            matter="supported",
            workflow=request.workflow,
            facts=request.facts,
            pathway_candidate=request.pathway_candidate,
        )

    state, jurisdiction = _jurisdiction(execution, request)
    answers = _answers(execution, request.facts)
    requested = tuple(a for a in dict.fromkeys(request.requested) if a in execution.options)
    relevant = _relevant(execution, request, jurisdiction)
    conditions = tuple(_condition(execution, c, jurisdiction, answers, request) for c in relevant)
    by_id = {c.condition: c for c in conditions}
    actions = tuple(
        _action(execution, a, state, jurisdiction, answers, by_id, request) for a in requested
    )

    # The matter's own cautions: what fired on trusted facts. A Condition guarding a
    # decision nobody asked for is a caution, never a hold on the whole conversation.
    cautions: list[Caution] = []
    contributions: list[Disposition] = [a.disposition for a in actions]
    for evaluation in conditions:
        if evaluation.status != "fired" or evaluation.action is None:
            continue
        condition = execution.conditions[evaluation.condition]
        rule = execution.bound.get((condition.id, jurisdiction or ""))
        two_state = rule is not None and rule.follow_up_when == "employer_insists"
        cautions.append(Caution(condition.id, _note(condition, jurisdiction), two_state,
                                evaluation.action))  # fmt: skip
        if evaluation.linked_actions:
            contributions.append("warn")
        else:
            contributions.append(evaluation.action)  # type: ignore[arg-type]
    reviews = tuple(a.review for a in actions if a.review is not None)
    matter_escalations = [
        c.condition
        for c in conditions
        if c.status == "fired" and c.action == "escalate" and not c.linked_actions
    ]
    if matter_escalations:
        reasons = tuple(f"condition:{c}" for c in matter_escalations)
        reviews += (ReviewRequirement(True, "matter", None, reasons),)
    if jurisdiction is None and not actions and state == "case_different":
        contributions.append("escalate")
        reviews += (ReviewRequirement(True, "matter", None, ("jurisdiction_different",)),)

    missing = _requirements(execution, request, state, jurisdiction, actions, conditions)
    disposition = strongest(contributions)
    presentation = PRESENTATIONS[disposition]
    next_step: NextStep
    if request.multiple_matters:
        next_step = "choose_matter"
    elif disposition == "allow":
        next_step = "answer_question" if missing else "continue_methodology"
    elif disposition == "warn" and any(m.kind == "insistence" for m in missing):
        next_step = "consider_caution"
    else:
        next_step = _next_step(disposition, tuple(m.key for m in missing))
    return ConversationEvaluation(
        availability="ready",
        matter="supported",
        workflow=execution.workflow,
        jurisdiction=jurisdiction,
        jurisdiction_state=state,
        pathway_candidate=request.pathway_candidate,
        pathway_ownership=execution.profile.pathway_ownership,
        facts=request.facts,
        conditions=conditions,
        actions=actions,
        reviews=reviews,
        missing=missing,
        cautions=tuple(cautions),
        two_state=_two_state(execution, request, conditions, jurisdiction),
        presentation=presentation,
        next_step=next_step,
        multiple_matters=request.multiple_matters,
        provenance=execution.provenance,
    )
