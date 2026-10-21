"""One founder turn through the gateway: readiness, limits, two phases, checks and fallbacks.

``AiGateway.respond`` runs, in order:

1. **Readiness** (no model request otherwise): enabled, a provider and model,
   the provider's key, the deployment's approval reference, an installed
   knowledge bundle (``knowledge_unavailable`` short-circuits: no model
   request, no general answer), and production-approved knowledge unless
   development knowledge is explicitly allowed (never in production).
2. **Usage limits** (``app.assistant.limits``): per account and service-wide.
3. **Understanding**: one request (and at most one schema repair); the
   founder's own messages only. Facts are kept only with real evidence.
4. **Routing** without a model: another HR matter, a non-HR request, a request
   for HeroOS's internal material and an unclear message each get a fixed
   reply (no second request); so do an unsupported or conflicting knowledge
   result.
5. **Retrieval and planning** (``planning``): ``get_knowledge_context`` with the
   validated route, the Blueprint's jurisdiction and the established facts;
   the server's question targets and the decisions asked about.
6. **Grounded response**: one request (and at most one schema repair) on the
   minimized knowledge view; then the grounding and reply checks. A reply
   that fails either, or a second invalid output, is replaced by a reply the
   server composes from fixed text and the plan (never from the model).

At most four provider requests per founder turn, inside one time budget.
A provider failure (rate limit, timeout, anything else) is never retried and
never answered by anything else: the turn fails with a fixed kind.

The result carries a ``Handoff`` (server-side only: never sent to the browser
or stored) describing the understanding for the deterministic workflow work
that follows (M2-NEW-06), with the runtime bundle digest it was built on.
"""

import logging
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from app.assistant.gateway.catalog import EMPTY_CATALOG, routing_catalog
from app.assistant.gateway.continuation import Continuations
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
)
from app.assistant.limits import UsageLimits
from app.assistant.provider import AssistantError, ChatTurn, Completion, StructuredChatProvider
from app.assistant.response_safety import gateway_problem
from app.companies.blueprint import CompanyBlueprintContext
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
# How the turn was handled, for the browser. Deliberately not an outcome:
# nothing here is Guidance, Warning, Block or Expert Review (M2-NEW-06).
ConversationState = Literal["responded", "clarifying", "outside_approved_guidance"]

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
    "That's outside what HeroOS can help with, so I won't offer a general answer. HeroOS's "
    "approved guidance currently covers: {coverage}. For this, a qualified specialist or "
    "consultancy is the right place to go. If you have a workplace conduct or disciplinary "
    "situation, tell me about it in your own words."
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
}
OPEN_QUESTION: Final = "What would you like to work through next?"
QUESTION_WORDS: Final = frozenset({"whether", "what", "which", "how", "when", "who", "where", "if"})


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
    """The understanding for the next layer (M2-NEW-06). Server-side only; never persisted here."""

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


@dataclass(slots=True)
class Telemetry:
    """Operational facts only: never a message, fact, reply, prompt or knowledge text."""

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


@dataclass(frozen=True, slots=True)
class GatewayReply:
    reply: str
    safe_next_step: str | None
    state: ConversationState
    continuation: str
    handoff: Handoff


class _Deadline:
    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._end = clock() + TURN_SECONDS

    def call_timeout(self) -> float:
        remaining = self._end - self._clock()
        if remaining < MIN_CALL_SECONDS:
            raise GatewayFailure("timeout")
        return min(CALL_SECONDS, remaining)


def _label(target: QuestionTarget) -> str:
    return re.sub(r"\s*\([^)]*\)", "", target.label).strip().rstrip(".")


def target_question(target: QuestionTarget) -> str:
    """A plain question about a target, for a reply the server composes."""
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


class AiGateway:
    def __init__(
        self,
        *,
        enabled: bool,
        provider: StructuredChatProvider | None,
        bundle: KnowledgeBundle | None,
        approval: str | None,
        allow_development_knowledge: bool,
        limits: UsageLimits,
        clock: Callable[[], float] = time.monotonic,
        continuations: Continuations | None = None,
    ) -> None:
        self.enabled = enabled
        self.provider = provider
        self.bundle = bundle
        self.approval = approval
        self.allow_development_knowledge = allow_development_knowledge
        self.limits = limits
        self._clock = clock
        self.catalog = EMPTY_CATALOG if bundle is None else routing_catalog(bundle)
        self._labels = internal_labels(bundle) if bundle is not None else re.compile(r"(?!x)x")
        self._continuations = continuations or Continuations(
            [] if bundle is None else [f.key for f in bundle.facts],
            "" if bundle is None else bundle.runtime_digest,
        )

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
        provider, bundle = self.provider, self.bundle
        assert provider is not None and bundle is not None
        exceeded = self.limits.acquire(str(company.current_user.user_id))
        if exceeded is not None:
            logger.info("AI gateway turn refused (outcome=%s_limit, calls=0)", exceeded.scope)
            raise GatewayFailure("rate_limited", retry_after=exceeded.retry_after)

        started = self._clock()
        telemetry = Telemetry(provider=provider.name, model=provider.model)
        try:
            result = self._turn(provider, bundle, company, turn, telemetry, _Deadline(self._clock))
        except GatewayFailure as failure:
            telemetry.outcome = failure.kind
            self._log(telemetry, bundle, started, logging.WARNING)
            raise
        self._log(telemetry, bundle, started, logging.INFO)
        return result

    def _turn(
        self, provider: StructuredChatProvider, bundle: KnowledgeBundle,
        company: CompanyBlueprintContext, turn: FounderTurn, telemetry: Telemetry,
        deadline: _Deadline,
    ) -> GatewayReply:  # fmt: skip
        founder = _recent_founder_messages(turn)
        user = company.current_user.user_id
        asked_before = self._continuations.read(turn.continuation, company.company_id, user)
        facts = {f.key: f.label for f in bundle.facts}

        understanding = self._understand(
            provider, company, founder, [facts[k] for k in asked_before], telemetry, deadline
        )
        understanding, dropped = check_evidence(
            understanding, self.catalog, founder, company_text(company)
        )
        telemetry.facts_rejected = dropped

        fixed = self._routed(understanding)
        if fixed is not None:
            text, state = fixed
            return self._reply(company, text, None, state, (), understanding, None, bundle)

        plan = plan_turn(bundle, understanding, company)
        status = plan.context.status
        telemetry.knowledge_status = status.value
        if status is KnowledgeStatus.BUNDLE_UNAVAILABLE:
            raise GatewayFailure("knowledge_unavailable")
        if status is KnowledgeStatus.UNSUPPORTED:
            return self._reply(
                company, NO_APPROVED_CONTENT, None, "outside_approved_guidance", (),
                understanding, plan, bundle,
            )  # fmt: skip
        if status is KnowledgeStatus.SOURCE_CONFLICT:
            return self._reply(
                company, SOURCE_CONFLICT, None, "outside_approved_guidance", (), understanding,
                plan, bundle,
            )  # fmt: skip

        view = knowledge_view(bundle, plan)
        sections = {
            "approved_knowledge": view.data,
            "company_context": company_view(company),
            "established_facts": [
                {"about": facts[f.fact_key], "value": f.value} for f in plan.established
            ],
            "jurisdiction_note": self._jurisdiction_note(plan),
            "conversation": _recent_conversation(turn),
            "current_message": turn.message,
        }
        offered = [t.id for t in plan.targets]
        proposal = self._phase(
            provider, RESPONSE_INSTRUCTION, [data_message(sections)], RESPONSE_TEMPERATURE,
            RESPONSE_TOKENS, lambda text: parse_response(text, offered), "b", telemetry, deadline,
            fail_soft=True,
        )  # fmt: skip
        if proposal is None:
            telemetry.outcome = "invalid_output_fallback"
            return self._fallback(company, "invalid", understanding, plan, bundle)

        texts = [proposal.reply] + ([proposal.safe_next_step] if proposal.safe_next_step else [])
        problem = next((p for p in (gateway_problem(t) for t in texts) if p is not None), None)
        if problem is not None:
            telemetry.safety = problem
            return self._fallback(company, FALLBACK_FAMILY[problem], understanding, plan, bundle)
        grounding = check_grounding(
            texts,
            knowledge=view.texts,
            founder=founder,
            jurisdiction=plan.context.jurisdiction,
            prohibited=plan.context.prohibited_behaviors,
            labels=self._labels,
            instructions=RESPONSE_INSTRUCTION + UNDERSTANDING_INSTRUCTION,
        )
        if grounding is not None:
            telemetry.grounding = grounding
            return self._fallback(company, "legal", understanding, plan, bundle)
        asked = tuple(t.fact_key for t in plan.targets if t.id in proposal.target_ids)
        return self._reply(
            company, proposal.reply, proposal.safe_next_step, "responded", asked, understanding,
            plan, bundle,
        )  # fmt: skip

    # --- phases -----------------------------------------------------------------------

    def _understand(
        self, provider: StructuredChatProvider, company: CompanyBlueprintContext,
        founder: Sequence[str], asked_labels: Sequence[str], telemetry: Telemetry,
        deadline: _Deadline,
    ) -> UnderstandingProposal:  # fmt: skip
        sections = {
            "routing_catalog": self.catalog.model_view(),
            "company_context": company_view(company),
            "previous_question_about": list(asked_labels),
            "founder_messages": [{"turn": i, "text": text} for i, text in enumerate(founder)],
        }
        current = len(founder) - 1
        result = self._phase(
            provider, UNDERSTANDING_INSTRUCTION, [data_message(sections)],
            UNDERSTANDING_TEMPERATURE, UNDERSTANDING_TOKENS,
            lambda text: parse_understanding(text, self.catalog, current_turn=current), "a",
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

    def _routed(self, understanding: UnderstandingProposal) -> tuple[str, ConversationState] | None:
        coverage = ", ".join(self.catalog.coverage())
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
        self, company: CompanyBlueprintContext, family: str,
        understanding: UnderstandingProposal, plan: TurnPlan, bundle: KnowledgeBundle,
    ) -> GatewayReply:  # fmt: skip
        """A reply composed only from fixed text and the plan (no model text survives)."""
        parts = [FALLBACK_LEADS[family]]
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
                "Jurisdiction-specific guidance needs your company's employment jurisdiction to "
                "be confirmed in your Company Blueprint first."
            )
        elif plan.jurisdiction_state == "conversation_conflict":
            parts.append("HeroOS needs to confirm which legal entity employs this person.")
        target = plan.targets[0] if plan.targets else None
        parts.append(target_question(target) if target is not None else OPEN_QUESTION)
        asked = (target.fact_key,) if target is not None else ()
        return self._reply(
            company, " ".join(parts), None, "responded", asked, understanding, plan, bundle
        )

    def _reply(
        self, company: CompanyBlueprintContext, text: str, step: str | None,
        state: ConversationState, asked: tuple[str, ...], understanding: UnderstandingProposal,
        plan: TurnPlan | None, bundle: KnowledgeBundle,
    ) -> GatewayReply:  # fmt: skip
        user = company.current_user.user_id
        context = None if plan is None else plan.context
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
            asked=asked,
            runtime_bundle_digest=bundle.runtime_digest,
        )
        return GatewayReply(
            reply=text,
            safe_next_step=step,
            state=state,
            continuation=self._continuations.issue(company.company_id, user, asked),
            handoff=handoff,
        )

    def _log(
        self, telemetry: Telemetry, bundle: KnowledgeBundle, started: float, level: int
    ) -> None:
        logger.log(
            level,
            "AI gateway turn (provider=%s, model=%s, outcome=%s, calls=%d, repairs=%s, "
            "knowledge_status=%s, runtime_bundle_digest=%s, safety=%s, grounding=%s, "
            "facts_rejected=%d, prompt_tokens=%d, completion_tokens=%d, latency_ms=%d)",
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
        )
