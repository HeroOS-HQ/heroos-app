"""Deterministic intake conditions (M2-02): an ordered, typed subset of the Conditions Library.

The HeroOS Conditions Library (JJ's workbook, confidential, not in this
repository) holds per-case triggers, jurisdiction tags and actions; the
Implementation Rules say how the engine routes and isolates them. This module
encodes only the conditions the Disciplinary intake needs, each with:

- its **source condition ID**, jurisdiction tag, type and action exactly as the
  workbook states them (``source_action`` keeps the workbook's own word where
  it is not one of warn / block / escalate);
- its ``citation_status`` and ``enforcement_status``, unchanged: a
  ``needs_legal_review`` condition stays provisional development content, it is
  never presented as approved legal advice;
- the workbook row (and the Implementation Rules it implements) and the
  SHA-256 of the exact source files it was mapped from;
- a **typed predicate** over structured answers. Triggers are never text that
  gets executed: they are small dataclasses evaluated by ``evaluate`` below,
  with explicit three-valued logic. An unanswered question and "Not sure" are
  UNKNOWN, never "No".

Customer-facing wording is not here: conditions carry a ``notice`` key and the
conversation module writes neutral text for it. Condition IDs, tags and review
statuses are implementation metadata (Implementation Rules §5) and are never
shown to customers.

The reviewable mapping of every rule to its source and tests is
docs/architecture/disciplinary-intake.md.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

from app.db.models.company_blueprint import JURISDICTION_DIFC, JURISDICTION_UAE_FEDERAL
from app.workflows.definition import NOT_SURE, SAFETY_SCREENING

JurisdictionTag = Literal["GLOBAL", "SHARED", "UAE-FED", "DIFC"]
ConditionType = Literal["precondition", "step_caution", "blocking"]
Action = Literal["warn", "block", "escalate"]
CitationStatus = Literal["confirmed", "needs_legal_review"]
EnforcementStatus = Literal["active", "not_enforced"]

# The Case jurisdiction (company_blueprints.employment_jurisdiction codes) ->
# the workbook's jurisdiction tag. Anything else has no tag: unsupported.
JURISDICTION_TAGS: Final[Mapping[str, JurisdictionTag]] = {
    JURISDICTION_UAE_FEDERAL: "UAE-FED",
    JURISDICTION_DIFC: "DIFC",
}


class Tri(StrEnum):
    """Three-valued (Kleene) truth: an unknown input never becomes "false"."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AnswerIn:
    """True if the answer to ``key`` is one of ``values``.

    Unanswered is UNKNOWN. So is any answer in ``unknown`` ("Not sure" by
    default); a condition whose source trigger reads "not stated" sets
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
class SourceDocument:
    file: str
    sha256: str
    version: str


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Where in a source document a condition comes from."""

    document: Literal["conditions_library", "implementation_rules"]
    # "Conditions Library!R16", "Structural Findings!R25", "Rule 7", ...
    location: str


@dataclass(frozen=True, slots=True)
class Condition:
    id: str
    # Evaluation order within the rule set.
    order: int
    jurisdiction: JurisdictionTag
    type: ConditionType
    action: Action
    # A second action the condition can take (the routing rule: "ask the
    # customer to confirm, or escalate").
    alternate_action: Action | None
    # The workbook's action cell as written.
    source_action: str
    citation_status: CitationStatus
    enforcement_status: EnforcementStatus
    # The step whose answers the condition reads; None for the routing rule.
    step: str | None
    # None only for the routing rule, which reads the Company Blueprint
    # readiness and the Case confirmation (app.workflows.intake).
    predicate: Predicate | None
    sources: tuple[SourceRef, ...]
    # Key of the customer-facing notice (app.workflows.conversation).
    notice: str

    def applies_to(self, jurisdiction: JurisdictionTag) -> bool:
        """Implementation Rules §4 and §7: only the Case's own tag, plus SHARED and GLOBAL."""
        return self.jurisdiction in ("GLOBAL", "SHARED", jurisdiction)

    @property
    def enforced(self) -> bool:
        return self.enforcement_status == "active"


@dataclass(frozen=True, slots=True)
class RuleSet:
    version: str
    workflow_key: str
    sources: Mapping[str, SourceDocument]
    conditions: tuple[Condition, ...]
    # Jurisdiction tag -> the condition that screens a Case of that
    # jurisdiction for high-risk factors. A tag without an entry has no
    # approved screening: such a Case is held, never screened by another
    # jurisdiction's rule.
    screening_by_jurisdiction: Mapping[JurisdictionTag, str]

    def condition(self, condition_id: str) -> Condition:
        return next(c for c in self.conditions if c.id == condition_id)

    def data(self) -> dict[str, object]:
        """The rule set as plain data (canonical: what ``digest`` hashes)."""
        return {
            "version": self.version,
            "workflow_key": self.workflow_key,
            "sources": {
                name: {"file": s.file, "sha256": s.sha256, "version": s.version}
                for name, s in sorted(self.sources.items())
            },
            "conditions": [
                {
                    "id": c.id,
                    "order": c.order,
                    "jurisdiction": c.jurisdiction,
                    "type": c.type,
                    "action": c.action,
                    "alternate_action": c.alternate_action,
                    "source_action": c.source_action,
                    "citation_status": c.citation_status,
                    "enforcement_status": c.enforcement_status,
                    "step": c.step,
                    "predicate": None if c.predicate is None else _predicate_data(c.predicate),
                    "sources": [
                        {"document": s.document, "location": s.location} for s in c.sources
                    ],
                    "notice": c.notice,
                }
                for c in self.conditions
            ],
            "screening_by_jurisdiction": dict(sorted(self.screening_by_jurisdiction.items())),
        }

    @property
    def digest(self) -> str:
        """SHA-256 of the canonical rule set: any change of rule or source changes it."""
        canonical = json.dumps(self.data(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


# The exact files the conditions below were mapped from (read-only; not stored
# in this repository).
CONDITIONS_LIBRARY: Final = SourceDocument(
    file="HeroOS_Conditions_Library-13.xlsx",
    sha256="ee7cfe5afe0986b01febf6a7a8f225fa75596ec33d435aba2bad5f08fb0be57d",
    version="workbook modified 2026-10-14T07:29:23Z",
)
IMPLEMENTATION_RULES: Final = SourceDocument(
    file="HeroOS Aries Implementation Rules - 14-10.docx",
    sha256="de03a865e830b9cf0b32e93699e036a16fa6c1bd21c90dd5c9625211273d26eb",
    version="working draft, revision 6, modified 2026-10-14T06:30:00Z",
)

ROUTING: Final = "JURISDICTION-ROUTING-001"
STOP_CALL_FIRST: Final = "UAE-STOP-CALL-FIRST"
POLICY_ACK_CASE: Final = "POLICY-ACK-CASE"
ONE_PENALTY: Final = "UAE-ONE-PENALTY-SAME-INCIDENT"
OFFDUTY: Final = "UAE-OFFDUTY-CONNECTION"


def _cl(row: int, sheet: str = "Conditions Library") -> SourceRef:
    return SourceRef("conditions_library", f"{sheet}!R{row}")


def _ir(rule: int) -> SourceRef:
    return SourceRef("implementation_rules", f"Rule {rule}")


DISCIPLINARY_INTAKE: Final = RuleSet(
    version="disciplinary-intake.1",
    workflow_key="disciplinary",
    sources={
        "conditions_library": CONDITIONS_LIBRARY,
        "implementation_rules": IMPLEMENTATION_RULES,
    },
    conditions=(
        # Runs ahead of every other condition (its own trigger text). Unclear
        # -> ask the customer to confirm (block); conflicting or unsupported ->
        # escalate. The workbook's action cell says "blocking".
        Condition(
            id=ROUTING,
            order=1,
            jurisdiction="GLOBAL",
            type="precondition",
            action="block",
            alternate_action="escalate",
            source_action="blocking",
            citation_status="confirmed",
            enforcement_status="active",
            step=None,
            predicate=None,
            sources=(
                _cl(41),
                _cl(11, "Blueprint Fields"),
                _cl(23, "Structural Findings"),
                _cl(25, "Structural Findings"),
                _ir(1),
                _ir(2),
                _ir(3),
                _ir(4),
                _ir(5),
                _ir(6),
                _ir(7),
                _ir(17),
            ),
            notice="jurisdiction",
        ),
        # The rest in workbook row order.
        Condition(
            id=POLICY_ACK_CASE,
            order=2,
            jurisdiction="UAE-FED",
            type="step_caution",
            action="warn",
            alternate_action=None,
            source_action="warn",
            citation_status="needs_legal_review",
            enforcement_status="active",
            step="incident_context",
            predicate=AnswerIn("context.policy_awareness", ("no",)),
            sources=(_cl(5),),
            notice="policy_awareness",
        ),
        Condition(
            id=ONE_PENALTY,
            order=3,
            jurisdiction="UAE-FED",
            type="step_caution",
            action="warn",
            alternate_action=None,
            source_action="warn",
            citation_status="confirmed",
            enforcement_status="active",
            step="incident_context",
            predicate=AnswerIn("history.same_incident_sanction", ("yes",)),
            sources=(_cl(14),),
            notice="same_incident_sanction",
        ),
        # "incident_location == outside work AND no stated connection to
        # work": "Not sure" states no connection, so it counts with "No".
        Condition(
            id=OFFDUTY,
            order=4,
            jurisdiction="UAE-FED",
            type="step_caution",
            action="warn",
            alternate_action=None,
            source_action="warn",
            citation_status="confirmed",
            enforcement_status="active",
            step="incident_context",
            predicate=AllOf(
                (
                    AnswerIn("context.location", ("outside_work",)),
                    AnswerIn("context.work_connection", ("no", NOT_SURE), unknown=()),
                )
            ),
            sources=(_cl(15),),
            notice="off_duty_connection",
        ),
        # Any one high-risk factor escalates before any action is taken or put
        # in writing. Tagged UAE-FED ("proposed SHARED" is not approved): a
        # DIFC Case is held instead (screening_by_jurisdiction).
        Condition(
            id=STOP_CALL_FIRST,
            order=5,
            jurisdiction="UAE-FED",
            type="blocking",
            action="escalate",
            alternate_action=None,
            source_action="escalate",
            citation_status="needs_legal_review",
            enforcement_status="active",
            step="safety_screening",
            predicate=AnyOf(tuple(AnswerIn(q.key, ("yes",)) for q in SAFETY_SCREENING.questions)),
            sources=(_cl(16), _cl(11, "Structural Findings"), _ir(18)),
            notice="high_risk_factors",
        ),
    ),
    screening_by_jurisdiction={"UAE-FED": STOP_CALL_FIRST},
)

RULESETS: Final[Mapping[str, RuleSet]] = {DISCIPLINARY_INTAKE.workflow_key: DISCIPLINARY_INTAKE}
