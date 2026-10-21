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

The result carries a ``Handoff`` (server-side only: never sent to the browser
or stored) with the understanding and the deterministic evaluation, for the
persistence that follows (M2-NEW-07).
"""

import dataclasses
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from app.assistant.gateway.catalog import EMPTY_CATALOG, RoutingCatalog, routing_catalog
from app.assistant.gateway.grounding import check_grounding, internal_labels
from app.assistant.gateway.planning import QuestionTarget, TurnPlan, plan_turn
from app.assistant.gateway.projection import (
    JURISDICTION_NAMES,
    company_text,
    company_view,
    knowledge_view,
)
from app.assistant.gateway.prompts import (
    RESPONSE_INSTRUCTION,
    UNDERSTANDING_INSTRUCTION,
    data_message,
    repair_turns,
)
from app.assistant.gateway.proposals import (
    ProposalError,
    ResponseProposal,
    UnderstandingProposal,
    check_evidence,
    parse_response,
    parse_understanding,
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
    Asked,
    PriorState,
    StatedFact,
    TrustOutcome,
    contradicted,
    trust_facts,
)
from app.evaluation.model import ConversationEvaluation, Matter, TrustedFactState
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
UNDERSTANDING_TEMPERATURE: Final = 0.0
RESPONSE_TEMPERATURE: Final = 0.2
# The founder's earlier messages the understanding phase sees (newest kept first).
MAX_FOUNDER_TURNS: Final = 6
MAX_FOUNDER_CHARS: Final = 6000
# The recent conversation the response phase sees.
MAX_CONVERSATION_TURNS: Final = 6
MAX_CONVERSATION_CHARS: Final = 6000

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
class FounderTurn:
    message: str
    # Recent conversation as the browser holds it (oldest first, both roles; untrusted).
    history: tuple[ChatTurn, ...] = ()
    continuation: str | None = None


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
class GatewayReply:
    reply: str
    safe_next_step: str | None
    state: ConversationState
    continuation: str
    handoff: Handoff
    # The deterministic outcome (server-owned); None when there is nothing to show.
    outcome: Outcome | None = None


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


def _versions(snapshot: ExecutionSnapshot) -> str:
    """The identity a continuation is bound to: the knowledge and the execution profile."""
    knowledge = "-" if snapshot.knowledge is None else snapshot.knowledge.runtime_digest
    profile = "-" if snapshot.profile is None else snapshot.profile.digest
    return f"{knowledge}|{profile}"


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
            view = _SnapshotView(
                catalog=EMPTY_CATALOG if bundle is None else routing_catalog(bundle),
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
            a.kind != "confirm" or (a.key in schemas and schemas[a.key].valid(a.candidate))
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
        request = EvaluationRequest(matter=matter, workflow=workflow)
        if matter == "supported" and execution is not None:
            current = len(_recent_founder_messages(turn)) - 1
            stated = [
                StatedFact(f.fact_key, f.value, f.excerpt, f.establishes, f.source_turn == current)
                for f in understanding.facts
                if f.provenance != "company_blueprint"
            ]
            trust = trust_facts(
                execution,
                stated=stated,
                message=turn.message,
                prior=prior,
                blueprint=_blueprint_values(company),
            )
            requested = [a.action for a in understanding.actions]
            if trust.answered and read.state is not None:
                # A direct answer keeps the steps it was about under evaluation.
                requested += [a for a in read.state.actions if a in execution.options]
            confirmed = company.jurisdiction
            request = EvaluationRequest(
                matter="supported",
                workflow=workflow,
                company_jurisdiction=(
                    confirmed.employment_jurisdiction if confirmed.guidance_allowed else None
                ),
                jurisdiction_conflict="jurisdiction_conflict" in understanding.uncertainties,
                clarification=trust.jurisdiction,
                facts=trust.facts,
                requested=tuple(dict.fromkeys(requested)),
                topics=understanding.topics if plan is None else plan.query.topics,
                two_state=trust.two_state,
                reconfirm=reconfirm,
                multiple_matters="multiple_matters" in understanding.uncertainties,
                pathway_candidate=understanding.pathway,
                declined=trust.declined,
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
        return _Turn(evaluation, card, trust, prior, reconfirm)

    def _targets(
        self,
        snapshot: ExecutionSnapshot,
        plan: TurnPlan,
        result: _Turn,
        company: CompanyBlueprintContext,
    ) -> tuple[QuestionTarget, ...]:
        """What to ask next: what the deterministic checks need first, else the methodology's."""
        evaluation = result.evaluation
        execution = None if evaluation.workflow is None else snapshot.execution(evaluation.workflow)
        if execution is None or not evaluation.missing:
            return plan.targets
        requirement = evaluation.missing[0]
        if (
            requirement.kind == "jurisdiction"
            and evaluation.jurisdiction_state == "company_unconfirmed"
        ):
            return plan.targets  # a Blueprint step, not a conversation answer
        schema = execution.schemas.get(requirement.key)
        titles = {a.action: a.title for a in evaluation.actions}
        question = requirement_question(
            requirement,
            schema=schema,
            action_titles=titles,
            jurisdiction=company.jurisdiction.employment_jurisdiction,
        )
        kind = {"fact": "fact", "confirmation": "confirm"}.get(requirement.kind, requirement.kind)
        candidate = requirement.candidate
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
        read = self._codec.read(
            turn.continuation,
            company=company.company_id,
            user=user,
            versions=_versions(snapshot),
            previous_message=_previous_founder_message(turn),
        )
        asked_before = () if read.state is None else read.state.asked
        facts = {f.key: f.label for f in bundle.facts}
        labels = [ASKED_LABELS.get(a.kind, facts.get(a.key, "")) for a in asked_before]

        understanding = self._understand(
            provider, company, founder, [lbl for lbl in labels if lbl], telemetry, deadline,
            view.catalog,
        )  # fmt: skip
        understanding, dropped = check_evidence(
            understanding, view.catalog, founder, company_text(company)
        )
        understanding = without_contradicted(
            understanding, lambda f: contradicted(f.value, f.excerpt)
        )
        telemetry.facts_rejected = dropped

        fixed = self._routed(understanding, view.catalog)
        if fixed is not None:
            text, state = fixed
            result = self._evaluate(snapshot, company, turn, understanding, None, read, telemetry)
            return self._reply(
                company, snapshot, text, None, state, (), understanding, None, result, turn
            )

        plan = plan_turn(bundle, understanding, company)
        status = plan.context.status
        telemetry.knowledge_status = status.value
        if status is KnowledgeStatus.BUNDLE_UNAVAILABLE:
            raise GatewayFailure("knowledge_unavailable")
        result = self._evaluate(snapshot, company, turn, understanding, plan, read, telemetry)
        if status in (KnowledgeStatus.UNSUPPORTED, KnowledgeStatus.SOURCE_CONFLICT):
            text = NO_APPROVED_CONTENT if status is KnowledgeStatus.UNSUPPORTED else SOURCE_CONFLICT
            return self._reply(
                company, snapshot, text, None, "outside_approved_guidance", (), understanding,
                plan, result, turn,
            )  # fmt: skip

        plan = dataclasses.replace(plan, targets=self._targets(snapshot, plan, result, company))
        knowledge = knowledge_view(bundle, plan)
        decided, decided_texts = outcome_view(result.evaluation, result.card)
        sections: dict[str, object] = {
            "approved_knowledge": knowledge.data,
            **({"heroos_outcome": decided} if decided is not None else {}),
            "company_context": company_view(company),
            "established_facts": [
                {"about": facts[f.fact_key], "value": f.value} for f in plan.established
            ],
            "jurisdiction_note": self._jurisdiction_note(plan),
            "conversation": _recent_conversation(turn),
            "current_message": turn.message,
        }
        offered = [t.id for t in plan.targets]
        try:
            proposal = self._phase(
                provider, RESPONSE_INSTRUCTION, [data_message(sections)], RESPONSE_TEMPERATURE,
                RESPONSE_TOKENS, lambda text: parse_response(text, offered), "b", telemetry,
                deadline, fail_soft=True,
            )  # fmt: skip
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

        texts = [proposal.reply] + ([proposal.safe_next_step] if proposal.safe_next_step else [])
        problem: str | None = next(
            (p for p in (gateway_problem(t) for t in texts) if p is not None), None
        )
        if problem is None:
            problem = outcome_contradiction(texts, result.evaluation)
        if problem is not None:
            telemetry.safety = problem
            telemetry.wording = "fallback_safety"
            return self._fallback(
                company, snapshot, FALLBACK_FAMILY[problem], understanding, plan, result, turn
            )
        grounding = check_grounding(
            texts,
            knowledge=(*knowledge.texts, *decided_texts),
            founder=founder,
            jurisdiction=plan.context.jurisdiction,
            prohibited=plan.context.prohibited_behaviors,
            labels=view.labels,
            instructions=RESPONSE_INSTRUCTION + UNDERSTANDING_INSTRUCTION,
        )
        if grounding is not None:
            telemetry.grounding = grounding
            telemetry.wording = "fallback_grounding"
            return self._fallback(company, snapshot, "legal", understanding, plan, result, turn)
        used = [t for t in plan.targets if t.id in proposal.target_ids]
        reply = proposal.reply
        required = next((t for t in plan.targets if t.question is not None), None)
        if required is not None and required not in used:
            # A deterministic check needs this answer: ask it in the server's words.
            reply = f"{reply} {required.question}"
            used.append(required)
        step = proposal.safe_next_step
        fixed_step = next_step_text(result.evaluation) if result.evaluation.ready else None
        if result.card is not None and result.card.kind in SAFETY_OUTCOMES:
            # Under a Warning, Block or Expert Review the safe next step is the server's.
            step = fixed_step
        return self._reply(
            company, snapshot, reply, step, "responded", tuple(used), understanding, plan,
            result, turn,
        )  # fmt: skip

    # --- phases -----------------------------------------------------------------------

    def _understand(
        self, provider: StructuredChatProvider, company: CompanyBlueprintContext,
        founder: Sequence[str], asked_labels: Sequence[str], telemetry: Telemetry,
        deadline: _Deadline, catalog: RoutingCatalog,
    ) -> UnderstandingProposal:  # fmt: skip
        sections = {
            "routing_catalog": catalog.model_view(),
            "company_context": company_view(company),
            "previous_question_about": list(asked_labels),
            "founder_messages": [{"turn": i, "text": text} for i, text in enumerate(founder)],
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
        telemetry: Telemetry, deadline: _Deadline, *, fail_soft: bool,
    ) -> P | None:  # fmt: skip
        """One request and at most one schema repair. Transport failures are never retried."""
        completion = self._call(provider, system, turns, temperature, tokens, telemetry, deadline)
        try:
            return parse(completion.text)
        except ProposalError as first:
            telemetry.repairs.append(name)
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
        self, understanding: UnderstandingProposal, catalog: RoutingCatalog
    ) -> tuple[str, ConversationState] | None:
        coverage = ", ".join(catalog.coverage())
        if understanding.intent == "other_hr":
            return OUTSIDE_HR.format(coverage=coverage), "outside_approved_guidance"
        if understanding.intent == "unsupported":
            return OUTSIDE.format(coverage=coverage), "outside_approved_guidance"
        if understanding.intent == "confidential_request":
            return CONFIDENTIAL, "outside_approved_guidance"
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
        turn: FounderTurn,
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
            requested_actions=tuple(a.action for a in evaluation.actions),
            evaluation=evaluation,
        )
        next_state = self._next_state(result, asked)
        return GatewayReply(
            reply=text,
            safe_next_step=step,
            state=state,
            continuation=self._codec.issue(
                next_state,
                company=company.company_id,
                user=user,
                versions=_versions(snapshot),
                message=turn.message,
            ),
            handoff=handoff,
            outcome=result.card,
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
            actions=tuple(a.action for a in evaluation.actions),
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
