"""Deterministic intake rules (M2-02): a small, ordered, typed rule set.

The engine here is generic: rules are data, evaluated by ``evaluate`` with
explicit three-valued logic. An unanswered question and "Not sure" are
UNKNOWN, never "No"; nothing is ever executed from text.

Each rule has:

- a neutral ``key`` (also the key of its customer-facing notice);
- the jurisdictions it applies in (an empty tuple: every Case, run first);
- its action (warn, block or escalate) and, for the routing rule, the second
  action it can take;
- whether its content is still under legal review (``provisional``: shown as
  provisional, never as approved advice) and whether it is enforced;
- the step whose answers it reads and its typed predicate.

The rule content is development content from HeroOS's private content library.
Which library entries, versions and review statuses each rule corresponds to is
kept privately with the M2-02 records, not in this public repository; the
rule-set ``version`` and ``digest`` (stored with every evaluation) identify
exactly which rules ran.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

from app.db.models.company_blueprint import JURISDICTION_DIFC, JURISDICTION_UAE_FEDERAL
from app.workflows.definition import NOT_SURE, SAFETY_SCREENING

Action = Literal["warn", "block", "escalate"]

# The jurisdictions the rule set knows (company_blueprints.employment_jurisdiction codes).
JURISDICTIONS: Final = (JURISDICTION_UAE_FEDERAL, JURISDICTION_DIFC)


class Tri(StrEnum):
    """Three-valued (Kleene) truth: an unknown input never becomes "false"."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AnswerIn:
    """True if the answer to ``key`` is one of ``values``.

    Unanswered is UNKNOWN. So is any answer in ``unknown`` ("Not sure" by
    default); a rule that triggers when something is "not stated" sets
    ``unknown=()`` and lists "Not sure" among its ``values`` instead.
    """

    key: str
    values: tuple[str, ...]
    unknown: tuple[str, ...] = (NOT_SURE,)


@dataclass(frozen=True, slots=True)
class AllOf:
    terms: tuple["Predicate", ...]


@dataclass(frozen=True, slots=True)
class AnyOf:
    terms: tuple["Predicate", ...]


Predicate = AnswerIn | AllOf | AnyOf


def evaluate(predicate: Predicate, answers: Mapping[str, object]) -> Tri:
    """Evaluate a predicate on the current answers (pure, total, no ``eval``)."""
    if isinstance(predicate, AnswerIn):
        value = answers.get(predicate.key)
        if value is None or value in predicate.unknown:
            return Tri.UNKNOWN
        return Tri.TRUE if value in predicate.values else Tri.FALSE
    results = [evaluate(term, answers) for term in predicate.terms]
    if isinstance(predicate, AllOf):
        if Tri.FALSE in results:
            return Tri.FALSE
        return Tri.TRUE if all(r is Tri.TRUE for r in results) else Tri.UNKNOWN
    if Tri.TRUE in results:
        return Tri.TRUE
    return Tri.FALSE if all(r is Tri.FALSE for r in results) else Tri.UNKNOWN


def predicate_keys(predicate: Predicate) -> tuple[str, ...]:
    """The answer keys a predicate reads, in order, without repeats."""
    if isinstance(predicate, AnswerIn):
        return (predicate.key,)
    keys: list[str] = []
    for term in predicate.terms:
        keys += [key for key in predicate_keys(term) if key not in keys]
    return tuple(keys)


def _predicate_data(predicate: Predicate) -> dict[str, object]:
    if isinstance(predicate, AnswerIn):
        return {
            "answer_in": predicate.key,
            "values": list(predicate.values),
            "unknown": list(predicate.unknown),
        }
    name = "all_of" if isinstance(predicate, AllOf) else "any_of"
    return {name: [_predicate_data(term) for term in predicate.terms]}


@dataclass(frozen=True, slots=True)
class Rule:
    key: str
    # Evaluation order within the rule set.
    order: int
    # Jurisdictions the rule applies in; empty: every Case, before anything else.
    applies_in: tuple[str, ...]
    action: Action
    # A second action the rule can take (routing: confirm, or escalate).
    alternate_action: Action | None
    # Content still under legal review: shown as provisional, never as approved.
    provisional: bool
    # A rule can be kept in the set without being applied.
    enforced: bool
    # The step whose answers the rule reads; None for the routing rule.
    step: str | None
    # None only for the routing rule, which reads the Company's jurisdiction
    # readiness and the Case confirmation (app.workflows.intake).
    predicate: Predicate | None

    def applies_to(self, jurisdiction: str) -> bool:
        return not self.applies_in or jurisdiction in self.applies_in


@dataclass(frozen=True, slots=True)
class RuleSet:
    version: str
    workflow_key: str
    rules: tuple[Rule, ...]
    # Jurisdiction -> the rule that screens a Case of that jurisdiction for
    # high-risk factors. A jurisdiction without an entry has no screening:
    # such a Case is held, never screened with another jurisdiction's rule.
    screening_by_jurisdiction: Mapping[str, str]

    def rule(self, key: str) -> Rule:
        return next(r for r in self.rules if r.key == key)

    def data(self) -> dict[str, object]:
        """The rule set as plain data (canonical: what ``digest`` hashes)."""
        return {
            "version": self.version,
            "workflow_key": self.workflow_key,
            "rules": [
                {
                    "key": r.key,
                    "order": r.order,
                    "applies_in": list(r.applies_in),
                    "action": r.action,
                    "alternate_action": r.alternate_action,
                    "provisional": r.provisional,
                    "enforced": r.enforced,
                    "step": r.step,
                    "predicate": None if r.predicate is None else _predicate_data(r.predicate),
                }
                for r in self.rules
            ],
            "screening_by_jurisdiction": dict(sorted(self.screening_by_jurisdiction.items())),
        }

    @property
    def digest(self) -> str:
        """SHA-256 of the canonical rule set: any change of any rule changes it."""
        canonical = json.dumps(self.data(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


ROUTING: Final = "case_jurisdiction"
HIGH_RISK: Final = "high_risk_screening"
FEDERAL: Final = (JURISDICTION_UAE_FEDERAL,)

DISCIPLINARY_INTAKE: Final = RuleSet(
    version="disciplinary-intake.1",
    workflow_key="disciplinary",
    rules=(
        # Runs ahead of every other rule. Unclear -> ask to confirm (block);
        # conflicting or unsupported -> escalate.
        Rule(
            key=ROUTING,
            order=1,
            applies_in=(),
            action="block",
            alternate_action="escalate",
            provisional=False,
            enforced=True,
            step=None,
            predicate=None,
        ),
        Rule(
            key="policy_awareness",
            order=2,
            applies_in=FEDERAL,
            action="warn",
            alternate_action=None,
            provisional=True,
            enforced=True,
            step="incident_context",
            predicate=AnswerIn("context.policy_awareness", ("no",)),
        ),
        Rule(
            key="same_incident_sanction",
            order=3,
            applies_in=FEDERAL,
            action="warn",
            alternate_action=None,
            provisional=False,
            enforced=True,
            step="incident_context",
            predicate=AnswerIn("history.same_incident_sanction", ("yes",)),
        ),
        # Outside work and no connection to work stated: "Not sure" states none.
        Rule(
            key="off_duty_connection",
            order=4,
            applies_in=FEDERAL,
            action="warn",
            alternate_action=None,
            provisional=False,
            enforced=True,
            step="incident_context",
            predicate=AllOf(
                (
                    AnswerIn("context.location", ("outside_work",)),
                    AnswerIn("context.work_connection", ("no", NOT_SURE), unknown=()),
                )
            ),
        ),
        # Any one factor escalates before any action is taken or put in
        # writing. Applies in UAE Federal Cases only; a DIFC Case is held.
        Rule(
            key=HIGH_RISK,
            order=5,
            applies_in=FEDERAL,
            action="escalate",
            alternate_action=None,
            provisional=True,
            enforced=True,
            step="safety_screening",
            predicate=AnyOf(tuple(AnswerIn(q.key, ("yes",)) for q in SAFETY_SCREENING.questions)),
        ),
    ),
    screening_by_jurisdiction={JURISDICTION_UAE_FEDERAL: HIGH_RISK},
)

RULESETS: Final[Mapping[str, RuleSet]] = {DISCIPLINARY_INTAKE.workflow_key: DISCIPLINARY_INTAKE}
