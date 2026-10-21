"""From a validated understanding to the knowledge request and what HeroOS asks next.

Everything here is deterministic server logic over trusted inputs:

- **Jurisdiction** comes from the canonical Company Blueprint only: its
  operator-confirmed employment jurisdiction, while guidance is allowed. A
  model can make it *less* certain (the founder's words suggest a different
  employing entity: ``jurisdiction_conflict``), never more: then nothing
  jurisdiction-specific is retrieved and HeroOS asks.
- **Known facts** are the explicit, confident statements the founder made
  (``FactProposal.establishes``). When the founder corrects something, the
  newest statement wins. An inferred or approximate value never establishes a
  fact, and nothing HeroOS said ever does.
- **The knowledge request** is narrow: the topics when there are any, else the
  pathway, else general orientation. The model never chooses a Condition or a
  document, and never calls the runtime itself.
- **Question targets** are the facts the approved methodology still needs, in
  the runtime's order, safety first:

  0. facts a blocking or escalating Condition needs, when it bears on what
     the founder raised (a routing prerequisite, or a Condition of the topics
     asked about) and doesn't only gate a decision already held for review;
  1. the methodology's (for a serious allegation: the investigation first),
     unless it only serves decisions held for review;
  2. the decisions the founder asked about that the approved content covers;
  3. other cautions, and what a specialist would need for a decision held
     for review (gathered, never a gate the conversation can clear);
  4. decisions nobody asked about.

  Facts held only for document preparation (outside this conversation),
  sensitive facts and Blueprint facts are never asked here. One target by
  default; a second only when the same approved item needs it.

The plan describes; it never decides. Nothing here says a Condition fired,
an option is allowed or a stage is complete.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from app.assistant.gateway.catalog import extractable
from app.assistant.gateway.proposals import FactProposal, UnderstandingProposal
from app.companies.blueprint import CompanyBlueprintContext
from app.knowledge.bundle import KnowledgeBundle
from app.knowledge.context import (
    KnowledgeContext,
    KnowledgeQuery,
    KnowledgeStatus,
    NextStep,
    get_knowledge_context,
)

MAX_TARGETS: Final = 2
# Condition actions whose facts come first (their safeguard matters most).
SAFEGUARD_ACTIONS: Final = frozenset({"block", "escalate"})

JurisdictionState = Literal["confirmed", "company_unconfirmed", "conversation_conflict"]
TargetMode = Literal["ask", "confirm"]
# M2-NEW-06: a fact, a confirmation of a canonical value, a two-state caution's insistence
# question, or the employee's jurisdiction.
TargetKind = Literal["fact", "confirm", "insistence", "jurisdiction"]


@dataclass(frozen=True, slots=True)
class QuestionTarget:
    """Something HeroOS needs to establish next. ``id`` is per turn ("q1"), never a fact key."""

    id: str
    fact_key: str
    label: str
    # "confirm": the founder said something close but not explicit or exact.
    mode: TargetMode
    kind: TargetKind = "fact"
    # confirm: the canonical value to confirm; insistence: the held action's id.
    candidate: str | int | None = None
    # The server's own wording of the question (a deterministic check needs this answer).
    question: str | None = None


@dataclass(frozen=True, slots=True)
class ActionNote:
    """A decision the founder asked about, as the approved content treats it (never a ruling)."""

    title: str
    # The runtime's availability in this jurisdiction: supported (still the
    # employer's decision, after every required step), review_required or not_available.
    availability: str
    requires_completed_investigation: bool
    requires_employee_response: bool


@dataclass(frozen=True, slots=True)
class TurnPlan:
    query: KnowledgeQuery
    context: KnowledgeContext
    jurisdiction_state: JurisdictionState
    # The founder's established facts (newest explicit statement per key).
    established: tuple[FactProposal, ...]
    targets: tuple[QuestionTarget, ...]
    # The decisions the founder asked about (their topics' options), action-scoped.
    requested_actions: tuple[ActionNote, ...]
    # Requested topics left out because their approved material is in conflict.
    conflicted_topics: tuple[str, ...]


def jurisdiction_input(
    company: CompanyBlueprintContext, understanding: UnderstandingProposal
) -> tuple[str | None, JurisdictionState]:
    """The trusted jurisdiction for the knowledge request, and why there is none."""
    confirmed = company.jurisdiction
    if not confirmed.guidance_allowed or confirmed.employment_jurisdiction is None:
        return None, "company_unconfirmed"
    if "jurisdiction_conflict" in understanding.uncertainties:
        return None, "conversation_conflict"
    return confirmed.employment_jurisdiction, "confirmed"


def established_facts(understanding: UnderstandingProposal) -> tuple[FactProposal, ...]:
    """One fact per key: the newest explicit statement (a correction replaces the earlier one).

    A Blueprint-sourced proposal ranks before every founder message, so what
    the founder says in this conversation wins over the Blueprint's notes.
    """
    newest: dict[str, FactProposal] = {}

    def turn(fact: FactProposal) -> int:
        return -1 if fact.source_turn is None else fact.source_turn

    for fact in understanding.facts:
        current = newest.get(fact.fact_key)
        if current is None or turn(fact) >= turn(current):
            newest[fact.fact_key] = fact
    return tuple(f for f in newest.values() if f.establishes)


def _query(
    understanding: UnderstandingProposal,
    workflow: str,
    jurisdiction: str | None,
    topics: tuple[str, ...],
    known: frozenset[str],
    company: CompanyBlueprintContext,
) -> KnowledgeQuery:
    return KnowledgeQuery(
        workflow=workflow,
        jurisdiction=jurisdiction,
        # Topics are narrower than a pathway: the pathway narrows only when none were named.
        pathway=None if topics else understanding.pathway,
        topics=topics,
        known_facts=known,
        company=company,
    )


def retrieve(
    bundle: KnowledgeBundle | None,
    understanding: UnderstandingProposal,
    company: CompanyBlueprintContext,
    established: Sequence[FactProposal],
) -> tuple[KnowledgeQuery, KnowledgeContext, tuple[str, ...], JurisdictionState]:
    """The knowledge request and the runtime's answer.

    When several topics were named and the runtime reports a source conflict,
    each topic is asked on its own and only the conflicted ones are left out
    (the conflict is about that route, not the whole conversation). Every
    answer still comes from ``get_knowledge_context``.
    """
    assert understanding.workflow is not None
    jurisdiction, state = jurisdiction_input(company, understanding)
    known = frozenset(f.fact_key for f in established)
    topics = understanding.topics
    query = _query(understanding, understanding.workflow, jurisdiction, topics, known, company)
    context = get_knowledge_context(bundle, query)
    conflicted: tuple[str, ...] = ()
    if context.status is KnowledgeStatus.SOURCE_CONFLICT and len(topics) > 1:
        conflicted = tuple(
            t
            for t in topics
            if get_knowledge_context(
                bundle,
                _query(understanding, understanding.workflow, jurisdiction, (t,), known, company),
            ).status
            is KnowledgeStatus.SOURCE_CONFLICT
        )
        remaining = tuple(t for t in topics if t not in conflicted)
        if remaining:
            query = _query(
                understanding, understanding.workflow, jurisdiction, remaining, known, company
            )
            context = get_knowledge_context(bundle, query)
    return query, context, conflicted, state


def _tiers(
    bundle: KnowledgeBundle, context: KnowledgeContext, topics: Iterable[str]
) -> list[tuple[int, str, str]]:
    """(tier, fact key, the approved item that needs it), in the runtime's order per tier."""
    requested = set(topics)
    asked = {o for t in bundle.topics if t.key in requested for o in t.options}
    held = {s.option_id for s in context.supported_next_steps if s.availability != "supported"}
    gating_held = {
        c for s in context.supported_next_steps if s.option_id in held for c in s.conditions
    }
    found: list[tuple[int, str, str]] = []
    for info in context.condition_metadata:
        condition = bundle.condition(info.id)
        if info.enforcement_status != "active" or condition is None:
            continue
        bears = condition.workflow == "global" or bool(set(condition.topics) & requested)
        safeguard = info.action in SAFEGUARD_ACTIONS and bears and info.id not in gating_held
        found += [
            (0 if safeguard else 3, key, f"condition:{info.id}") for key in info.required_facts
        ]
    for item in context.playbook_units:
        unit = next((u for u in bundle.units if u.id == item.id), None)
        if unit is not None:
            # Methodology that only serves decisions held for review is gathered, not asked first.
            only_held = bool(unit.options) and set(unit.options) <= held
            found += [
                (3 if only_held else 1, key, f"unit:{unit.id}") for key in unit.required_facts
            ]
    for step in context.supported_next_steps:
        tier = (3 if step.option_id in held else 2) if step.option_id in asked else 4
        found += [(tier, key, f"option:{step.option_id}") for key in step.required_facts]
    return sorted(found, key=lambda entry: entry[0])


def question_targets(
    bundle: KnowledgeBundle,
    context: KnowledgeContext,
    understanding: UnderstandingProposal,
    established: Sequence[FactProposal],
) -> tuple[QuestionTarget, ...]:
    """The highest-priority missing fact, and one more only if the same item needs it."""
    missing = set(context.missing_facts)
    known = {f.fact_key for f in established}
    tentative = {f.fact_key for f in understanding.facts if not f.establishes}
    facts = {f.key: f for f in bundle.facts}
    chosen: list[tuple[str, str]] = []
    for _tier, key, item in _tiers(bundle, context, understanding.topics):
        fact = facts.get(key)
        if fact is None or key not in missing or key in known or not extractable(fact):
            continue
        if any(key == k for k, _ in chosen):
            continue
        if not chosen or item == chosen[0][1]:
            chosen.append((key, item))
        if len(chosen) == MAX_TARGETS:
            break
    return tuple(
        QuestionTarget(
            id=f"q{index}",
            fact_key=key,
            label=facts[key].label,
            mode="confirm" if key in tentative else "ask",
        )
        for index, (key, _item) in enumerate(chosen, start=1)
    )


def requested_actions(
    bundle: KnowledgeBundle, context: KnowledgeContext, topics: Iterable[str]
) -> tuple[ActionNote, ...]:
    """The next steps linked to the topics the founder raised, as the runtime describes them."""
    asked = {o for t in bundle.topics if t.key in set(topics) for o in t.options}
    steps: list[NextStep] = [s for s in context.supported_next_steps if s.option_id in asked]
    return tuple(
        ActionNote(
            title=s.title,
            availability=s.availability,
            requires_completed_investigation=s.requires_completed_investigation,
            requires_employee_response=s.requires_employee_response,
        )
        for s in steps
    )


def plan_turn(
    bundle: KnowledgeBundle | None,
    understanding: UnderstandingProposal,
    company: CompanyBlueprintContext,
) -> TurnPlan:
    established = established_facts(understanding)
    query, context, conflicted, state = retrieve(bundle, understanding, company, established)
    if bundle is None:
        targets: tuple[QuestionTarget, ...] = ()
        actions: tuple[ActionNote, ...] = ()
    else:
        targets = question_targets(bundle, context, understanding, established)
        actions = requested_actions(bundle, context, query.topics)
    return TurnPlan(
        query=query,
        context=context,
        jurisdiction_state=state,
        established=established,
        targets=targets,
        requested_actions=actions,
        conflicted_topics=conflicted,
    )
