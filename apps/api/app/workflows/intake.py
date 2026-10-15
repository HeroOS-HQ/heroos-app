"""The Disciplinary intake evaluation (M2-02): routing, conditions, screening and holds.

Pure and deterministic: the same answers and the same Company jurisdiction
readiness always give the same evaluation. Nothing here reads free text,
infers a fact or decides anything for the employer.

Order of work (Conditions Library "Structural Findings" R11, and the routing
rule's own text: it runs ahead of every other condition):

1. ``JURISDICTION-ROUTING-001`` resolves the Case jurisdiction from the
   Company's operator-confirmed jurisdiction and the employer's confirmation
   for this Case. Missing, unclear, conflicting or unsupported -> no
   jurisdiction-specific condition runs (Implementation Rules §7, §17).
2. Only active conditions tagged with the resolved jurisdiction (or SHARED)
   are evaluated, in order. A UAE-FED rule never runs for a DIFC Case
   (Implementation Rules §4), and a jurisdiction without approved screening is
   held for specialist review rather than screened by another regime's rule.
3. The result: the screening state, at most one hold (``jurisdiction`` =
   paused until confirmed; ``specialist_review`` = escalated), the cautions to
   show, the missing and uncertain answers, and the Case status.

A high-risk answer holds the Case; it is never evidence about the employee. A
"Not sure" or a missing answer never clears the screening. Holds are internal:
no expert ticket is created and none is promised (Implementation Rules §18:
no staffed expert-review workflow exists yet).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from app.companies.jurisdiction import JurisdictionAssessment, JurisdictionReadiness
from app.db.models.company_blueprint import JURISDICTION_DIFC, JURISDICTION_UAE_FEDERAL
from app.workflows.conditions import (
    JURISDICTION_TAGS,
    ROUTING,
    RULESETS,
    Condition,
    RuleSet,
    Tri,
    evaluate,
    predicate_keys,
)
from app.workflows.definition import (
    CASE_JURISDICTION_KEY,
    JURISDICTION_DIFFERENT,
    NOT_SURE,
    Option,
    OptionsFrom,
    Question,
    Step,
    StepGate,
    WorkflowDefinition,
)

# Display names of the supported jurisdictions (same wording as onboarding).
JURISDICTION_LABELS: Final[Mapping[str, str]] = {
    JURISDICTION_UAE_FEDERAL: "UAE Federal (MOHRE)",
    JURISDICTION_DIFC: "DIFC",
}

JurisdictionStatus = Literal[
    "resolved",
    "company_unconfirmed",
    "company_unsupported",
    "awaiting_case_confirmation",
    "case_not_sure",
    "case_different",
    "case_confirmation_outdated",
]
Outcome = Literal["fired", "not_fired", "unknown", "not_applicable"]
Screening = Literal[
    "not_applicable", "not_started", "incomplete", "not_cleared", "cleared", "positive"
]
HoldKind = Literal["jurisdiction", "specialist_review"]
HoldReason = Literal[
    # specialist_review (escalate)
    "high_risk_factors",
    "jurisdiction_different",
    "jurisdiction_unsupported",
    "screening_not_covered",
    # jurisdiction (block: paused until confirmed)
    "company_jurisdiction_unconfirmed",
    "case_jurisdiction_not_sure",
    "case_jurisdiction_outdated",
]
Status = Literal[
    "case_created",
    "intake_in_progress",
    "awaiting_jurisdiction",
    "screening_not_cleared",
    "held_for_specialist_review",
    "intake_recorded",
]

STATUS_LABELS: Final[Mapping[Status, str]] = {
    "case_created": "Case created",
    "intake_in_progress": "Intake in progress",
    "awaiting_jurisdiction": "Awaiting jurisdiction confirmation",
    "screening_not_cleared": "Screening not cleared",
    "held_for_specialist_review": "On hold: specialist review needed",
    "intake_recorded": "Intake recorded",
}


@dataclass(frozen=True, slots=True)
class CaseJurisdiction:
    status: JurisdictionStatus
    # The resolved jurisdiction (only when ``status == "resolved"``).
    jurisdiction: str | None
    # The Company's confirmed jurisdiction, if confirmed and supported.
    company_jurisdiction: str | None
    # The employer's answer for this Case, as stored.
    case_answer: str | None

    @property
    def resolved(self) -> bool:
        return self.status == "resolved"


@dataclass(frozen=True, slots=True)
class ConditionResult:
    condition_id: str
    outcome: Outcome
    # The action taken when the condition fired; otherwise None.
    action: str | None
    # Why: a stable code (never free text).
    reason: str
    # The structured inputs the condition read (enumerated answers only).
    inputs: Mapping[str, str | None]
    # Fired cautions are shown unless a specialist-review hold is in force.
    shown: bool


@dataclass(frozen=True, slots=True)
class Hold:
    kind: HoldKind
    action: Literal["block", "escalate"]
    reason: HoldReason
    # The condition that placed the hold, and its review status.
    condition_id: str
    citation_status: str
    # high_risk_factors: the screening questions answered "Yes".
    factors: tuple[str, ...] = ()

    @property
    def provisional(self) -> bool:
        """Placed by a condition still under legal review (development content)."""
        return self.citation_status == "needs_legal_review"


@dataclass(frozen=True, slots=True)
class Caution:
    # The condition's notice key (stable, customer-safe; never the condition ID).
    notice: str
    condition_id: str
    citation_status: str


@dataclass(frozen=True, slots=True)
class IntakeEvaluation:
    definition_version: int
    ruleset_version: str
    ruleset_digest: str
    jurisdiction: CaseJurisdiction
    results: tuple[ConditionResult, ...]
    screening: Screening
    hold: Hold | None
    cautions: tuple[Caution, ...]
    status: Status
    available_steps: tuple[str, ...]
    # Questions asked now (available step and relevant), in definition order.
    asked: tuple[str, ...]
    missing: tuple[str, ...]
    # Asked questions answered "Not sure".
    uncertain: tuple[str, ...]

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def answered(self) -> int:
        return len(self.asked) - len(self.missing)

    @property
    def total(self) -> int:
        return len(self.asked)

    @property
    def next_stage_open(self) -> bool:
        """The gate later stages (classification, options) must check, server-side."""
        return self.status == "intake_recorded"


def ruleset_for(definition: WorkflowDefinition) -> RuleSet:
    return RULESETS[definition.key]


def resolve_jurisdiction(
    company: JurisdictionAssessment, answers: Mapping[str, object]
) -> CaseJurisdiction:
    """``JURISDICTION-ROUTING-001``: the Case jurisdiction, or why there is none.

    The Company Blueprint holds one operator-confirmed jurisdiction and no
    list of operating jurisdictions, so every Case asks the employer to
    confirm that this employee works under it. The answer is stored as the
    jurisdiction it confirmed: if the Company's confirmation later changes, the
    old answer no longer matches and must be given again. A Case can never
    select a jurisdiction the Company's confirmation does not support.
    """
    raw = answers.get(CASE_JURISDICTION_KEY)
    answer = raw if isinstance(raw, str) else None
    if company.readiness is JurisdictionReadiness.UNSUPPORTED:
        return CaseJurisdiction("company_unsupported", None, None, answer)
    if company.readiness is not JurisdictionReadiness.SUPPORTED_CONFIRMED or (
        company.jurisdiction not in JURISDICTION_TAGS
    ):
        return CaseJurisdiction("company_unconfirmed", None, None, answer)
    confirmed = company.jurisdiction
    if answer is None:
        return CaseJurisdiction("awaiting_case_confirmation", None, confirmed, None)
    if answer == confirmed:
        return CaseJurisdiction("resolved", confirmed, confirmed, answer)
    if answer == JURISDICTION_DIFFERENT:
        return CaseJurisdiction("case_different", None, confirmed, answer)
    if answer == NOT_SURE:
        return CaseJurisdiction("case_not_sure", None, confirmed, answer)
    return CaseJurisdiction("case_confirmation_outdated", None, confirmed, answer)


def question_options(question: Question, company: JurisdictionAssessment) -> tuple[Option, ...]:
    """The options of a question for this Company (built server-side when dynamic)."""
    if question.options_from is not OptionsFrom.COMPANY_JURISDICTION:
        return question.options
    confirmed = company.jurisdiction
    if not company.guidance_allowed or confirmed is None or confirmed not in JURISDICTION_LABELS:
        return ()
    return (
        Option(confirmed, f"Yes, {JURISDICTION_LABELS[confirmed]}"),
        Option(JURISDICTION_DIFFERENT, "No, a different jurisdiction applies"),
        Option(NOT_SURE, "Not sure"),
    )


def is_asked(question: Question, answers: Mapping[str, object]) -> bool:
    return (
        question.ask_when is None or answers.get(question.ask_when.key) in question.ask_when.values
    )


def step_available(
    step: Step, ruleset: RuleSet, company: JurisdictionAssessment, case: CaseJurisdiction
) -> bool:
    if step.gate is StepGate.COMPANY_JURISDICTION_CONFIRMED:
        return company.guidance_allowed and company.jurisdiction in JURISDICTION_TAGS
    if step.gate is StepGate.SCREENING_COVERED:
        return case.resolved and _screening_condition(ruleset, case) is not None
    return True


def _screening_condition(ruleset: RuleSet, case: CaseJurisdiction) -> Condition | None:
    if case.jurisdiction is None:
        return None
    condition_id = ruleset.screening_by_jurisdiction.get(JURISDICTION_TAGS[case.jurisdiction])
    return None if condition_id is None else ruleset.condition(condition_id)


def _inputs(condition: Condition, answers: Mapping[str, object]) -> dict[str, str | None]:
    if condition.predicate is None:
        return {}
    return {key: _text(answers.get(key)) for key in predicate_keys(condition.predicate)}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _routing_result(
    condition: Condition,
    ruleset: RuleSet,
    company: JurisdictionAssessment,
    case: CaseJurisdiction,
) -> ConditionResult:
    inputs = {
        "company.readiness": str(company.readiness),
        "company.reason": str(company.reason),
        "company.jurisdiction": company.jurisdiction,
        CASE_JURISDICTION_KEY: case.case_answer,
    }
    if case.status == "awaiting_case_confirmation":
        return ConditionResult(condition.id, "unknown", None, case.status, inputs, False)
    escalate = case.status in ("company_unsupported", "case_different")
    if not case.resolved:
        action = "escalate" if escalate else "block"
        return ConditionResult(condition.id, "fired", action, case.status, inputs, True)
    if _screening_condition(ruleset, case) is None:
        # Resolved, but no approved screening covers this jurisdiction: fail
        # safe to "escalate" (Structural Findings R25; Implementation Rules §17).
        return ConditionResult(
            condition.id, "fired", "escalate", "screening_not_covered", inputs, True
        )
    return ConditionResult(condition.id, "not_fired", None, "resolved", inputs, False)


def _screening_state(
    definition: WorkflowDefinition, available: bool, answers: Mapping[str, object]
) -> Screening:
    if not available:
        return "not_applicable"
    step = next(s for s in definition.steps if s.gate is StepGate.SCREENING_COVERED)
    values = [answers.get(q.key) for q in step.questions]
    if "yes" in values:
        return "positive"
    if all(value is None for value in values):
        return "not_started"
    if None in values:
        return "incomplete"
    return "not_cleared" if NOT_SURE in values else "cleared"


_ROUTING_HOLDS: Final[Mapping[JurisdictionStatus, tuple[HoldKind, HoldReason]]] = {
    "company_unconfirmed": ("jurisdiction", "company_jurisdiction_unconfirmed"),
    "case_not_sure": ("jurisdiction", "case_jurisdiction_not_sure"),
    "case_confirmation_outdated": ("jurisdiction", "case_jurisdiction_outdated"),
    "company_unsupported": ("specialist_review", "jurisdiction_unsupported"),
    "case_different": ("specialist_review", "jurisdiction_different"),
}


def evaluate_intake(
    definition: WorkflowDefinition,
    answers: Mapping[str, object],
    company: JurisdictionAssessment,
) -> IntakeEvaluation:
    """Evaluate the intake for the current answers and Company readiness."""
    ruleset = ruleset_for(definition)
    case = resolve_jurisdiction(company, answers)
    tag = JURISDICTION_TAGS.get(case.jurisdiction or "")

    results: list[ConditionResult] = []
    for condition in sorted(ruleset.conditions, key=lambda c: c.order):
        if condition.id == ROUTING:
            results.append(_routing_result(condition, ruleset, company, case))
            continue
        inputs = _inputs(condition, answers)
        if not condition.enforced:
            results.append(
                ConditionResult(condition.id, "not_applicable", None, "not_enforced", inputs, False)
            )
        elif tag is None or not condition.applies_to(tag):
            reason = "jurisdiction_unresolved" if tag is None else "other_jurisdiction"
            results.append(
                ConditionResult(condition.id, "not_applicable", None, reason, inputs, False)
            )
        else:
            assert condition.predicate is not None
            truth = evaluate(condition.predicate, answers)
            if truth is Tri.TRUE:
                results.append(
                    ConditionResult(condition.id, "fired", condition.action, "met", inputs, True)
                )
            elif truth is Tri.FALSE:
                results.append(
                    ConditionResult(condition.id, "not_fired", None, "not_met", inputs, False)
                )
            else:
                results.append(
                    ConditionResult(condition.id, "unknown", None, "unknown_inputs", inputs, False)
                )

    available = tuple(
        step.key for step in definition.steps if step_available(step, ruleset, company, case)
    )
    screening_available = any(
        s.gate is StepGate.SCREENING_COVERED and s.key in available for s in definition.steps
    )
    screening = _screening_state(definition, screening_available, answers)

    hold = _hold(definition, ruleset, case, results, answers)
    if hold is not None and hold.kind == "specialist_review":
        # No further self-service guidance while escalated: cautions are
        # recorded, not shown.
        results = [
            r
            if r.outcome != "fired" or r.action != "warn"
            else ConditionResult(r.condition_id, r.outcome, r.action, r.reason, r.inputs, False)
            for r in results
        ]
    cautions = tuple(
        Caution(c.notice, c.id, c.citation_status)
        for r in results
        for c in ruleset.conditions
        if c.id == r.condition_id and r.outcome == "fired" and r.action == "warn" and r.shown
    )

    asked = tuple(
        q.key
        for step in definition.steps
        if step.key in available
        for q in step.questions
        if is_asked(q, answers)
    )
    missing = tuple(key for key in asked if answers.get(key) is None)
    uncertain = tuple(key for key in asked if answers.get(key) == NOT_SURE)

    status = _status(hold, asked, missing, screening)
    return IntakeEvaluation(
        definition_version=definition.version,
        ruleset_version=ruleset.version,
        ruleset_digest=ruleset.digest,
        jurisdiction=case,
        results=tuple(results),
        screening=screening,
        hold=hold,
        cautions=cautions,
        status=status,
        available_steps=available,
        asked=asked,
        missing=missing,
        uncertain=uncertain,
    )


def _hold(
    definition: WorkflowDefinition,
    ruleset: RuleSet,
    case: CaseJurisdiction,
    results: list[ConditionResult],
    answers: Mapping[str, object],
) -> Hold | None:
    by_id = {r.condition_id: r for r in results}
    routing = by_id[ROUTING]
    rule = ruleset.condition(ROUTING)
    if routing.outcome == "fired":
        if routing.reason == "screening_not_covered":
            return Hold(
                "specialist_review",
                "escalate",
                "screening_not_covered",
                rule.id,
                rule.citation_status,
            )
        kind, reason = _ROUTING_HOLDS[case.status]
        action: Literal["block", "escalate"] = (
            "escalate" if kind == "specialist_review" else "block"
        )
        return Hold(kind, action, reason, rule.id, rule.citation_status)
    screening = _screening_condition(ruleset, case)
    if screening is not None and by_id[screening.id].outcome == "fired":
        step = next(s for s in definition.steps if s.gate is StepGate.SCREENING_COVERED)
        factors = tuple(q.key for q in step.questions if answers.get(q.key) == "yes")
        return Hold(
            "specialist_review",
            "escalate",
            "high_risk_factors",
            screening.id,
            screening.citation_status,
            factors,
        )
    return None


def _status(
    hold: Hold | None, asked: tuple[str, ...], missing: tuple[str, ...], screening: Screening
) -> Status:
    if hold is not None:
        return (
            "held_for_specialist_review"
            if hold.kind == "specialist_review"
            else "awaiting_jurisdiction"
        )
    if len(missing) == len(asked):
        return "case_created" if asked else "intake_in_progress"
    if missing:
        return "intake_in_progress"
    if screening == "not_cleared":
        return "screening_not_cleared"
    if screening == "cleared":
        return "intake_recorded"
    # Every asked question answered but no screening applies: only reachable if
    # the rule set offers no screening, which always holds above. Fail safe.
    return "intake_in_progress"
