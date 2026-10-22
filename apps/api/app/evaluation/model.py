"""The evaluation's domain contracts: plain, immutable, independent of the API and the browser.

Two vocabularies stay separate:

- the **business disposition** of a requested employer action (``allow``,
  ``warn``, ``unknown``, ``block``, ``escalate``) and the one **presentation**
  the founder sees (Guidance, Warning, Block, Expert Review);
- the **technical availability** of the evaluation itself (``ready`` or why
  not). A technical problem never becomes a business outcome: no Block, no
  Expert Review is ever shown because something is missing or broken.

``allow`` never means lawful: only that no active deterministic HeroOS rule
prevents the step on the trusted inputs and the compatible approved content.
``unknown`` means HeroOS can't evaluate every safeguard of that step yet (no
executable rule exists for one, or the input can't be collected here): it is
never treated as clear.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final, Literal

from app.workflows.conditions import Tri

EVALUATION_SCHEMA: Final = "heroos.conversation-evaluation/1"

Disposition = Literal["allow", "warn", "unknown", "block", "escalate"]
# ESCALATE > BLOCK > UNKNOWN > WARN > ALLOW: the strongest result of a step wins.
DISPOSITIONS: Final[tuple[Disposition, ...]] = ("allow", "warn", "unknown", "block", "escalate")
RANK: Final[Mapping[str, int]] = {d: i for i, d in enumerate(DISPOSITIONS)}

Presentation = Literal["guidance", "warning", "block", "expert_review"]
PRESENTATIONS: Final[Mapping[Disposition, Presentation]] = {
    "allow": "guidance",
    "warn": "warning",
    # Not evaluable is a caution, never a clearance and never a false Block.
    "unknown": "warning",
    "block": "block",
    "escalate": "expert_review",
}

Availability = Literal[
    "ready", "knowledge_bundle_missing", "rule_bundle_missing", "execution_profile_missing",
    "incompatible_versions", "unsupported_executor", "privacy_capability_unavailable",
    "invalid_continuation", "internal_failure",
]  # fmt: skip
Category = Literal["executable", "guard_only", "question_only", "not_enforced", "quarantined"]
CATEGORIES: Final[tuple[Category, ...]] = (
    "executable", "guard_only", "question_only", "not_enforced", "quarantined",
)  # fmt: skip
ConditionStatus = Literal["fired", "not_fired", "unknown", "unavailable", "not_evaluated"]
Trust = Literal["proposed", "established_conversational", "engine_trusted"]
FactSource = Literal["direct_answer", "confirmation", "blueprint", "continuation"]
Matter = Literal[
    "supported", "unsupported_hr", "outside_product_scope", "unclear", "confidential_request",
]  # fmt: skip
JurisdictionState = Literal[
    "resolved", "company_unconfirmed", "conversation_conflict", "case_different", "case_not_sure",
]  # fmt: skip
PathwayOwnership = Literal[
    "ai_candidate_only", "employer_confirmation_required", "deterministic", "none",
]  # fmt: skip
NextStep = Literal[
    "continue_methodology", "answer_question", "establish_prerequisite", "consider_caution",
    "obtain_specialist_review", "confirm_jurisdiction", "choose_matter", "seek_specialist_advice",
    "complete_case_step",
]  # fmt: skip
# The prefix of a stage checklist answer (a Case fact the employer saves in a started stage).
CHECKLIST_PREFIX: Final = "progress."
RequirementKind = Literal["fact", "confirmation", "jurisdiction", "insistence"]
FollowUpState = Literal["not_applicable", "pending", "applied", "reconfirm"]

# HeroOS has no staffed Expert Review yet (M2-NEW-09): a requirement, never a ticket.
EXPERT_REVIEW_SERVICE_AVAILABLE: Final = False

Value = str | int


@dataclass(frozen=True, slots=True)
class TrustedFactState:
    """The facts of this turn, by trust level. Only ``engine`` ever enters a rule."""

    # ENGINE_TRUSTED: canonical values (an option value or a whole number).
    engine: Mapping[str, Value] = field(default_factory=dict)
    # Where each engine value came from (direct_answer, confirmation, blueprint, continuation).
    sources: Mapping[str, FactSource] = field(default_factory=dict)
    # ESTABLISHED_CONVERSATIONAL: what the founder clearly said, as the AI read it. Useful
    # for the conversation (never asked again), never a rule's input.
    conversational: Mapping[str, str] = field(default_factory=dict)
    # PROPOSED only: hinted, approximate, contradicted or hedged.
    proposed: tuple[str, ...] = ()

    def level(self, key: str) -> Trust | None:
        if key in self.engine:
            return "engine_trusted"
        if key in self.conversational:
            return "established_conversational"
        return "proposed" if key in self.proposed else None

    @property
    def not_engine_trusted(self) -> int:
        """Conversational facts not (or not yet) trusted for execution."""
        return len([k for k in self.conversational if k not in self.engine])


@dataclass(frozen=True, slots=True)
class CaseProgress:
    """The attached Case's formal progression, as authoritative evaluation input (M2-NEW-08).

    Read from the Case's own records, never from the conversation: the stages its
    employer completed (progress events) and the stage checklist answers the
    employer saved, for the jurisdiction the Case's progression runs under. Only an
    employer decision's prerequisite rule reads them, and only when the evaluation
    resolves that same jurisdiction; anywhere else no stage is completed and no
    checklist answer is known. The AI can't write any of it: the employer records
    a pathway, a stage and a checklist answer through the Case's own controls.
    """

    # The Case's resolved jurisdiction (its intake's); None while unresolved.
    jurisdiction: str | None
    completed: frozenset[str] = frozenset()
    # Checklist fact key (``progress.<stage>.<item>``) -> the employer's saved answer.
    checklist: Mapping[str, str] = field(default_factory=dict)

    def applies(self, jurisdiction: str | None) -> bool:
        return jurisdiction is not None and self.jurisdiction == jurisdiction


@dataclass(frozen=True, slots=True)
class TwoState:
    """A two-state caution (warn first; stronger only if the employer explicitly insists)."""

    # The bound rule's key.
    rule: str
    # The caution was shown (its condition was met).
    shown: bool
    # The founder said they understood it: never an employment decision.
    acknowledged: bool
    # TRUE: explicitly intends to proceed regardless (ENGINE_TRUSTED); FALSE: explicitly
    # doesn't; UNKNOWN: not stated, or trusted state was lost and must be confirmed again.
    insists: Tri


@dataclass(frozen=True, slots=True)
class Note:
    """Approved wording behind a result: a Condition's or a rule's title and text."""

    title: str
    text: tuple[str, ...]
    # The legal basis isn't confirmed (needs_legal_review / provisional): never presented as law.
    provisional: bool


@dataclass(frozen=True, slots=True)
class ConditionEvaluation:
    condition: str
    category: Category
    status: ConditionStatus
    # The Condition's configured (initial) action.
    initial: str
    # The action it takes now (fired or unknown inputs, follow-up included); None otherwise.
    action: str | None
    follow_up: FollowUpState
    reasons: tuple[str, ...]
    # Fact keys whose absence keeps it from being decided.
    missing: tuple[str, ...]
    provisional: bool
    # The employer decisions the approved content links it to here.
    linked_actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewRequirement:
    required: bool
    scope: Literal["action", "matter"]
    # The action it holds (scope "action"); None for the whole matter.
    action: str | None
    reasons: tuple[str, ...]
    service_available: bool = EXPERT_REVIEW_SERVICE_AVAILABLE


@dataclass(frozen=True, slots=True)
class MissingRequirement:
    # A fact key, "jurisdiction", or "insistence:<rule>".
    key: str
    kind: RequirementKind
    label: str
    # The requested actions it holds (empty: the conversation's own question).
    actions: tuple[str, ...]
    # confirmation: the canonical value the founder is asked to confirm.
    candidate: Value | None = None


@dataclass(frozen=True, slots=True)
class Caution:
    source: str
    note: Note
    two_state: bool
    action: str


@dataclass(frozen=True, slots=True)
class ActionEvaluation:
    """One requested employer decision, by stable option id (never its display title)."""

    action: str
    title: str
    disposition: Disposition
    reasons: tuple[str, ...]
    missing: tuple[str, ...]
    provisional: bool
    review: ReviewRequirement | None
    next_step: NextStep
    conditions: tuple[str, ...]
    notes: tuple[Note, ...] = ()
    scope: Literal["action"] = "action"
    # M2-NEW-08: asked about only hypothetically ("what if I dismissed them?"): evaluated so
    # the answer is accurate, never recorded as the employer's intention (no active review,
    # never carried as still requested).
    hypothetical: bool = False


@dataclass(frozen=True, slots=True)
class Provenance:
    snapshot: str
    workflow: str
    knowledge_runtime_digest: str
    profile: str
    profile_version: str
    profile_digest: str
    definition_version: int
    rule_bundle: str | None
    rule_bundle_version: str | None
    rule_bundle_digest: str | None


@dataclass(frozen=True, slots=True)
class ConversationEvaluation:
    availability: Availability
    matter: Matter
    workflow: str | None = None
    jurisdiction: str | None = None
    jurisdiction_state: JurisdictionState | None = None
    pathway_candidate: str | None = None
    pathway_ownership: PathwayOwnership = "none"
    facts: TrustedFactState = field(default_factory=TrustedFactState)
    conditions: tuple[ConditionEvaluation, ...] = ()
    actions: tuple[ActionEvaluation, ...] = ()
    reviews: tuple[ReviewRequirement, ...] = ()
    missing: tuple[MissingRequirement, ...] = ()
    cautions: tuple[Caution, ...] = ()
    two_state: tuple[TwoState, ...] = ()
    # None: no business outcome (technical unavailability, or not an HR matter HeroOS covers).
    presentation: Presentation | None = None
    next_step: NextStep | None = None
    multiple_matters: bool = False
    provenance: Provenance | None = None
    # M2-NEW-08: the Case's formal progression the prerequisites read (None: no Case).
    case_progress: CaseProgress | None = None
    schema: str = EVALUATION_SCHEMA

    @property
    def ready(self) -> bool:
        return self.availability == "ready"

    def disposition_counts(self) -> dict[str, int]:
        return {d: sum(1 for a in self.actions if a.disposition == d) for d in DISPOSITIONS}

    def record(self) -> dict[str, object]:
        """Canonical plain data (M2-NEW-07 may persist it after re-evaluating it server-side).

        Never sent to a browser, and never trusted when it comes back from one.
        """
        provenance = self.provenance
        return {
            "schema": self.schema,
            "availability": self.availability,
            "matter": self.matter,
            "workflow": self.workflow,
            "jurisdiction": self.jurisdiction,
            "jurisdiction_state": self.jurisdiction_state,
            "pathway": {"candidate": self.pathway_candidate, "ownership": self.pathway_ownership},
            "facts": {
                "engine_trusted": dict(sorted(self.facts.engine.items())),
                "sources": dict(sorted(self.facts.sources.items())),
                "established_conversational": sorted(self.facts.conversational),
                "proposed": sorted(self.facts.proposed),
            },
            "conditions": [
                {
                    "condition": c.condition,
                    "category": c.category,
                    "status": c.status,
                    "initial": c.initial,
                    "action": c.action,
                    "follow_up": c.follow_up,
                    "reasons": list(c.reasons),
                    "missing": list(c.missing),
                    "provisional": c.provisional,
                    "linked_actions": list(c.linked_actions),
                }  # fmt: skip
                for c in self.conditions
            ],
            "actions": [
                {
                    "action": a.action,
                    "disposition": a.disposition,
                    "reasons": list(a.reasons),
                    "missing": list(a.missing),
                    "provisional": a.provisional,
                    "review": a.review is not None and a.review.required,
                    "next_step": a.next_step,
                    "conditions": list(a.conditions),
                    "hypothetical": a.hypothetical,
                }  # fmt: skip
                for a in self.actions
            ],
            "reviews": [
                {
                    "scope": r.scope,
                    "action": r.action,
                    "reasons": list(r.reasons),
                    "service_available": r.service_available,
                }  # fmt: skip
                for r in self.reviews
            ],
            "missing": [
                {"key": m.key, "kind": m.kind, "actions": list(m.actions)} for m in self.missing
            ],  # fmt: skip
            "two_state": [
                {
                    "rule": t.rule,
                    "shown": t.shown,
                    "acknowledged": t.acknowledged,
                    "insists": t.insists.value,
                }  # fmt: skip
                for t in self.two_state
            ],
            "presentation": self.presentation,
            "next_step": self.next_step,
            "multiple_matters": self.multiple_matters,
            # M2-NEW-08 (additive): the Case progression the prerequisites read, by stage key.
            "case_progress": None
            if self.case_progress is None
            else {
                "jurisdiction": self.case_progress.jurisdiction,
                "applied": self.case_progress.applies(self.jurisdiction),
                "completed": sorted(self.case_progress.completed),
                "checklist_answers": len(self.case_progress.checklist),
            },
            "provenance": None
            if provenance is None
            else {
                "snapshot": provenance.snapshot,
                "workflow": provenance.workflow,
                "knowledge_runtime_digest": provenance.knowledge_runtime_digest,
                "profile": provenance.profile,
                "profile_version": provenance.profile_version,
                "profile_digest": provenance.profile_digest,
                "definition_version": provenance.definition_version,
                "rule_bundle": provenance.rule_bundle,
                "rule_bundle_version": provenance.rule_bundle_version,
                "rule_bundle_digest": provenance.rule_bundle_digest,
            },
        }


def strongest(dispositions: list[Disposition]) -> Disposition:
    """The deterministic precedence: ESCALATE > BLOCK > UNKNOWN > WARN > ALLOW."""
    return max(dispositions, key=lambda d: RANK[d], default="allow")
