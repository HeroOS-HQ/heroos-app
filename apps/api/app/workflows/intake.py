"""The Disciplinary intake evaluation (M2-02): routing, rules, screening and holds.

Pure and deterministic: the same answers, Company jurisdiction readiness,
earlier escalation and environment setting always give the same evaluation.
Nothing here reads free text, infers a fact or decides anything for the
employer.

Order of work:

1. The routing rule resolves the Case jurisdiction from the Company's
   operator-confirmed jurisdiction and the employer's confirmation for this
   Case. Missing, unclear, conflicting or unsupported -> no
   jurisdiction-specific rule runs.
2. Only enforced rules that apply in the resolved jurisdiction are evaluated,
   in order. A UAE Federal rule never runs for a DIFC Case, and a jurisdiction
   without screening is held for specialist review rather than screened with
   another jurisdiction's rule.
3. The result: the screening state, at most one hold (``jurisdiction`` =
   paused until confirmed; ``specialist_review`` = escalated), the cautions to
   show, the missing and uncertain answers, and the Case status.

A high-risk answer holds the Case; it is never evidence about the employee. A
"Not sure" or a missing answer never clears the screening.

**An escalation is never released by changed answers.** Once a save has held
the Case for specialist review, every later evaluation keeps it held (reason
``earlier_escalation``) even if the current answers no longer trigger it.
There is no release in the product yet: who may release a hold, and how, is
undecided (no staffed expert-review workflow exists). Holds are internal: no
expert ticket is created and none is promised.

The safety screening asks health-related questions. It is offered only where
the environment enables it for synthetic demo data (``screening_enabled``);
sensitive answers are never copied into the evaluation trace (counts only).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from app.companies.jurisdiction import JurisdictionAssessment, JurisdictionReadiness
from app.db.models.company_blueprint import JURISDICTION_DIFC, JURISDICTION_UAE_FEDERAL
from app.workflows.conditions import (
    HIGH_RISK,
    JURISDICTIONS,
    ROUTING,
    RULESETS,
    Rule,
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
    "not_applicable", "disabled", "not_started", "incomplete", "not_cleared", "cleared", "positive"
]
HoldKind = Literal["jurisdiction", "specialist_review"]
HoldReason = Literal[
    # specialist_review (escalate)
    "high_risk_factors",
    "jurisdiction_different",
    "jurisdiction_unsupported",
    "screening_not_covered",
    "earlier_escalation",
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
    "screening_unavailable",
    "held_for_specialist_review",
    "intake_recorded",
]

STATUS_LABELS: Final[Mapping[Status, str]] = {
    "case_created": "Case created",
    "intake_in_progress": "Intake in progress",
    "awaiting_jurisdiction": "Awaiting jurisdiction confirmation",
    "screening_not_cleared": "Screening not cleared",
    "screening_unavailable": "Screening not enabled here",
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
class RuleResult:
    rule: str
    outcome: Outcome
    # The action taken when the rule fired; otherwise None.
    action: str | None
    # Why: a stable code (never free text).
    reason: str
    # The structured inputs the rule read: enumerated answers, or for sensitive
    # questions only how many were Yes / No / Not sure / unanswered.
    inputs: Mapping[str, object]
    # Fired cautions are shown unless a specialist-review hold is in force.
    shown: bool


@dataclass(frozen=True, slots=True)
class EarlierEscalation:
    """The first specialist-review hold an earlier save recorded for the Case."""

    reason: HoldReason
    since: datetime


@dataclass(frozen=True, slots=True)
class Hold:
    kind: HoldKind
    action: Literal["block", "escalate"]
    reason: HoldReason
    # The rule behind the hold (for earlier_escalation: behind the first one).
    rule: str
    # That rule's content is still under legal review.
    provisional: bool
    # high_risk_factors: the screening questions answered "Yes".
    factors: tuple[str, ...] = ()
    # earlier_escalation: why the Case was first held.
    origin: HoldReason | None = None


@dataclass(frozen=True, slots=True)
class Caution:
    # The rule's key (stable, customer-safe; also the notice key).
    rule: str
    provisional: bool


@dataclass(frozen=True, slots=True)
class IntakeEvaluation:
    definition_version: int
    ruleset_version: str
    ruleset_digest: str
    jurisdiction: CaseJurisdiction
    results: tuple[RuleResult, ...]
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
    # The first escalation, kept whatever the current answers say.
    earlier_escalation: EarlierEscalation | None = None

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
    def currently_escalated(self) -> bool:
        """The current answers or jurisdiction themselves call for specialist review."""
        return (
            self.hold is not None
            and self.hold.kind == "specialist_review"
            and self.hold.reason != "earlier_escalation"
        )

    @property
    def next_stage_open(self) -> bool:
        """The gate later stages (classification, options) must check, server-side."""
        return self.status == "intake_recorded"


def ruleset_for(definition: WorkflowDefinition) -> RuleSet:
    return RULESETS[definition.key]


def resolve_jurisdiction(
    company: JurisdictionAssessment, answers: Mapping[str, object]
) -> CaseJurisdiction:
    """The routing rule: the Case jurisdiction, or why there is none.

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
        company.jurisdiction not in JURISDICTIONS
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


def _screening_rule(ruleset: RuleSet, case: CaseJurisdiction) -> Rule | None:
    if case.jurisdiction is None:
        return None
    key = ruleset.screening_by_jurisdiction.get(case.jurisdiction)
    return None if key is None else ruleset.rule(key)


def step_available(
    step: Step,
    ruleset: RuleSet,
    company: JurisdictionAssessment,
    case: CaseJurisdiction,
    *,
    screening_enabled: bool,
) -> bool:
    if step.gate is StepGate.COMPANY_JURISDICTION_CONFIRMED:
        return company.guidance_allowed and company.jurisdiction in JURISDICTIONS
    if step.gate is StepGate.SCREENING_COVERED:
        return screening_enabled and case.resolved and _screening_rule(ruleset, case) is not None
    return True


def _inputs(
    rule: Rule, answers: Mapping[str, object], sensitive: frozenset[str]
) -> dict[str, object]:
    if rule.predicate is None:
        return {}
    keys = predicate_keys(rule.predicate)
    inputs: dict[str, object] = {
        key: _text(answers.get(key)) for key in keys if key not in sensitive
    }
    hidden = [answers.get(key) for key in keys if key in sensitive]
    if hidden:
        # Which sensitive question had which answer is in case_facts already;
        # the trace keeps only the counts.
        inputs["sensitive_answers"] = {
            "yes": sum(1 for v in hidden if v == "yes"),
            "no": sum(1 for v in hidden if v == "no"),
            "not_sure": sum(1 for v in hidden if v == NOT_SURE),
            "unanswered": sum(1 for v in hidden if v is None),
        }
    return inputs


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _routing_result(
    rule: Rule,
    ruleset: RuleSet,
    company: JurisdictionAssessment,
    case: CaseJurisdiction,
) -> RuleResult:
    inputs: dict[str, object] = {
        "company.readiness": str(company.readiness),
        "company.reason": str(company.reason),
        "company.jurisdiction": company.jurisdiction,
        CASE_JURISDICTION_KEY: case.case_answer,
    }
    if case.status == "awaiting_case_confirmation":
        return RuleResult(rule.key, "unknown", None, case.status, inputs, False)
    escalate = case.status in ("company_unsupported", "case_different")
    if not case.resolved:
        action = "escalate" if escalate else "block"
        return RuleResult(rule.key, "fired", action, case.status, inputs, True)
    if _screening_rule(ruleset, case) is None:
        # Resolved, but no screening covers this jurisdiction: fail safe.
        return RuleResult(rule.key, "fired", "escalate", "screening_not_covered", inputs, True)
    return RuleResult(rule.key, "not_fired", None, "resolved", inputs, False)


def _screening_step(definition: WorkflowDefinition) -> Step:
    return next(s for s in definition.steps if s.gate is StepGate.SCREENING_COVERED)


def _screening_state(
    definition: WorkflowDefinition,
    available: bool,
    disabled: bool,
    answers: Mapping[str, object],
) -> Screening:
    if disabled:
        return "disabled"
    if not available:
        return "not_applicable"
    values = [answers.get(q.key) for q in _screening_step(definition).questions]
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
    *,
    screening_enabled: bool,
    earlier_escalation: EarlierEscalation | None = None,
) -> IntakeEvaluation:
    """Evaluate the intake for the current answers, readiness and history."""
    ruleset = ruleset_for(definition)
    case = resolve_jurisdiction(company, answers)
    jurisdiction = case.jurisdiction
    sensitive = frozenset(q.key for s in definition.steps for q in s.questions if q.sensitive)

    results: list[RuleResult] = []
    for rule in sorted(ruleset.rules, key=lambda r: r.order):
        if rule.key == ROUTING:
            results.append(_routing_result(rule, ruleset, company, case))
            continue
        inputs = _inputs(rule, answers, sensitive)
        if not rule.enforced:
            results.append(
                RuleResult(rule.key, "not_applicable", None, "not_enforced", inputs, False)
            )
        elif jurisdiction is None or not rule.applies_to(jurisdiction):
            reason = "jurisdiction_unresolved" if jurisdiction is None else "other_jurisdiction"
            results.append(RuleResult(rule.key, "not_applicable", None, reason, inputs, False))
        elif rule.key == HIGH_RISK and not screening_enabled:
            results.append(
                RuleResult(rule.key, "not_applicable", None, "screening_disabled", inputs, False)
            )
        else:
            assert rule.predicate is not None
            truth = evaluate(rule.predicate, answers)
            if truth is Tri.TRUE:
                results.append(RuleResult(rule.key, "fired", rule.action, "met", inputs, True))
            elif truth is Tri.FALSE:
                results.append(RuleResult(rule.key, "not_fired", None, "not_met", inputs, False))
            else:
                results.append(
                    RuleResult(rule.key, "unknown", None, "unknown_inputs", inputs, False)
                )

    available = tuple(
        step.key
        for step in definition.steps
        if step_available(step, ruleset, company, case, screening_enabled=screening_enabled)
    )
    covered = case.resolved and _screening_rule(ruleset, case) is not None
    screening = _screening_state(
        definition,
        _screening_step(definition).key in available,
        covered and not screening_enabled,
        answers,
    )

    hold = _hold(definition, ruleset, case, results, answers, screening_enabled)
    if earlier_escalation is not None and (hold is None or hold.kind != "specialist_review"):
        # Changed answers never release an escalation (no release exists yet).
        origin = earlier_escalation.reason
        first_rule = ruleset.rule(HIGH_RISK if origin == "high_risk_factors" else ROUTING)
        hold = Hold(
            "specialist_review",
            "escalate",
            "earlier_escalation",
            first_rule.key,
            first_rule.provisional,
            origin=origin,
        )
    if hold is not None and hold.kind == "specialist_review":
        # No further self-service guidance while escalated: cautions are
        # recorded, not shown.
        results = [
            r
            if r.outcome != "fired" or r.action != "warn"
            else RuleResult(r.rule, r.outcome, r.action, r.reason, r.inputs, False)
            for r in results
        ]
    rules = {r.key: r for r in ruleset.rules}
    cautions = tuple(
        Caution(r.rule, rules[r.rule].provisional)
        for r in results
        if r.outcome == "fired" and r.action == "warn" and r.shown
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
        earlier_escalation=earlier_escalation,
    )


def _hold(
    definition: WorkflowDefinition,
    ruleset: RuleSet,
    case: CaseJurisdiction,
    results: list[RuleResult],
    answers: Mapping[str, object],
    screening_enabled: bool,
) -> Hold | None:
    by_rule = {r.rule: r for r in results}
    routing = by_rule[ROUTING]
    rule = ruleset.rule(ROUTING)
    if routing.outcome == "fired":
        if routing.reason == "screening_not_covered":
            return Hold(
                "specialist_review", "escalate", "screening_not_covered", rule.key, rule.provisional
            )
        kind, reason = _ROUTING_HOLDS[case.status]
        action: Literal["block", "escalate"] = (
            "escalate" if kind == "specialist_review" else "block"
        )
        return Hold(kind, action, reason, rule.key, rule.provisional)
    screening = _screening_rule(ruleset, case)
    if screening_enabled and screening is not None and by_rule[screening.key].outcome == "fired":
        factors = tuple(
            q.key for q in _screening_step(definition).questions if answers.get(q.key) == "yes"
        )
        return Hold(
            "specialist_review",
            "escalate",
            "high_risk_factors",
            screening.key,
            screening.provisional,
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
    if screening == "disabled":
        return "screening_unavailable"
    if screening == "not_cleared":
        return "screening_not_cleared"
    if screening == "cleared":
        return "intake_recorded"
    # Every asked question answered but no screening ran: only reachable if the
    # rule set offers no screening, which always holds above. Fail safe.
    return "intake_in_progress"
