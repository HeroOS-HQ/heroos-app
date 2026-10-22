"""One founder turn through the gateway: readiness, limits, two phases, checks and fallbacks.

``AiGateway.respond`` runs, in order:

1. **Readiness** (no model request otherwise): enabled, a provider and model,
   the provider's key, the deployment's approval reference, an installed
   knowledge bundle (``knowledge_unavailable`` short-circuits: no model
   request, no general answer), and production-approved knowledge unless
   development knowledge is explicitly allowed (never in production).
2. **Usage limits** (``app.assistant.limits``): per account and service-wide.
3. **One execution snapshot** (M2-NEW-06): the knowledge, rules, definitions
   and execution profile the whole turn uses, taken once; no turn mixes two
   versions.
4. **Understanding**: one request (and at most one schema repair); the
   founder's own messages only. Facts and requested decisions are kept only
   with real evidence; readings the founder's own words contradict establish
   nothing.
5. **Routing** without a model: another HR matter, a non-HR request, a request
   for HeroOS's internal material and an unclear message each get a fixed
   reply (no second request); so do an unsupported or conflicting knowledge
   result.
6. **Retrieval and planning** (``planning``): ``get_knowledge_context`` with the
   validated route, the Blueprint's jurisdiction and the established facts;
   the server's question targets and the decisions asked about.
7. **Deterministic evaluation** (``app.evaluation``, M2-NEW-06): the trusted
   facts (only ENGINE_TRUSTED values enter a rule), the bound Conditions and
   the requested decisions' results, and the one outcome (Guidance, Warning,
   Block, Expert Review) the server owns. The model never decides it.
8. **Grounded response**: one request (and at most one schema repair) on the
   minimized knowledge view and the decided outcome; then the grounding,
   reply-safety and contradiction checks. A reply that fails, or a second
   invalid output, is replaced by a reply the server composes from fixed text
   and the deterministic result (never from the model). If the provider fails
   after a Warning, Block or Expert Review was decided, the server still
   answers with it: AI availability never weakens a deterministic result.

At most four provider requests per founder turn, inside one time budget.
A provider failure is never retried and never answered by anything else.

**The Case's workflow position (M2-NEW-08).** A persisted conversation with a
Case passes its authoritative position (``CaseContext``, built by
``app.conversations.progress`` from the Case's own records): the deterministic
evaluation reads it as input (an employer decision's prerequisite may need a
completed stage or a stage checklist answer), and the response phase reads a
labels-only view of it (``case_progress``) so HeroOS can say where the Case
stands. It is read-only: nothing here selects a pathway, starts or completes a
stage or records anything; the employer does that in the Case.

**A greeting** ("Hi Hannah") gets a friendly fixed reply with no model request:
there is nothing to understand or evaluate yet, and no Case is created.

The result carries a ``Handoff`` (server-side only: never sent to the browser)
with the understanding, the deterministic evaluation and the snapshot the turn
used, and the next trusted state (``GatewayReply.next_state``), for the
persistence that follows (M2-NEW-07, ``app.conversations``). A persisted
conversation starts each turn from its server-side state (``FounderTurn.resume``)
instead of the browser's continuation; the trust rules are the same.
"""

import dataclasses
import logging
import re
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Literal

from app.assistant.gateway.catalog import EMPTY_CATALOG, RoutingCatalog, routing_catalog
from app.assistant.gateway.grounding import check_grounding, internal_labels
from app.assistant.gateway.memory import (
    JURISDICTION as MEMORY_JURISDICTION,
)
from app.assistant.gateway.memory import (
    MAX_UNANSWERED,
    ConversationMemory,
    carry,
    conversation_view,
    record,
    resolve,
    said_values,
)
from app.assistant.gateway.planning import QuestionTarget, TurnPlan, plan_turn
from app.assistant.gateway.projection import (
    JURISDICTION_NAMES,
    company_text,
    company_view,
    knowledge_view,
)
from app.assistant.gateway.prompts import (
    LIGHT_INSTRUCTION,
    RESPONSE_INSTRUCTION,
    UNDERSTANDING_INSTRUCTION,
    data_message,
    regeneration_turns,
    repair_turns,
)
from app.assistant.gateway.proposals import (
    ProposalError,
    ResponseProposal,
    UnderstandingProposal,
    check_evidence,
    parse_response,
    parse_understanding,
    sentence_of,
    without_contradicted,
)
from app.assistant.limits import UsageLimits
from app.assistant.provider import AssistantError, ChatTurn, Completion, StructuredChatProvider
from app.assistant.response_safety import gateway_problem
from app.companies.blueprint import CompanyBlueprintContext
from app.evaluation.continuation import ContinuationCodec, ContinuationState, ReadResult
from app.evaluation.evaluator import (
    ConversationEvaluationService,
    EvaluationRequest,
)
from app.evaluation.facts import (
    NOT_SURE,
    Asked,
    PriorState,
    StatedFact,
    TrustOutcome,
    canonical,
    contradicted,
    says_not_known,
    trust_facts,
)
from app.evaluation.model import (
    CaseProgress,
    ConversationEvaluation,
    Matter,
    MissingRequirement,
    TrustedFactState,
)
from app.evaluation.presentation import (
    Outcome,
    fallback_reply,
    next_step_text,
    outcome,
    outcome_contradiction,
    outcome_view,
    requirement_question,
)
from app.evaluation.snapshot import (
    ExecutionSnapshot,
    WorkflowExecution,
    knowledge_only_runtime,
)
from app.knowledge.bundle import KnowledgeBundle
from app.knowledge.context import KnowledgeStatus

logger = logging.getLogger(__name__)

TURN_SECONDS: Final = 40.0
CALL_SECONDS: Final = 20.0
MIN_CALL_SECONDS: Final = 3.0
MAX_PROVIDER_CALLS: Final = 4
UNDERSTANDING_TOKENS: Final = 1200
RESPONSE_TOKENS: Final = 1200
LIGHT_TOKENS: Final = 400
UNDERSTANDING_TEMPERATURE: Final = 0.0
RESPONSE_TEMPERATURE: Final = 0.2
# The founder's earlier messages the understanding phase sees (newest kept first).
MAX_FOUNDER_TURNS: Final = 6
MAX_FOUNDER_CHARS: Final = 6000
# The recent conversation the response phase sees.
MAX_CONVERSATION_TURNS: Final = 6
MAX_CONVERSATION_CHARS: Final = 6000
# HeroOS's last reply, for the understanding phase (what was actually asked).
MAX_PREVIOUS_REPLY_CHARS: Final = 1500

GatewayReason = Literal["disabled", "not_configured", "knowledge_unavailable"]
FailureKind = Literal[
    "not_configured", "knowledge_unavailable", "rate_limited", "timeout", "unavailable",
    "invalid_output",
]  # fmt: skip
# How the turn was handled, for the browser. Deliberately not an outcome: the outcome
# (Guidance, Warning, Block, Expert Review) is the server's deterministic ``outcome``.
ConversationState = Literal["responded", "clarifying", "outside_approved_guidance"]
MATTERS: Final[Mapping[str, Matter]] = {
    "supported_hr": "supported",
    "other_hr": "unsupported_hr",
    "unsupported": "outside_product_scope",
    "unclear": "unclear",
    "confidential_request": "confidential_request",
    # Thanks, a goodbye, a reaction or a question about HeroOS itself: nothing to evaluate.
    "conversational": "unclear",
}
# Outcomes a failed or replaced model reply must never hide.
SAFETY_OUTCOMES: Final = frozenset({"warning", "block", "expert_review"})

DEVELOPMENT_NOTICE: Final = (
    "Preview: HeroOS's guidance content is still in development and not yet approved for "
    "production use. Use fictional scenarios only."
)

OUTSIDE_HR: Final = (
    "That's an HR matter HeroOS's approved guidance doesn't cover yet, so I won't guess at an "
    "answer. HeroOS's approved guidance currently covers: {coverage}. For this, a qualified HR or "
    "employment specialist is the right person to speak to. If there's a conduct or "
    "disciplinary side to it, tell me about that and I can help."
)
OUTSIDE: Final = (
    "That's outside what HeroOS can help with, so I won't offer a general answer. HeroOS helps "
    "employers with workplace HR situations; its approved guidance currently covers: "
    "{coverage}. If you have a workplace conduct or disciplinary situation, tell me about it in "
    "your own words."
)
CONFIDENTIAL: Final = (
    "I can't share HeroOS's internal instructions, rules or source materials. I can help with a "
    "specific workplace situation using HeroOS's approved guidance: tell me what's happening, "
    "in your own words."
)
UNCLEAR: Final = (
    "Tell me a little more about what's happening at work, in your own words: who's involved "
    "and what happened. Then I can see how HeroOS's approved guidance can help."
)
CONVERSATIONAL: Final = (
    "Thanks. I'm here whenever you want to talk through a workplace conduct or disciplinary "
    "situation."
)
# The same refusal again, shorter: the founder already read the full one (found live: the
# fixed text repeated word for word to every follow-up).
OUTSIDE_HR_AGAIN: Final = (
    "That one is still outside HeroOS's approved guidance, so a qualified HR or employment "
    "specialist is the right person for it. If there's a conduct or disciplinary side to it, "
    "I can help with that."
)
OUTSIDE_AGAIN: Final = (
    "That's still outside what HeroOS can help with, so I'll leave that one there. If a "
    "workplace conduct or disciplinary situation comes up, tell me about it and we can work "
    "through it."
)
# What HeroOS is, for a reply to a question about HeroOS itself (no approved guidance in it).
SCOPE: Final = (
    "HeroOS helps employers in the United Arab Emirates handle workplace conduct and "
    "disciplinary matters fairly and step by step, using approved guidance for the company's "
    "confirmed employment jurisdiction (UAE Federal or DIFC). One conversation is one case: "
    "the founder describes what happened, HeroOS asks what it needs, explains what the "
    "approved guidance says and which safeguards apply, and the employer makes every decision "
    "and takes every formal step in the case. HeroOS doesn't give general legal advice, "
    "can't take actions for the employer and doesn't prepare or send documents."
)
GREETING: Final = (
    "Hi! What can HR help you with today? Tell me what's happening at work in your own words."
)
# A message that is only a greeting ("Hi Hannah", "Good morning!"): nothing to understand yet.
_GREETING: Final = re.compile(
    r"^(?:(?:hi|hello|hey|hiya|howdy|greetings|yo|salam|salaam|marhaba|ahlan"
    r"|assalamu?\s+alaikum|as-?salamu\s+alaikum|good\s+(?:morning|afternoon|evening|day))"
    r"(?:\s+(?:there|again|all|everyone|team|hannah|heroos|hero\s+os))*"
    r"(?:\s+[a-z]+)?"
    r"(?:\s+how\s+are\s+you(?:\s+(?:doing|today))?)?)$"
)


def is_greeting(message: str) -> bool:
    """The message is only a greeting (at most a name after it): no HR situation in it yet."""
    words = re.sub(r"[^\w\s'-]", " ", message.casefold()).split()
    return 0 < len(words) <= 7 and _GREETING.match(" ".join(words)) is not None


SOURCE_CONFLICT: Final = (
    "HeroOS can't safely guide this specific question yet: the approved material behind it is "
    "still being reviewed, and I won't choose between versions of it. A qualified employment "
    "specialist should look at this part. Is there another side of the situation I can help "
    "you think through?"
)
NO_APPROVED_CONTENT: Final = (
    "HeroOS's approved guidance doesn't cover this part of the situation, so I won't guess. A "
    "qualified employment specialist is the right person for it. Is there another side of the "
    "situation I can help you think through?"
)
FALLBACK_LEADS: Final[dict[str, str]] = {
    "claim": (
        "To be clear, I can't take actions for you: I can't update a case, prepare or send "
        "documents, arrange a specialist review or track deadlines."
    ),
    "outcome": (
        "I can't recommend or authorize a disciplinary outcome: that decision stays with you, "
        "after a fair process and any review HeroOS's approved guidance requires."
    ),
    "legal": "I can't state legal specifics here beyond HeroOS's approved guidance.",
    "invalid": (
        "I couldn't put together a reliable answer from HeroOS's approved guidance just now."
    ),
    "provider": "",
    # M2-NEW-07: the case changed while this answer was prepared (commit-time reconciliation).
    "changed": "This case changed while I was answering, so here is HeroOS's current result.",
}
FALLBACK_FAMILY: Final[dict[str, str]] = {
    "action_claim": "claim",
    "document_claim": "claim",
    "review_promise": "claim",
    "monitoring_promise": "claim",
    "authorization": "outcome",
    "sanction_recommendation": "outcome",
    "procedural_certainty": "outcome",
    "legal_certainty": "legal",
    "jurisdiction_certainty": "legal",
    "misconduct_finding": "outcome",
    "contradicts_hold": "outcome",
    "contradicts_review": "outcome",
    "contradicts_caution": "outcome",
}
OPEN_QUESTION: Final = "What would you like to work through next?"
QUESTION_WORDS: Final = frozenset({"whether", "what", "which", "how", "when", "who", "where", "if"})
ASKED_LABELS: Final[Mapping[str, str]] = {
    "insistence": "whether they still intend to go ahead with a step despite HeroOS's caution",
    "jurisdiction": (
        "whether this employee is employed under the company's confirmed employment jurisdiction"
    ),
}


class GatewayFailure(Exception):
    """No reply for this turn. ``kind`` is all a caller may show."""

    def __init__(self, kind: FailureKind, *, retry_after: int | None = None) -> None:
        super().__init__(kind)
        self.kind: FailureKind = kind
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class CaseContext:
    """The attached Case's authoritative workflow position for one turn (M2-NEW-08).

    Built from the Case's own records (never from the conversation) by
    ``app.conversations.progress``. Read-only for the AI: the model can describe
    it, never change it; the employer changes it through the Case's controls.
    """

    # The evaluation's input: completed stages and checklist answers, per jurisdiction.
    progress: CaseProgress
    # The labels-only view the response phase reads (``case_progress``): never an id, a rule,
    # a raw row or an answer value.
    view: Mapping[str, object]
    # The view's texts (stage titles, pathway labels), for the grounding check.
    texts: tuple[str, ...] = ()
    # What a reply's wording about the Case rests on (``AiGateway.reconcile``).
    signature: tuple[object, ...] = ()
    # The decisions currently needing Expert Review (option ids; titled from the turn's
    # snapshot), and whether the matter as a whole does.
    reviews: tuple[str, ...] = ()
    matter_review: bool = False
    # Chat-first: the Case's open intake questions the conversation can collect (definition
    # question keys, in order). HeroOS may ask about them; it never has to.
    open_questions: tuple[str, ...] = ()

    def model_view(self, knowledge: KnowledgeBundle) -> tuple[dict[str, object], tuple[str, ...]]:
        """The view the response phase reads, and its texts (for the grounding check)."""
        titles = {o.id: o.title for o in knowledge.options}
        held = [titles.get(a, "A decision you asked about") for a in self.reviews]
        if self.matter_review:
            held.append("The matter as a whole")
        return {**self.view, "decisions_needing_expert_review": held}, (*self.texts, *held)


@dataclass(frozen=True, slots=True)
class FounderTurn:
    message: str
    # Recent conversation, oldest first, both roles: as the browser holds it (untrusted), or
    # as a persisted conversation stored it.
    history: tuple[ChatTurn, ...] = ()
    continuation: str | None = None
    # A persisted conversation's trusted state for this turn's snapshot (M2-NEW-07); it
    # replaces the continuation, which is then not read.
    resume: Callable[[ExecutionSnapshot], ReadResult] | None = None
    # M2-NEW-08: the attached Case's workflow position (None: no Case).
    case: CaseContext | None = None
    # Chat-first Case: what the founder already said that the Case could hold (the conversation's
    # noted readings, Case question key -> canonical value). Already said, so never asked again
    # (and noted again until saved or contradicted); never trusted.
    noted: Mapping[str, str] = field(default_factory=dict)
    # What the conversation already covered (``memory``): said, not known, asked. Never trusted.
    memory: ConversationMemory = field(default_factory=ConversationMemory)


@dataclass(frozen=True, slots=True)
class EstablishedFact:
    key: str
    value: str
    provenance: str
    turn: int | None


@dataclass(frozen=True, slots=True)
class Handoff:
    """The understanding and the deterministic result. Server-side only; never persisted here."""

    intent: str
    workflow: str | None
    pathway_candidate: str | None
    topics: tuple[str, ...]
    established: tuple[EstablishedFact, ...]
    # Facts the founder hinted at without stating them (to confirm, never relied on).
    tentative: tuple[str, ...]
    uncertainties: tuple[str, ...]
    summary: str | None
    knowledge_status: str | None
    jurisdiction: str | None
    # The decisions asked about that the approved content routes to specialist review.
    review_required: tuple[str, ...]
    asked: tuple[str, ...]
    runtime_bundle_digest: str | None
    # M2-NEW-06: the employer decisions the founder asked about (option ids).
    requested_actions: tuple[str, ...] = ()
    # M2-NEW-06: the deterministic evaluation (``ConversationEvaluation.record()`` for M2-NEW-07).
    evaluation: ConversationEvaluation | None = None
    # M2-NEW-07: the one snapshot the whole turn used (its executions, knowledge and identity).
    snapshot: ExecutionSnapshot | None = None
    # M2-NEW-07: the decisions the founder explicitly withdrew in this message (option ids).
    withdrawn_actions: tuple[str, ...] = ()
    # M2-NEW-08: the decisions asked about only hypothetically (evaluated, never intended).
    hypothetical_actions: tuple[str, ...] = ()


@dataclass(slots=True)
class Telemetry:
    """Operational facts only: never a message, fact, value, reply, prompt or knowledge text."""

    provider: str
    model: str
    calls: int = 0
    repairs: list[str] = field(default_factory=list)
    knowledge_status: str = "-"
    safety: str = "ok"
    grounding: str = "ok"
    facts_rejected: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    outcome: str = "ok"
    # M2-NEW-06 (bounded categories and counts only).
    workflow: str = "-"
    evaluation: str = "-"
    presentation: str = "-"
    dispositions: str = "-"
    engine_trusted: int = 0
    conversational_untrusted: int = 0
    profile: str = "-"
    rule_bundle: str = "-"
    continuation: str = "none"
    evaluation_us: int = 0
    wording: str = "model"


@dataclass(frozen=True, slots=True)
class TurnBasis:
    """What the reply was decided on, to re-run only the deterministic part (server-side only)."""

    snapshot: ExecutionSnapshot
    understanding: UnderstandingProposal
    # The evaluation the reply's wording rests on.
    result: "_Turn"
    # The plan the reply used (None for a routed turn) and the questions it asked.
    plan: TurnPlan | None
    asked: tuple[QuestionTarget, ...]
    # The reply is fixed text (a routed turn or no approved content), not the model's words.
    fixed: bool


@dataclass(frozen=True, slots=True)
class GatewayReply:
    reply: str
    safe_next_step: str | None
    state: ConversationState
    continuation: str
    handoff: Handoff
    # The deterministic outcome (server-owned); None when there is nothing to show.
    outcome: Outcome | None = None
    # The trusted state the next turn starts from (what ``continuation`` carries, unsealed).
    next_state: ContinuationState | None = None
    basis: TurnBasis | None = field(default=None, repr=False, compare=False)
    # What the conversation covered after this turn (a persisted conversation keeps it).
    memory: ConversationMemory = field(default_factory=ConversationMemory)


Reconciliation = Literal["kept", "refreshed", "relaxed", "held"]
# Why a weaker result at commit is less certain, not authoritative (``AiGateway.reconcile``).
Uncertainty = Literal["unavailable", "trust_lost", "jurisdiction", "fact_lost", "unverifiable"]
# How strict an outcome is: uncertainty may never weaken one (``AiGateway.reconcile``).
STRICTNESS: Final[Mapping[str | None, int]] = {
    None: 0, "unavailable": 0, "guidance": 0, "warning": 1, "block": 2, "expert_review": 3,
}  # fmt: skip


class _Deadline:
    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._end = clock() + TURN_SECONDS

    def call_timeout(self) -> float:
        remaining = self._end - self._clock()
        if remaining < MIN_CALL_SECONDS:
            raise GatewayFailure("timeout")
        return min(CALL_SECONDS, remaining)


@dataclass(frozen=True, slots=True)
class _SnapshotView:
    """What the gateway derives from one snapshot's knowledge (built once per snapshot)."""

    catalog: RoutingCatalog
    labels: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class _Turn:
    """Everything the reply and the next continuation need from this turn's evaluation."""

    evaluation: ConversationEvaluation
    card: Outcome | None
    trust: TrustOutcome | None
    prior: PriorState
    reconfirm: bool
    # M2-NEW-08: the Case position the reply's wording rests on.
    case: tuple[object, ...] = ()
    # What the conversation covered, after the founder's message (before HeroOS's reply).
    memory: ConversationMemory = field(default_factory=ConversationMemory)


def _label(target: QuestionTarget) -> str:
    return re.sub(r"\s*\([^)]*\)", "", target.label).strip().rstrip(".")


def target_question(target: QuestionTarget) -> str:
    """A plain question about a target, for a reply the server composes."""
    if target.question is not None:
        return target.question
    label = _label(target)
    lead = "Could you confirm" if target.mode == "confirm" else "Could you tell me"
    text = label[:1].lower() + label[1:]
    if label.split(" ", 1)[0].lower() in QUESTION_WORDS:
        return f"{lead} {text}?"
    return f"{lead} more about this: {text}?"


def _signature(result: "_Turn") -> tuple[object, ...]:
    """What a reply's wording rests on: the outcome, what is missing and the jurisdiction."""
    evaluation = result.evaluation
    return (
        result.card,
        evaluation.availability,
        evaluation.presentation,
        evaluation.next_step,
        evaluation.jurisdiction_state,
        tuple((a.action, a.disposition) for a in evaluation.actions),
        tuple((m.key, m.kind, m.candidate) for m in evaluation.missing),
        result.case,
    )


MAX_CASE_TARGETS: Final = 2


def _case_targets(
    execution: WorkflowExecution,
    case: CaseContext | None,
    evaluation: ConversationEvaluation,
    planned: Sequence[QuestionTarget],
    unanswered: Collection[str] = (),
) -> tuple[QuestionTarget, ...]:
    """Optional targets for the Case's open intake questions (never one the founder answered
    or already said, never one asked last turn that the reply didn't answer, and never twice):
    the reply may ask about one, in its own words."""
    if case is None:
        return ()
    facts = evaluation.facts
    # Never what the founder already said only approximately ("last week"): an optional question
    # asking for more precision reads as asking again (found live).
    known = {
        *facts.engine, *facts.conversational, *facts.proposed, *(t.fact_key for t in planned),
        *unanswered,
    }  # fmt: skip
    targets: list[QuestionTarget] = []
    for question in case.open_questions:
        key = execution.question_facts.get(question, question)
        schema = execution.schemas.get(key)
        if schema is None or schema.kind == "blueprint" or key in known:
            continue
        targets.append(QuestionTarget(f"c{len(targets) + 1}", key, schema.label, "ask"))
        if len(targets) == MAX_CASE_TARGETS:
            break
    return tuple(targets)


def _asked_again(result: "_Turn", requirement: MissingRequirement) -> bool:
    """Whether HeroOS asked exactly this fact last turn and the founder's reply didn't answer it.

    Not the insistence question of a two-state caution: it is part of its safeguard's protocol and
    is asked again. The jurisdiction question is a question for information too (found live: the
    founder said "his contract is with the DIFC company" and was asked it again at once, twice);
    while it is unresolved its safeguard holds the steps, asked or not.
    """
    if result.trust is None or result.trust.answered:
        return False
    kind = {"fact": "fact", "confirmation": "confirm", "jurisdiction": "jurisdiction"}.get(
        requirement.kind
    )
    return kind is not None and any(
        a.kind == kind and a.key == requirement.key for a in result.prior.asked
    )


def _settled(result: "_Turn") -> frozenset[str]:
    """What HeroOS never asks again this turn: trusted, said (or noted), not known, answered,
    or not answered too often (``ConversationMemory.settled``)."""
    facts = result.evaluation.facts
    return result.memory.settled() | frozenset(facts.engine) | frozenset(facts.conversational)


def _ignored(result: "_Turn", requirement: MissingRequirement) -> bool:
    """Whether the founder already said they don't know this, or left it unanswered too often.

    The requirement stays (its safeguard still holds the step); only the question stops: HeroOS
    may say why it matters, never append the same question again. The jurisdiction question
    counts as answered once the founder replied to it in any way the server could read.
    """
    if requirement.kind not in ("fact", "confirmation", "jurisdiction"):
        return False
    key = MEMORY_JURISDICTION if requirement.kind == "jurisdiction" else requirement.key
    asked = result.memory.asked.get(key)
    if asked is None:
        return False
    if asked.last == "not_sure" or (
        asked.last == "answered" and requirement.kind == "jurisdiction"
    ):
        return True
    return asked.last == "unanswered" and asked.times >= MAX_UNANSWERED


def _strictness(result: "_Turn") -> int:
    return STRICTNESS[None if result.card is None else result.card.kind]


def _for_employee(
    bundle: KnowledgeBundle, understanding: UnderstandingProposal,
    company: CompanyBlueprintContext, plan: TurnPlan, result: "_Turn",
    known: frozenset[str] = frozenset(),
) -> TurnPlan:  # fmt: skip
    """The plan again, shared guidance only, when this employee's jurisdiction is unresolved.

    The knowledge request runs before the evaluation, under the Company's
    confirmed jurisdiction; the evaluation may then find that it doesn't apply
    to this employee ("Not sure", another jurisdiction, an outdated Case
    confirmation). No jurisdiction-specific text then reaches the model.
    """
    unresolved = result.evaluation.jurisdiction_state in ("case_not_sure", "case_different")
    if not unresolved or plan.query.jurisdiction is None:
        return plan
    return plan_turn(bundle, understanding, company, employee_unresolved=True, known=known)


def uncertainty(fresh: "_Turn", prepared: "_Turn") -> Uncertainty | None:
    """Why ``fresh`` rests on less certain state than ``prepared`` (None: it doesn't).

    A weaker result at commit is authoritative only when nothing it rests on
    became less certain: the checks are ready, no trusted state was lost, a
    resolved jurisdiction is still the same resolved one, every trusted fact is
    still trusted (and not "Not sure"), and no safeguard that applied became
    unknown. A recorded prerequisite or a changed trusted value is authoritative.
    """
    now, then = fresh.evaluation, prepared.evaluation
    if now.availability != "ready":
        return "unavailable"
    if fresh.reconfirm and not prepared.reconfirm:
        return "trust_lost"
    if then.jurisdiction_state == "resolved" and (
        now.jurisdiction_state != "resolved" or now.jurisdiction != then.jurisdiction
    ):
        return "jurisdiction"
    for key, value in then.facts.engine.items():
        current = now.facts.engine.get(key)
        if current is None or (current == NOT_SURE and value != NOT_SURE):
            return "fact_lost"
    fired = {c.condition for c in then.conditions if c.status == "fired"}
    undecided = ("unknown", "unavailable", "not_evaluated")
    if any(c.condition in fired and c.status in undecided for c in now.conditions):
        return "unverifiable"
    before = {a.action: a.disposition for a in then.actions}
    if any(a.disposition == "unknown" and before.get(a.action) != "unknown" for a in now.actions):
        return "unverifiable"
    return None


def _recent_founder_messages(turn: FounderTurn) -> list[str]:
    kept: list[str] = []
    budget = MAX_FOUNDER_CHARS
    for item in reversed(turn.history):
        if item.role != "user":
            continue
        budget -= len(item.content)
        if budget < 0 or len(kept) == MAX_FOUNDER_TURNS:
            break
        kept.append(item.content)
    kept.reverse()
    return [*kept, turn.message]


def _recent_conversation(turn: FounderTurn) -> list[dict[str, str]]:
    kept: list[dict[str, str]] = []
    budget = MAX_CONVERSATION_CHARS
    for item in reversed(turn.history):
        budget -= len(item.content)
        if budget < 0 or len(kept) == MAX_CONVERSATION_TURNS:
            break
        kept.append({"from": "founder" if item.role == "user" else "heroos", "text": item.content})
    kept.reverse()
    return kept


def _previous_founder_message(turn: FounderTurn) -> str | None:
    return next((t.content for t in reversed(turn.history) if t.role == "user"), None)


def snapshot_versions(snapshot: ExecutionSnapshot) -> str:
    """The identity a continuation is bound to: the knowledge and the execution profile."""
    knowledge = "-" if snapshot.knowledge is None else snapshot.knowledge.runtime_digest
    profile = "-" if snapshot.profile is None else snapshot.profile.digest
    return f"{knowledge}|{profile}"


def _with_noted(
    execution: WorkflowExecution,
    facts: TrustedFactState,
    noted: Mapping[str, str],
    carried: Mapping[str, str] | None = None,
    hedged: Collection[str] = (),
) -> TrustedFactState:
    """The conversation's noted readings, and what the founder said earlier (``carried``,
    from the conversation's memory), count as said (ESTABLISHED_CONVERSATIONAL), never trusted.

    Found live: a reading noted on one turn and not re-proposed by the next turn's understanding
    was asked for again, and dropped from the noted list; a fact said early in a long
    conversation was asked again once the understanding no longer saw that message. The
    founder's newest statement still wins: a key this turn read, trusts, or hedges is left as it
    is (a correction that reduces certainty reduces it).
    """
    said = dict(facts.conversational)
    for key, value in (carried or {}).items():
        if key not in said and key not in facts.engine and key not in hedged:
            said[key] = value
    for question_key, value in noted.items():
        schema = next(
            (s for s in execution.schemas.values() if question_key in (s.key, s.question)), None
        )
        if schema is None or schema.key in said or schema.key in facts.engine:
            continue
        if schema.key in hedged:
            continue
        said[schema.key] = value
    if len(said) == len(facts.conversational):
        return facts
    return dataclasses.replace(facts, conversational=dict(sorted(said.items())))


def _fact_labels(snapshot: ExecutionSnapshot, bundle: KnowledgeBundle) -> dict[str, str]:
    """Fact key -> label: the knowledge's, else (a Case question) the schema's own."""
    labels = {f.key: f.label for f in bundle.facts}
    for execution in snapshot.workflows.values():
        labels.update({k: s.label for k, s in execution.schemas.items() if k not in labels})
    return labels


_SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+")


def _previous_reply(turn: FounderTurn) -> str | None:
    """HeroOS's last reply (as the conversation holds it), bounded."""
    text = next((t.content for t in reversed(turn.history) if t.role != "user"), None)
    return None if text is None else text[:MAX_PREVIOUS_REPLY_CHARS]


def _previous_question(turn: FounderTurn) -> str | None:
    """The question(s) HeroOS's last reply ended with: what the founder's message may answer.

    Only the trailing question, never HeroOS's statements: a claim HeroOS made is never
    something the understanding phase reads (it can't become the founder's fact).
    """
    reply = _previous_reply(turn)
    if reply is None:
        return None
    sentences = [s for s in _SENTENCE_END.split(reply.strip()) if s]
    asked: list[str] = []
    while sentences and sentences[-1].rstrip().endswith("?") and len(asked) < 2:
        asked.insert(0, sentences.pop())
    return " ".join(asked) or None


def _continued(
    snapshot: ExecutionSnapshot, read: ReadResult, understanding: UnderstandingProposal
) -> UnderstandingProposal:
    """A message with no matter of its own in a conversation that has one continues it.

    Found live: "ok", "sort of", "thats about it" or "thanks" in the middle of a disciplinary
    matter were read as unclear (or as unsupported) and got a fixed "tell me what's happening"
    paragraph, word for word, as if the matter had never been described. Nothing new is
    trusted here: the matter's own evaluation runs on its trusted state, and the reply answers
    what the founder said. A new HR matter or a request outside HeroOS is never continued.
    """
    ongoing = None if read.state is None else read.state.workflow
    if ongoing is None or snapshot.execution(ongoing) is None:
        return understanding
    no_matter = understanding.intent in ("unclear", "conversational") or (
        understanding.intent == "supported_hr" and understanding.workflow is None
    )
    if not no_matter:
        return understanding
    return dataclasses.replace(
        understanding,
        intent="supported_hr",
        workflow=ongoing,
        pathway=None,
        topics=(),
        continued=True,
    )


def _known(
    snapshot: ExecutionSnapshot, understanding: UnderstandingProposal, read: ReadResult,
    turn: FounderTurn,
) -> frozenset[str]:  # fmt: skip
    """What the conversation already covered beyond this turn's understanding (for planning)."""
    known = set(turn.memory.settled()) | (set() if read.state is None else set(read.state.engine))
    execution = snapshot.execution(understanding.workflow) if understanding.workflow else None
    if execution is not None:
        known |= {execution.question_facts.get(q, q) for q in turn.noted}
    return frozenset(known)


# A sentence announcing the question that follows ("HeroOS will ask you next whether ..."): the
# question itself is what follows (found live: the announcement, then the same question).
_ANNOUNCES: Final = re.compile(
    r"\b(?:heroos|i)\s+(?:will|'ll|is\s+going\s+to|am\s+going\s+to)\s+(?:now\s+|also\s+)?"
    r"(?:ask|need\s+to\s+ask|follow\s+up)\b|\b(?:next|one\s+more|following)\s+question\b",
    re.IGNORECASE,
)


_LEAD_IN: Final = re.compile(r"(?:[,:]|\b(?:so|and|then))$", re.IGNORECASE)


def _with_question(reply: str, question: str) -> str:
    """The reply with the server's question as its one question (its own trailing questions
    are left out: the server's wording is what the founder's answer is read against)."""
    sentences = [s for s in _SENTENCE_END.split(reply.strip()) if s and not _ANNOUNCES.search(s)]
    while sentences and sentences[-1].rstrip().endswith("?"):
        sentences.pop()
    kept = " ".join(sentences).rstrip()
    if not kept:
        return question
    if _LEAD_IN.search(kept):
        # "..., so" or "...:" leads into the question (found live: "... so Has a sanction ...?").
        return f"{kept} {question[:1].lower()}{question[1:]}"
    if kept[-1] not in ".!?":
        kept += "."
    return f"{kept} {question}"


def _noted_facts(execution: WorkflowExecution, noted: Mapping[str, str]) -> dict[str, str]:
    """The noted readings by fact key (they are kept by Case question key)."""
    facts: dict[str, str] = {}
    for question_key, value in noted.items():
        schema = next(
            (s for s in execution.schemas.values() if question_key in (s.key, s.question)), None
        )
        if schema is not None:
            facts[schema.key] = value
    return facts


def _corrects(
    execution: WorkflowExecution,
    understanding: UnderstandingProposal,
    current: int,
    earlier: Mapping[str, str],
) -> bool:
    """Whether the current message corrects something said before: it states another value for a
    fact the conversation holds, or the understanding reads conflicting statements."""
    if "conflicting_statements" in understanding.uncertainties:
        return True
    for proposal in understanding.facts:
        before = earlier.get(proposal.fact_key)
        schema = execution.schemas.get(proposal.fact_key)
        if proposal.source_turn != current or before is None or schema is None:
            continue
        if canonical(schema, proposal.value) not in (None, canonical(schema, before)):
            return True
    return False


def _blueprint_values(company: CompanyBlueprintContext) -> dict[str, object]:
    return {
        "employee_count": company.employee_count,
        "industry": company.industry,
        "policies_exist": company.policies_exist,
        "hr_support": company.hr_support,
    }


class AiGateway:
    def __init__(
        self,
        *,
        enabled: bool,
        provider: StructuredChatProvider | None,
        bundle: KnowledgeBundle | None = None,
        approval: str | None,
        allow_development_knowledge: bool,
        limits: UsageLimits,
        clock: Callable[[], float] = time.monotonic,
        evaluation: ConversationEvaluationService | None = None,
        continuations: ContinuationCodec | None = None,
    ) -> None:
        self.enabled = enabled
        self.provider = provider
        self.approval = approval
        self.allow_development_knowledge = allow_development_knowledge
        self.limits = limits
        self._clock = clock
        self._evaluation = evaluation or ConversationEvaluationService(
            knowledge_only_runtime(bundle)
        )
        self._codec = continuations or ContinuationCodec(None)
        self._views: dict[str, _SnapshotView] = {}

    # --- the snapshot ---------------------------------------------------------------------

    def snapshot(self) -> ExecutionSnapshot:
        """The current execution snapshot (status reads; a turn takes its own once)."""
        return self._evaluation.snapshot()

    @property
    def bundle(self) -> KnowledgeBundle | None:
        """The current snapshot's knowledge (readiness only; a turn uses its own snapshot)."""
        return self._evaluation.snapshot().knowledge

    @property
    def catalog(self) -> RoutingCatalog:
        return self._view(self._evaluation.snapshot()).catalog

    def _view(self, snapshot: ExecutionSnapshot) -> _SnapshotView:
        view = self._views.get(snapshot.id)
        if view is None:
            bundle = snapshot.knowledge
            schemas = [s for e in snapshot.workflows.values() for s in e.schemas.values()]
            # A Case-backed fact's question, in the case's own words.
            prompts = {
                s.key: question.prompt
                for e in snapshot.workflows.values()
                for s in e.schemas.values()
                if s.question is not None
                and (question := e.definition.question(s.question)) is not None
            }
            view = _SnapshotView(
                catalog=EMPTY_CATALOG
                if bundle is None
                else routing_catalog(
                    bundle,
                    # Chat-first: the Case's own intake questions are facts the founder may state.
                    case_facts={s.key: s.label for s in schemas if s.key == s.question},
                    options={
                        s.key: tuple(o.value for o in s.options)
                        for s in schemas
                        if s.kind in ("yes_no", "choice")
                    },
                    questions=prompts,
                ),
                labels=internal_labels(bundle) if bundle is not None else re.compile(r"(?!x)x"),
            )
            self._views = {snapshot.id: view}
        return view

    # --- readiness ----------------------------------------------------------------------

    @property
    def development_knowledge(self) -> bool:
        bundle = self.bundle
        return bundle is not None and (
            bundle.approval != "approved" or bundle.provenance != "private"
        )

    @property
    def missing(self) -> tuple[str, ...]:
        """The prerequisites that keep an enabled gateway unavailable (names only)."""
        missing = []
        if self.provider is None:
            missing.append("provider")
        if self.approval is None:
            missing.append("approval")
        if self.bundle is None:
            missing.append("knowledge")
        elif self.development_knowledge and not self.allow_development_knowledge:
            missing.append("approved_knowledge")
        return tuple(missing)

    @property
    def reason(self) -> GatewayReason | None:
        """Why the gateway can't answer here; None when it can."""
        if not self.enabled:
            return "disabled"
        missing = self.missing
        if any(m in missing for m in ("provider", "approval", "approved_knowledge")):
            return "not_configured"
        if "knowledge" in missing:
            return "knowledge_unavailable"
        return None

    @property
    def notice(self) -> str | None:
        return DEVELOPMENT_NOTICE if self.development_knowledge else None

    # --- one turn ---------------------------------------------------------------------

    def respond(self, company: CompanyBlueprintContext, turn: FounderTurn) -> GatewayReply:
        reason = self.reason
        if reason == "knowledge_unavailable":
            # Never a model request without approved knowledge, and never a general answer.
            logger.warning("AI gateway turn refused (outcome=knowledge_unavailable, calls=0)")
            raise GatewayFailure("knowledge_unavailable")
        if reason is not None:
            logger.warning("AI gateway turn refused (outcome=not_configured, calls=0)")
            raise GatewayFailure("not_configured")
        provider = self.provider
        assert provider is not None
        exceeded = self.limits.acquire(str(company.current_user.user_id))
        if exceeded is not None:
            logger.info("AI gateway turn refused (outcome=%s_limit, calls=0)", exceeded.scope)
            raise GatewayFailure("rate_limited", retry_after=exceeded.retry_after)

        # One snapshot for the whole turn: classify, evaluate and phrase on the same versions.
        snapshot = self._evaluation.snapshot()
        bundle = snapshot.knowledge
        if bundle is None:
            raise GatewayFailure("knowledge_unavailable")
        started = self._clock()
        telemetry = Telemetry(provider=provider.name, model=provider.model)
        if snapshot.profile is not None:
            telemetry.profile = f"{snapshot.profile.profile}@{snapshot.profile.version}"
        try:
            result = self._turn(
                provider, snapshot, bundle, company, turn, telemetry, _Deadline(self._clock)
            )
        except GatewayFailure as failure:
            telemetry.outcome = failure.kind
            self._log(telemetry, bundle, started, logging.WARNING)
            raise
        self._log(telemetry, bundle, started, logging.INFO)
        return result

    def _prior(
        self, read: ReadResult, execution: WorkflowExecution | None, workflow: str | None
    ) -> tuple[PriorState, str | None]:
        """The trusted state to start from, and why any was rejected (lost: re-confirmed)."""
        state = read.state
        if state is None:
            return PriorState(), read.rejection
        asked = state.asked
        carried = PriorState(
            engine=state.engine,
            workflow=state.workflow,
            jurisdiction=state.jurisdiction,
            two_state=state.two_state,
            asked=asked,
            reconfirm=state.reconfirm,
        )
        if not read.trusted:
            # A per-process key: what HeroOS asked helps the AI; nothing is trusted.
            return PriorState(asked=asked), None
        if execution is None:
            # Nothing is evaluated this turn (another kind of request): the trusted state is
            # carried to the next turn unchanged, never dropped.
            return carried, None
        if state.workflow not in (None, workflow):
            # Another matter's state never applies here; its loss is re-confirmed.
            return PriorState(), "other_workflow"
        schemas = execution.schemas
        valid = all(
            k in schemas and schemas[k].kind != "blueprint" and schemas[k].valid(v)
            for k, v in state.engine.items()
        ) and all(
            a.kind != "confirm"
            or (a.key in schemas and (a.candidate is None or schemas[a.key].valid(a.candidate)))
            for a in asked
        )
        if not valid:
            return PriorState(), "invalid_state"
        return carried, None

    def _evaluate(
        self,
        snapshot: ExecutionSnapshot,
        company: CompanyBlueprintContext,
        turn: FounderTurn,
        understanding: UnderstandingProposal,
        plan: TurnPlan | None,
        read: ReadResult,
        telemetry: Telemetry,
    ) -> _Turn:
        """The deterministic evaluation of this turn (pure; timed for the log)."""
        workflow = understanding.workflow if understanding.intent == "supported_hr" else None
        execution = None if workflow is None else snapshot.execution(workflow)
        prior, rejection = self._prior(read, execution, workflow)
        had_conversation = _previous_founder_message(turn) is not None
        # Trusted state lost mid-conversation is re-confirmed, never silently dropped.
        lost = had_conversation and read.trusted and execution is not None and (
            read.state is None or rejection is not None
        )  # fmt: skip
        telemetry.continuation = (rejection or "ok") if had_conversation else "none"
        reconfirm = lost or prior.reconfirm
        matter = MATTERS[understanding.intent]
        if matter == "supported" and workflow is None:
            matter = "unclear"
        started = time.perf_counter_ns()
        trust = None
        hedged: frozenset[str] = frozenset()
        stated: set[str] = set()
        current = len(_recent_founder_messages(turn)) - 1
        request = EvaluationRequest(matter=matter, workflow=workflow)
        if matter == "supported" and execution is not None:
            stated_facts = [
                StatedFact(f.fact_key, f.value, f.excerpt, f.establishes, f.source_turn == current)
                for f in understanding.facts
                if f.provenance != "company_blueprint"
            ]
            trust = trust_facts(
                execution,
                stated=stated_facts,
                message=turn.message,
                prior=prior,
                blueprint=_blueprint_values(company),
            )
            # The current message touched these without stating them (hedged, inferred or
            # contradicted): what was said about them before no longer stands.
            hedged = frozenset(
                f.fact_key
                for f in understanding.facts
                if f.source_turn == current and f.fact_key not in trust.facts.conversational
            )
            carried = carry(execution, trust.facts, turn.memory, hedged=hedged)
            noted = turn.noted
            said_before = {
                **{k: str(v) for k, v in turn.memory.said.items()},
                **_noted_facts(execution, noted),
            }
            if _corrects(execution, understanding, current, said_before):
                # A correction: only what the understanding still reads stands (found live: "it
                # was raised with him before" corrected to "that was another operative", and the
                # reading "discussed with him" from the same words stayed noted).
                carried, noted = {}, {}
            stated = {
                f.fact_key
                for f in understanding.facts
                if f.source_turn == current and f.fact_key in trust.facts.conversational
            } | {
                k for k, s in trust.facts.sources.items() if s in ("direct_answer", "confirmation")
            }
            requested = [a.action for a in understanding.actions]
            hypothetical = tuple(a.action for a in understanding.hypothetical)
            if (trust.answered or understanding.continued) and read.state is not None:
                # A direct answer keeps the steps it was about under evaluation (unless the
                # founder withdrew one in the same message); so does a message with no matter of
                # its own ("ok", "thanks"): it never drops the decision under discussion.
                withdrawn = {a.action for a in understanding.withdrawn}
                requested += [
                    a
                    for a in read.state.actions
                    if a in execution.options and a not in withdrawn and a not in hypothetical
                ]
            confirmed = company.jurisdiction
            request = EvaluationRequest(
                matter="supported",
                workflow=workflow,
                company_jurisdiction=(
                    confirmed.employment_jurisdiction if confirmed.guidance_allowed else None
                ),
                jurisdiction_conflict="jurisdiction_conflict" in understanding.uncertainties,
                clarification=trust.jurisdiction,
                facts=_with_noted(execution, trust.facts, noted, carried, hedged),
                requested=tuple(dict.fromkeys(requested)),
                topics=understanding.topics if plan is None else plan.query.topics,
                two_state=trust.two_state,
                reconfirm=reconfirm,
                multiple_matters="multiple_matters" in understanding.uncertainties,
                pathway_candidate=understanding.pathway,
                declined=trust.declined,
                progress=None if turn.case is None else turn.case.progress,
                hypothetical=hypothetical,
            )
        evaluation = self._evaluation.evaluate(snapshot, request)
        telemetry.evaluation_us = (time.perf_counter_ns() - started) // 1000
        card = outcome(evaluation, company_confirmed=company.jurisdiction.guidance_allowed)
        telemetry.workflow = workflow or "-"
        telemetry.evaluation = evaluation.availability
        telemetry.presentation = "-" if card is None else card.kind
        counts = evaluation.disposition_counts()
        telemetry.dispositions = "".join(f"{d[0]}{n}" for d, n in counts.items())
        telemetry.engine_trusted = len(evaluation.facts.engine)
        telemetry.conversational_untrusted = evaluation.facts.not_engine_trusted
        if execution is not None and execution.rule_bundle is not None:
            telemetry.rule_bundle = execution.rule_bundle.version
        case = () if turn.case is None else turn.case.signature
        memory = resolve(
            turn.memory,
            previous=prior.asked,
            facts=None if trust is None else evaluation.facts,
            stated=stated,
            answered=trust is not None and trust.answered,
            does_not_know=understanding.previous_answer == "does_not_know"
            and says_not_known(turn.message),
            jurisdiction_answered=trust is not None and trust.answered,
            said={} if trust is None or execution is None else said_values(
                execution, evaluation.facts
            ),
            hedged=hedged,
        )  # fmt: skip
        return _Turn(evaluation, card, trust, prior, reconfirm, case, memory)

    def _targets(
        self,
        snapshot: ExecutionSnapshot,
        plan: TurnPlan,
        result: _Turn,
        company: CompanyBlueprintContext,
        case: CaseContext | None = None,
    ) -> tuple[QuestionTarget, ...]:
        """What to ask next: what the deterministic checks need first, else what the Case record
        still needs (chat-first) and the methodology's, for the reply to choose from."""
        evaluation = result.evaluation
        execution = None if evaluation.workflow is None else snapshot.execution(evaluation.workflow)
        settled = _settled(result)
        # Never what the conversation already covered (found live: a fact said early on, or one
        # the founder said they don't know, was asked again and again).
        planned = tuple(t for t in plan.targets if t.fact_key not in settled)
        if execution is None:
            return planned
        if not evaluation.missing:
            unanswered = (
                {a.key for a in result.prior.asked if a.kind == "fact"}
                if result.trust is not None and not result.trust.answered
                else set()
            )
            optional = _case_targets(execution, case, evaluation, planned, unanswered | settled)
            return (*optional, *planned)
        requirement = next(
            (
                r
                for r in evaluation.missing
                # The founder answered this exact question with something else (or with what
                # they don't know), or left it unanswered too often: never the same question
                # again at once (found live: it was re-appended turn after turn). The reply
                # answers what they said; the next requirement, if any, is asked instead.
                if not (_asked_again(result, r) or _ignored(result, r))
            ),
            None,
        )
        if requirement is None:
            # Nothing the checks need can be asked now: what the Case record still needs can.
            unanswered = {a.key for a in result.prior.asked if a.kind == "fact"}
            optional = _case_targets(execution, case, evaluation, planned, unanswered | settled)
            return (*optional, *planned)
        if (
            requirement.kind == "jurisdiction"
            and evaluation.jurisdiction_state == "company_unconfirmed"
        ):
            return planned  # a Blueprint step, not a conversation answer
        schema = execution.schemas.get(requirement.key)
        definition_question = (
            None
            if schema is None or schema.question is None
            else execution.definition.question(schema.question)
        )
        titles = {a.action: a.title for a in evaluation.actions}
        question = requirement_question(
            requirement,
            schema=schema,
            action_titles=titles,
            jurisdiction=company.jurisdiction.employment_jurisdiction,
            prompt=None if definition_question is None else definition_question.prompt,
        )
        earlier = result.memory.asked.get(
            MEMORY_JURISDICTION if requirement.kind == "jurisdiction" else requirement.key
        )
        if earlier is not None and earlier.last == "hedged":
            # Asked again after an uncertain answer: said so, never the bare question repeated.
            lowered = question[:1].lower() + question[1:]
            question = f"You weren't certain earlier, so just to check: {lowered}"
        kind = {"fact": "fact", "confirmation": "confirm"}.get(requirement.kind, requirement.kind)
        candidate = requirement.candidate
        if requirement.kind == "confirmation" and definition_question is not None:
            # Its own question asked again: the answer is a direct one (no candidate to confirm).
            candidate = None
        if requirement.kind == "insistence":
            candidate = requirement.actions[0] if requirement.actions else None
        return (
            QuestionTarget(
                id="q1",
                # An insistence answer is matched to its two-state rule by the rule key.
                fact_key=(
                    requirement.key.partition(":")[2]
                    if requirement.kind == "insistence"
                    else requirement.key
                ),
                label=requirement.label
                if requirement.kind in ("fact", "confirmation")
                else question,
                mode="confirm" if requirement.kind == "confirmation" else "ask",
                kind=kind,  # type: ignore[arg-type]  # one of the target kinds
                candidate=candidate,
                question=question,
            ),
        )

    def _turn(
        self, provider: StructuredChatProvider, snapshot: ExecutionSnapshot,
        bundle: KnowledgeBundle, company: CompanyBlueprintContext, turn: FounderTurn,
        telemetry: Telemetry, deadline: _Deadline,
    ) -> GatewayReply:  # fmt: skip
        view = self._view(snapshot)
        founder = _recent_founder_messages(turn)
        user = company.current_user.user_id
        read = (
            turn.resume(snapshot)
            if turn.resume is not None
            else self._codec.read(
                turn.continuation,
                company=company.company_id,
                user=user,
                versions=snapshot_versions(snapshot),
                previous_message=_previous_founder_message(turn),
            )
        )
        asked_before = () if read.state is None else read.state.asked
        facts = _fact_labels(snapshot, bundle)
        labels = [ASKED_LABELS.get(a.kind, facts.get(a.key, "")) for a in asked_before]

        if is_greeting(turn.message):
            # Nothing to understand or evaluate yet: a friendly reply, no model request.
            understanding = UnderstandingProposal(
                intent="unclear", workflow=None, pathway=None, topics=(), facts=(),
                uncertainties=(), summary=None,
            )  # fmt: skip
            telemetry.wording = "greeting"
            result = self._evaluate(snapshot, company, turn, understanding, None, read, telemetry)
            return self._reply(
                company, snapshot, GREETING, None, "clarifying", (), understanding, None, result,
                turn, fixed=True,
            )  # fmt: skip

        understanding = self._understand(
            provider, company, founder, [lbl for lbl in labels if lbl], telemetry, deadline,
            view.catalog, _previous_question(turn),
        )  # fmt: skip
        # A bare answer can only answer the one question HeroOS just asked.
        answering = (
            asked_before[0].key
            if len(asked_before) == 1 and asked_before[0].kind in ("fact", "confirm")
            else None
        )
        understanding, dropped = check_evidence(
            understanding, view.catalog, founder, company_text(company), answering=answering
        )
        understanding = without_contradicted(
            understanding,
            lambda f: contradicted(f.value, f.excerpt, context=sentence_of(founder, f)),
        )
        telemetry.facts_rejected = dropped
        # Thanks, a reaction or a goodbye in the middle of a matter: answered, never asked a
        # required question on its way out.
        conversational = understanding.intent == "conversational"
        understanding = _continued(snapshot, read, understanding)

        fixed = self._routed(understanding, view.catalog, turn)
        if fixed is not None:
            text, state = fixed
            result = self._evaluate(snapshot, company, turn, understanding, None, read, telemetry)
            if state == "clarifying":
                # Answered in words, not a fixed text (found live: "ok", "thanks, bye" and
                # "what is this thing for?" got the same canned paragraph, again and again).
                text = (
                    self._light(provider, company, turn, founder, view, telemetry, deadline) or text
                )
            return self._reply(
                company, snapshot, text, None, state, (), understanding, None, result, turn,
                fixed=True,
            )  # fmt: skip

        execution = snapshot.execution(understanding.workflow) if understanding.workflow else None
        known = _known(snapshot, understanding, read, turn)
        plan = plan_turn(bundle, understanding, company, known=known)
        status = plan.context.status
        telemetry.knowledge_status = status.value
        if status is KnowledgeStatus.BUNDLE_UNAVAILABLE:
            raise GatewayFailure("knowledge_unavailable")
        result = self._evaluate(snapshot, company, turn, understanding, plan, read, telemetry)
        plan = _for_employee(bundle, understanding, company, plan, result, known=known)
        status = plan.context.status
        telemetry.knowledge_status = status.value
        if status in (KnowledgeStatus.UNSUPPORTED, KnowledgeStatus.SOURCE_CONFLICT):
            text = NO_APPROVED_CONTENT if status is KnowledgeStatus.UNSUPPORTED else SOURCE_CONFLICT
            return self._reply(
                company, snapshot, text, None, "outside_approved_guidance", (), understanding,
                plan, result, turn, fixed=True,
            )  # fmt: skip

        plan = dataclasses.replace(
            plan, targets=self._targets(snapshot, plan, result, company, turn.case)
        )
        if conversational:
            # The founder is thanking, reacting or leaving: no question is forced on them.
            plan = dataclasses.replace(
                plan, targets=tuple(t for t in plan.targets if t.question is None)
            )
        knowledge = knowledge_view(bundle, plan)
        decided, decided_texts = outcome_view(result.evaluation, result.card)
        case_view, case_texts = (
            ({}, ()) if turn.case is None else turn.case.model_view(bundle)
        )  # fmt: skip
        sections: dict[str, object] = {
            "approved_knowledge": knowledge.data,
            **({"heroos_outcome": decided} if decided is not None else {}),
            # M2-NEW-08: where the Case stands, as its employer recorded it (read-only).
            **({"case_progress": case_view} if turn.case is not None else {}),
            "company_context": company_view(company),
            # What the conversation already covered: known, not known, asked (server-owned).
            "conversation_state": conversation_view(
                execution,
                facts,
                result.evaluation.facts if result.trust else None,
                result.memory,
                result.prior.asked,
                [(f.fact_key, f.value) for f in plan.established],
            ),
            "jurisdiction_note": self._jurisdiction_note(plan),
            "conversation": _recent_conversation(turn),
            "current_message": turn.message,
        }
        offered = [t.id for t in plan.targets]

        def check(proposal: ResponseProposal) -> tuple[Literal["safety", "grounding"], str] | None:
            texts = [proposal.reply] + (
                [proposal.safe_next_step] if proposal.safe_next_step else []
            )
            return self._checked(
                texts, result, knowledge.texts, decided_texts, case_texts, founder, plan, view
            )

        turns = [data_message(sections)]
        try:
            proposal = self._phase(
                provider, RESPONSE_INSTRUCTION, turns, RESPONSE_TEMPERATURE,
                RESPONSE_TOKENS, lambda text: parse_response(text, offered), "b", telemetry,
                deadline, fail_soft=True,
            )  # fmt: skip
            problem = None if proposal is None else check(proposal)
            if (
                proposal is not None
                and problem is not None
                and telemetry.calls < MAX_PROVIDER_CALLS
            ):
                # One rewrite with the reason (a fixed code, never text): found live, a reply
                # that restated the founder's own "3 days" or skipped their question for a
                # canned fallback. The rewrite passes every check again or the fallback stands.
                telemetry.repairs.append(f"b:{problem[1]}")
                try:
                    rewritten = self._phase(
                        provider, RESPONSE_INSTRUCTION,
                        regeneration_turns(turns, proposal.reply, problem[1]),
                        RESPONSE_TEMPERATURE, RESPONSE_TOKENS,
                        lambda text: parse_response(text, offered), "c", telemetry, deadline,
                        fail_soft=True, repair=False,
                    )  # fmt: skip
                except GatewayFailure:
                    rewritten = None  # the server's own reply stands, as without the rewrite
                if rewritten is not None and check(rewritten) is None:
                    proposal, problem = rewritten, None
        except GatewayFailure as failure:
            if result.card is None or result.card.kind not in SAFETY_OUTCOMES:
                raise
            # The deterministic result was decided: it stays, in the server's own words.
            telemetry.wording = f"provider_{failure.kind}"
            return self._fallback(
                company, snapshot, "provider", understanding, plan, result, turn, provider=True
            )
        if proposal is None:
            telemetry.outcome = "invalid_output_fallback"
            telemetry.wording = "fallback_invalid"
            return self._fallback(company, snapshot, "invalid", understanding, plan, result, turn)
        if problem is not None:
            family, code = problem
            if family == "grounding":
                telemetry.grounding = code
                telemetry.wording = "fallback_grounding"
                return self._fallback(company, snapshot, "legal", understanding, plan, result, turn)
            telemetry.safety = code
            telemetry.wording = "fallback_safety"
            return self._fallback(
                company, snapshot, FALLBACK_FAMILY[code], understanding, plan, result, turn
            )
        reply = proposal.reply
        # A target counts as asked only if the reply asks something: a claim with no question
        # in the words would make the founder's next message a "direct answer" to nothing.
        used = [t for t in plan.targets if t.id in proposal.target_ids] if "?" in reply else []
        required = next((t for t in plan.targets if t.question is not None), None)
        if required is not None:
            # A deterministic check needs this answer: always asked in the server's words (its
            # meaning is what the answer is parsed against), as the reply's one question (found
            # live: the model's own question and the server's, one after the other).
            reply = _with_question(reply, required.question or "")
            used = [required]
        step = proposal.safe_next_step
        fixed_step = next_step_text(result.evaluation) if result.evaluation.ready else None
        if result.card is not None and result.card.kind in SAFETY_OUTCOMES:
            # Under a Warning, Block or Expert Review the safe next step is the server's.
            step = fixed_step
        return self._reply(
            company, snapshot, reply, step, "responded", tuple(used), understanding, plan,
            result, turn,
        )  # fmt: skip

    def _checked(
        self, texts: Sequence[str], result: _Turn, knowledge: Sequence[str],
        decided: Sequence[str], case: Sequence[str], founder: Sequence[str], plan: TurnPlan,
        view: _SnapshotView,
    ) -> tuple[Literal["safety", "grounding"], str] | None:  # fmt: skip
        """The first reply-safety, contradiction or grounding check the texts fail."""
        problem: str | None = next(
            (p for p in (gateway_problem(t) for t in texts) if p is not None), None
        )
        if problem is None:
            problem = outcome_contradiction(list(texts), result.evaluation)
        if problem is not None:
            return "safety", problem
        grounding = check_grounding(
            texts,
            knowledge=(*knowledge, *decided, *case),
            founder=founder,
            jurisdiction=plan.context.jurisdiction,
            prohibited=plan.context.prohibited_behaviors,
            labels=view.labels,
            instructions=RESPONSE_INSTRUCTION + UNDERSTANDING_INSTRUCTION,
        )
        return None if grounding is None else ("grounding", grounding)

    def _light(
        self, provider: StructuredChatProvider, company: CompanyBlueprintContext,
        turn: FounderTurn, founder: Sequence[str], view: _SnapshotView, telemetry: Telemetry,
        deadline: _Deadline,
    ) -> str | None:  # fmt: skip
        """A short reply in the model's words to a message with no matter to work on yet (a
        start, a reaction, thanks, a goodbye, a question about HeroOS), or None for the fixed
        text. It carries no approved guidance and passes the reply-safety and grounding checks;
        a provider failure fails the turn, as everywhere else."""
        coverage = list(view.catalog.coverage())
        sections = {
            "heroos_scope": {"what_heroos_does": SCOPE, "approved_guidance_covers": coverage},
            "company_context": company_view(company),
            "conversation": _recent_conversation(turn),
            "current_message": turn.message,
        }
        proposal = self._phase(
            provider, LIGHT_INSTRUCTION, [data_message(sections)], RESPONSE_TEMPERATURE,
            LIGHT_TOKENS, lambda text: parse_response(text, []), "l", telemetry, deadline,
            fail_soft=True,
        )  # fmt: skip
        if proposal is None or gateway_problem(proposal.reply) is not None:
            telemetry.wording = "fixed_light"
            return None
        grounding = check_grounding(
            [proposal.reply],
            knowledge=(SCOPE, *coverage),
            founder=founder,
            jurisdiction=None,
            prohibited=(),
            labels=view.labels,
            instructions=LIGHT_INSTRUCTION + UNDERSTANDING_INSTRUCTION,
        )
        if grounding is not None:
            telemetry.grounding = grounding
            telemetry.wording = "fixed_light"
            return None
        telemetry.wording = "light"
        return proposal.reply

    # --- commit-time reconciliation (M2-NEW-07) ---------------------------------------

    def reconcile(
        self, company: CompanyBlueprintContext, turn: FounderTurn, reply: GatewayReply
    ) -> tuple[GatewayReply, Reconciliation]:
        """The reply on the Case as it is now: the deterministic part again, no model request.

        ``turn.resume`` reads the state at commit time (the Case's facts and the
        Blueprint may have changed while the provider answered). Same snapshot,
        same understanding; only the deterministic evaluation runs again, and the
        freshest authoritative result is the one recorded:

        - the same result: the model's wording stands (``kept``), on the fresh state;
        - a result at least as strict: the wording is replaced by the server's fixed
          text for the current result (``refreshed``);
        - a weaker result on authoritative state (another administrator recorded
          the missing prerequisite, say): the stale stricter wording is discarded
          for the server's fixed text for the current result (``relaxed``);
        - a weaker result only because something became less certain (trust lost,
          the jurisdiction no longer resolved, a trusted fact gone or "Not sure",
          a safeguard unknown; ``uncertainty``): the stricter reply that was
          prepared stands (``held``). Uncertainty never weakens a Warning, Block or
          Expert Review. Its next state is still the current one, so what was lost
          stays lost and is re-confirmed, never carried over.
        """
        basis = reply.basis
        if basis is None or turn.resume is None:
            return reply, "kept"
        snapshot, understanding = basis.snapshot, basis.understanding
        bundle = snapshot.knowledge
        assert bundle is not None  # a reply with a basis was answered from knowledge
        telemetry = Telemetry(provider="-", model="-")
        read = turn.resume(snapshot)
        routed = self._routed(understanding, self._view(snapshot).catalog) is not None
        known = _known(snapshot, understanding, read, turn)
        plan = None if routed else plan_turn(bundle, understanding, company, known=known)
        result = self._evaluate(snapshot, company, turn, understanding, plan, read, telemetry)
        if plan is not None:
            plan = _for_employee(bundle, understanding, company, plan, result, known=known)
        if _signature(result) == _signature(basis.result):
            refreshed = self._reply(
                company, snapshot, reply.reply, reply.safe_next_step, reply.state, basis.asked,
                understanding, basis.plan, result, turn, fixed=basis.fixed,
            )  # fmt: skip
            return refreshed, "kept"
        weaker = _strictness(result) < _strictness(basis.result)
        if weaker and uncertainty(result, basis.result) is not None:
            # The prepared outcome stands; the next turn starts from the current state.
            return dataclasses.replace(
                reply, next_state=self._next_state(result, basis.asked)
            ), "held"  # fmt: skip
        reconciliation: Reconciliation = "relaxed" if weaker else "refreshed"
        if basis.fixed or plan is None:
            # Fixed text stays fixed text; the outcome is the current one.
            return self._reply(
                company, snapshot, reply.reply, None, reply.state, (), understanding, plan,
                result, turn, fixed=True,
            ), reconciliation  # fmt: skip
        plan = dataclasses.replace(
            plan, targets=self._targets(snapshot, plan, result, company, turn.case)
        )
        return (
            self._fallback(company, snapshot, "changed", understanding, plan, result, turn),
            reconciliation,
        )

    # --- phases -----------------------------------------------------------------------

    def _understand(
        self, provider: StructuredChatProvider, company: CompanyBlueprintContext,
        founder: Sequence[str], asked_labels: Sequence[str], telemetry: Telemetry,
        deadline: _Deadline, catalog: RoutingCatalog, previous: str | None = None,
    ) -> UnderstandingProposal:  # fmt: skip
        sections = {
            "routing_catalog": catalog.model_view(),
            "company_context": company_view(company),
            "previous_question_about": list(asked_labels),
            # The question HeroOS's last reply ended with, so an answer is read against what was
            # actually asked (context only: never a source for a fact).
            **({"previous_heroos_question": previous} if previous else {}),
            "founder_messages": [{"turn": i, "text": text} for i, text in enumerate(founder)],
            # For a date the founder gives relatively ("yesterday"); a reading, never trusted.
            "today": datetime.now(UTC).date().isoformat(),
        }
        current = len(founder) - 1
        result = self._phase(
            provider, UNDERSTANDING_INSTRUCTION, [data_message(sections)],
            UNDERSTANDING_TEMPERATURE, UNDERSTANDING_TOKENS,
            lambda text: parse_understanding(text, catalog, current_turn=current), "a",
            telemetry, deadline, fail_soft=False,
        )  # fmt: skip
        assert result is not None
        return result

    def _phase[P: (UnderstandingProposal, ResponseProposal)](
        self, provider: StructuredChatProvider, system: str, turns: list[ChatTurn],
        temperature: float, tokens: int, parse: Callable[[str], P], name: str,
        telemetry: Telemetry, deadline: _Deadline, *, fail_soft: bool, repair: bool = True,
    ) -> P | None:  # fmt: skip
        """One request and at most one schema repair. Transport failures are never retried."""
        completion = self._call(provider, system, turns, temperature, tokens, telemetry, deadline)
        try:
            return parse(completion.text)
        except ProposalError as first:
            if not repair:
                return None
            telemetry.repairs.append(name)
            # The fixed structural code only (never the output).
            logger.info("AI gateway output repaired (phase=%s, code=%s)", name, first.code)
            repaired = self._call(
                provider, system, repair_turns(turns, completion.text, [first.code]),
                temperature, tokens, telemetry, deadline,
            )  # fmt: skip
            try:
                return parse(repaired.text)
            except ProposalError:
                if fail_soft:
                    return None
                raise GatewayFailure("invalid_output") from None

    def _call(
        self, provider: StructuredChatProvider, system: str, turns: Sequence[ChatTurn],
        temperature: float, tokens: int, telemetry: Telemetry, deadline: _Deadline,
    ) -> Completion:  # fmt: skip
        if telemetry.calls >= MAX_PROVIDER_CALLS:
            raise GatewayFailure("unavailable")
        timeout = deadline.call_timeout()
        telemetry.calls += 1
        try:
            completion = provider.complete_json(
                system, turns, temperature=temperature, max_completion_tokens=tokens,
                timeout=timeout,
            )  # fmt: skip
        except AssistantError as exc:
            raise GatewayFailure(exc.kind, retry_after=exc.retry_after) from None
        telemetry.prompt_tokens += completion.prompt_tokens or 0
        telemetry.completion_tokens += completion.completion_tokens or 0
        return completion

    # --- replies the server composes ---------------------------------------------------

    def _routed(
        self, understanding: UnderstandingProposal, catalog: RoutingCatalog,
        turn: FounderTurn | None = None,
    ) -> tuple[str, ConversationState] | None:  # fmt: skip
        coverage = ", ".join(catalog.coverage())
        previous = None if turn is None else _previous_reply(turn)
        if understanding.intent == "other_hr":
            text = OUTSIDE_HR.format(coverage=coverage)
            again = previous in (text, OUTSIDE_HR_AGAIN)
            return (OUTSIDE_HR_AGAIN if again else text), "outside_approved_guidance"
        if understanding.intent == "unsupported":
            text = OUTSIDE.format(coverage=coverage)
            again = previous in (text, OUTSIDE_AGAIN)
            return (OUTSIDE_AGAIN if again else text), "outside_approved_guidance"
        if understanding.intent == "confidential_request":
            return CONFIDENTIAL, "outside_approved_guidance"
        if understanding.intent == "conversational":
            return CONVERSATIONAL, "clarifying"
        if understanding.intent == "unclear" or understanding.workflow is None:
            return UNCLEAR, "clarifying"
        return None

    @staticmethod
    def _jurisdiction_note(plan: TurnPlan) -> str:
        if plan.jurisdiction_state == "conversation_conflict":
            return (
                "Unclear for this employee: the founder's words suggest a different employing "
                "entity or regime than the company's confirmed one. Apply neither; ask which "
                "legal entity employs this person."
            )
        if plan.jurisdiction_state == "company_unconfirmed":
            return (
                "Not confirmed: the company's employment jurisdiction isn't confirmed in its "
                "Company Blueprint yet (HeroOS confirms it from the licensing details). Give only "
                "shared orientation and say that jurisdiction-specific guidance needs it."
            )
        if plan.jurisdiction_state == "employee_unresolved":
            return (
                "Not confirmed for this employee: the employer hasn't confirmed that the "
                "company's jurisdiction applies to them. Give only the shared guidance provided "
                "and say that jurisdiction-specific guidance waits until it is confirmed."
            )
        jurisdiction = plan.context.jurisdiction or ""
        return f"Confirmed: {JURISDICTION_NAMES.get(jurisdiction, jurisdiction)}."

    def _fallback(
        self, company: CompanyBlueprintContext, snapshot: ExecutionSnapshot, family: str,
        understanding: UnderstandingProposal, plan: TurnPlan, result: _Turn, turn: FounderTurn,
        *, provider: bool = False,
    ) -> GatewayReply:  # fmt: skip
        """A reply composed only from fixed text, the plan and the deterministic result."""
        target = plan.targets[0] if plan.targets else None
        question = target_question(target) if target is not None else OPEN_QUESTION
        card = result.card
        if card is not None and card.kind != "unavailable":
            text = fallback_reply(
                result.evaluation, card, lead=FALLBACK_LEADS[family], question=question,
                provider_note=provider,
            )  # fmt: skip
        else:
            parts = [FALLBACK_LEADS[family]] if FALLBACK_LEADS[family] else []
            for action in plan.requested_actions:
                if action.availability == "review_required":
                    parts.append(f"{action.title} needs specialist review before it is taken.")
                elif action.availability == "not_available":
                    parts.append(
                        f"{action.title} isn't available for your company under HeroOS's approved "
                        "guidance."
                    )
            if plan.jurisdiction_state == "company_unconfirmed":
                parts.append(
                    "Jurisdiction-specific guidance needs your company's employment jurisdiction "
                    "to be confirmed in your Company Blueprint first."
                )
            elif plan.jurisdiction_state == "conversation_conflict":
                parts.append("HeroOS needs to confirm which legal entity employs this person.")
            parts.append(question)
            text = " ".join(parts)
        asked = (target,) if target is not None else ()
        step = next_step_text(result.evaluation) if result.evaluation.ready else None
        return self._reply(
            company, snapshot, text, step if card is not None else None, "responded", asked,
            understanding, plan, result, turn,
        )  # fmt: skip

    def _reply(
        self, company: CompanyBlueprintContext, snapshot: ExecutionSnapshot, text: str,
        step: str | None, state: ConversationState, asked: tuple[QuestionTarget, ...],
        understanding: UnderstandingProposal, plan: TurnPlan | None, result: _Turn,
        turn: FounderTurn, *, fixed: bool = False,
    ) -> GatewayReply:  # fmt: skip
        user = company.current_user.user_id
        context = None if plan is None else plan.context
        evaluation = result.evaluation
        handoff = Handoff(
            intent=understanding.intent,
            workflow=understanding.workflow,
            pathway_candidate=understanding.pathway,
            topics=understanding.topics if plan is None else plan.query.topics,
            established=tuple(
                EstablishedFact(f.fact_key, f.value, f.provenance, f.source_turn)
                for f in (() if plan is None else plan.established)
            ),
            tentative=tuple(f.fact_key for f in understanding.facts if not f.establishes),
            uncertainties=understanding.uncertainties,
            summary=understanding.summary,
            knowledge_status=None if context is None else context.status.value,
            jurisdiction=None if context is None else context.jurisdiction,
            review_required=tuple(
                a.title
                for a in (() if plan is None else plan.requested_actions)
                if a.availability == "review_required"
            ),
            asked=tuple(t.fact_key for t in asked),
            runtime_bundle_digest=None
            if snapshot.knowledge is None
            else snapshot.knowledge.runtime_digest,
            requested_actions=tuple(a.action for a in evaluation.actions if not a.hypothetical),
            evaluation=evaluation,
            snapshot=snapshot,
            withdrawn_actions=tuple(a.action for a in understanding.withdrawn),
            hypothetical_actions=tuple(a.action for a in evaluation.actions if a.hypothetical),
        )
        next_state = self._next_state(result, asked)
        memory = record(result.memory, [(t.kind, t.fact_key) for t in asked if t.fact_key])
        return GatewayReply(
            reply=text,
            safe_next_step=step,
            state=state,
            continuation=self._codec.issue(
                next_state,
                company=company.company_id,
                user=user,
                versions=snapshot_versions(snapshot),
                message=turn.message,
            ),
            handoff=handoff,
            outcome=result.card,
            next_state=next_state,
            basis=TurnBasis(snapshot, understanding, result, plan, asked, fixed),
            memory=memory,
        )

    @staticmethod
    def _next_state(result: _Turn, asked: tuple[QuestionTarget, ...]) -> ContinuationState:
        """The trusted state the next turn starts from (an off-topic turn keeps the prior one)."""
        evaluation = result.evaluation
        questions = tuple(
            Asked(t.kind, t.fact_key, t.candidate) for t in asked if t.kind != "fact" or t.fact_key
        )
        if result.trust is None:
            prior = result.prior
            return ContinuationState(
                workflow=evaluation.workflow or prior.workflow,
                asked=questions,
                engine=dict(prior.engine),
                jurisdiction=prior.jurisdiction,
                two_state=dict(prior.two_state),
                reconfirm=prior.reconfirm,
            )
        facts: TrustedFactState = evaluation.facts
        return ContinuationState(
            workflow=evaluation.workflow,
            asked=questions,
            engine={k: v for k, v in facts.engine.items() if facts.sources.get(k) != "blueprint"},
            jurisdiction=result.trust.jurisdiction,
            two_state={t.rule: t for t in evaluation.two_state},
            reconfirm=result.reconfirm,
            # A "what if" is never carried as a step the employer still considers.
            actions=tuple(a.action for a in evaluation.actions if not a.hypothetical),
        )

    def _log(
        self, telemetry: Telemetry, bundle: KnowledgeBundle, started: float, level: int
    ) -> None:
        logger.log(
            level,
            "AI gateway turn (provider=%s, model=%s, outcome=%s, calls=%d, repairs=%s, "
            "knowledge_status=%s, runtime_bundle_digest=%s, safety=%s, grounding=%s, "
            "facts_rejected=%d, prompt_tokens=%d, completion_tokens=%d, latency_ms=%d, "
            "workflow=%s, evaluation=%s, presentation=%s, dispositions=%s, engine_trusted=%d, "
            "conversational_untrusted=%d, profile=%s, rule_bundle=%s, continuation=%s, "
            "evaluation_us=%d, wording=%s)",
            telemetry.provider,
            telemetry.model,
            telemetry.outcome,
            telemetry.calls,
            ",".join(telemetry.repairs) or "none",
            telemetry.knowledge_status,
            bundle.runtime_digest,
            telemetry.safety,
            telemetry.grounding,
            telemetry.facts_rejected,
            telemetry.prompt_tokens,
            telemetry.completion_tokens,
            int((self._clock() - started) * 1000),
            telemetry.workflow,
            telemetry.evaluation,
            telemetry.presentation,
            telemetry.dispositions,
            telemetry.engine_trusted,
            telemetry.conversational_untrusted,
            telemetry.profile,
            telemetry.rule_bundle,
            telemetry.continuation,
            telemetry.evaluation_us,
            telemetry.wording,
        )
