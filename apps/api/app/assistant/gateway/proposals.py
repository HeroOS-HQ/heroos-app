"""What the model may propose, and the server's strict validation of it.

Both phases answer with one JSON object. Every object is parsed strictly:
unknown or missing fields, duplicate keys, wrong types, unknown enum values,
oversized fields and ids outside the routing catalog are refused with a
fixed, structural ``ProposalError`` code (never the model's text). The
gateway allows one schema repair per phase.

**Understanding** (``UnderstandingProposal``): the intent, an optional
workflow, pathway and topics from the catalog (unknown is a valid answer),
fact proposals, uncertainty codes, an optional short summary and (M2-NEW-06)
the employer decisions the founder explicitly asked about, by catalog id and
with the founder's own words. It has no field for a Condition, an outcome, a
sanction choice, a transition, a document, a jurisdiction or a legal
conclusion, and none can be added. A requested decision only makes HeroOS
check more: its absence never proves a safeguard doesn't apply.

**Fact proposals** are candidates, never facts. Each names a catalog fact key,
a value, where it comes from (the current or an earlier founder message, or
the canonical Company Blueprint), the turn, a short excerpt and whether the
founder said it explicitly. ``check_evidence`` keeps a proposal only when its
excerpt really appears in that founder message (or in the Blueprint view the
model was given): a model can't manufacture a statement and attribute it to
the founder, and HeroOS's own earlier replies are never a source (the model
isn't shown them in this phase at all). A proposal that fails is dropped,
not repaired: dropping a fact is always the safer direction.

**Grounded response** (``ResponseProposal``): the reply, the server-offered
question targets it used and an optional safe next step. No status, outcome,
review, jurisdiction or reference can be returned: the server owns those.
"""

import json
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from app.assistant.gateway.catalog import CatalogWorkflow, RoutingCatalog

UNDERSTANDING_SCHEMA: Final = "heroos.understanding/1"
RESPONSE_SCHEMA: Final = "heroos.response/1"

Intent = Literal["supported_hr", "other_hr", "unclear", "unsupported", "confidential_request"]
INTENTS: Final[tuple[Intent, ...]] = (
    "supported_hr", "other_hr", "unclear", "unsupported", "confidential_request",
)  # fmt: skip
Confidence = Literal["high", "medium", "low"]
CONFIDENCES: Final[tuple[Confidence, ...]] = ("high", "medium", "low")
Provenance = Literal["current_user_message", "prior_user_message", "company_blueprint"]
PROVENANCES: Final[tuple[Provenance, ...]] = (
    "current_user_message", "prior_user_message", "company_blueprint",
)  # fmt: skip
Basis = Literal["explicit", "inferred"]
BASES: Final[tuple[Basis, ...]] = ("explicit", "inferred")
Uncertainty = Literal[
    "jurisdiction_conflict", "conflicting_statements", "approximate_details", "multiple_matters",
    "unclear_request",
]  # fmt: skip
UNCERTAINTIES: Final[tuple[Uncertainty, ...]] = (
    "jurisdiction_conflict", "conflicting_statements", "approximate_details", "multiple_matters",
    "unclear_request",
)  # fmt: skip

MAX_TOPICS: Final = 3
MAX_FACTS: Final = 12
MAX_UNCERTAINTIES: Final = 5
MAX_VALUE_CHARS: Final = 120
MAX_EXCERPT_CHARS: Final = 160
MAX_SUMMARY_CHARS: Final = 300
MAX_REPLY_CHARS: Final = 1600
MAX_NEXT_STEP_CHARS: Final = 300
MAX_TARGET_IDS: Final = 3
MAX_REQUESTED_ACTIONS: Final = 3

_UNDERSTANDING_FIELDS: Final = frozenset(
    {"schema_version", "intent", "workflow_candidate", "pathway_candidate", "topics",
     "fact_proposals", "uncertainties"}
)  # fmt: skip
_FACT_FIELDS: Final = frozenset(
    {"fact_key", "proposed_value", "confidence", "provenance", "source_turn", "support_excerpt",
     "explicit_or_inferred"}
)  # fmt: skip
_ACTION_FIELDS: Final = frozenset({"action", "source_turn", "support_excerpt"})
_RESPONSE_FIELDS: Final = frozenset({"schema_version", "reply"})
_RESPONSE_OPTIONAL: Final = frozenset({"question_target_ids", "safe_next_step"})


class ProposalError(ValueError):
    """A model output is refused. ``code`` is fixed; ``location`` is structural only."""

    def __init__(self, code: str, location: str = "$") -> None:
        self.code = code
        self.location = location
        super().__init__(f"{code} at {location}")


@dataclass(frozen=True, slots=True)
class FactProposal:
    fact_key: str
    value: str
    confidence: Confidence
    provenance: Provenance
    # The founder message's index (oldest first); None for the Blueprint.
    source_turn: int | None
    # Server-side only: never logged, never returned to the browser.
    excerpt: str
    basis: Basis

    @property
    def establishes(self) -> bool:
        """Only an explicit, confident statement counts as a known fact for this turn."""
        return self.basis == "explicit" and self.confidence != "low"


@dataclass(frozen=True, slots=True)
class RequestedAction:
    """An employer decision the founder explicitly asked about (catalog option id)."""

    action: str
    source_turn: int
    # Server-side only: never logged, never returned to the browser.
    excerpt: str


@dataclass(frozen=True, slots=True)
class UnderstandingProposal:
    intent: Intent
    workflow: str | None
    pathway: str | None
    topics: tuple[str, ...]
    facts: tuple[FactProposal, ...]
    uncertainties: tuple[Uncertainty, ...]
    summary: str | None
    actions: tuple[RequestedAction, ...] = ()
    # M2-NEW-07: decisions the founder says (now) they no longer consider; kept only when
    # ``check_evidence`` finds their own explicit words.
    withdrawn: tuple[RequestedAction, ...] = ()


@dataclass(frozen=True, slots=True)
class ResponseProposal:
    reply: str
    target_ids: tuple[str, ...]
    safe_next_step: str | None


# --- strict JSON ----------------------------------------------------------------------


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise ProposalError("duplicate_key")
        data[key] = value
    return data


def _no_constants(_: str) -> object:
    raise ProposalError("invalid_number")


def _load(text: str) -> dict[str, object]:
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constants)
    except json.JSONDecodeError:
        raise ProposalError("invalid_json") from None
    if not isinstance(data, dict):
        raise ProposalError("expected_object")
    return data


def _fields(
    data: Mapping[str, object], required: frozenset[str], optional: frozenset[str], where: str
) -> None:
    keys = set(data)
    if keys - required - optional:
        raise ProposalError("unknown_field", where)
    if required - keys:
        raise ProposalError("missing_field", where)


def _text(value: object, limit: int, where: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ProposalError("expected_string", where)
    value = value.strip()
    if not value or len(value) > limit:
        raise ProposalError("bad_length", where)
    if any(unicodedata.category(c) == "Cc" and c not in "\n\t" for c in value):
        raise ProposalError("control_character", where)
    return value


def _code[T: str](value: object, allowed: Sequence[T], where: str) -> T:
    if not isinstance(value, str) or value not in allowed:
        raise ProposalError("unknown_value", where)
    return cast(T, value)


def _list(value: object, limit: int, where: str) -> list[object]:
    if not isinstance(value, list):
        raise ProposalError("expected_list", where)
    if len(value) > limit:
        raise ProposalError("too_many", where)
    return value


def _unique(values: Sequence[str], where: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ProposalError("duplicate_value", where)
    return tuple(values)


# --- understanding --------------------------------------------------------------------


def _fact(raw: object, where: str, current_turn: int) -> FactProposal:
    if not isinstance(raw, dict):
        raise ProposalError("expected_object", where)
    _fields(raw, _FACT_FIELDS, frozenset(), where)
    key = _text(raw["fact_key"], 100, f"{where}.fact_key")
    provenance = _code(raw["provenance"], PROVENANCES, f"{where}.provenance")
    turn = raw["source_turn"]
    if provenance == "company_blueprint":
        if turn is not None:
            raise ProposalError("bad_turn", f"{where}.source_turn")
    else:
        if not isinstance(turn, int) or isinstance(turn, bool):
            raise ProposalError("bad_turn", f"{where}.source_turn")
        expected = (
            turn == current_turn
            if provenance == "current_user_message"
            else 0 <= turn < current_turn
        )
        if not expected:
            raise ProposalError("bad_turn", f"{where}.source_turn")
    assert key is not None
    value = _text(raw["proposed_value"], MAX_VALUE_CHARS, f"{where}.proposed_value")
    excerpt = _text(raw["support_excerpt"], MAX_EXCERPT_CHARS, f"{where}.support_excerpt")
    assert value is not None and excerpt is not None
    return FactProposal(
        fact_key=key,
        value=value,
        confidence=_code(raw["confidence"], CONFIDENCES, f"{where}.confidence"),
        provenance=provenance,
        source_turn=turn if provenance != "company_blueprint" else None,
        excerpt=excerpt,
        basis=_code(raw["explicit_or_inferred"], BASES, f"{where}.explicit_or_inferred"),
    )


def parse_understanding(
    text: str, catalog: RoutingCatalog, *, current_turn: int
) -> UnderstandingProposal:
    """The understanding phase's object, strictly validated against the catalog.

    Fact keys outside the catalog are kept here and dropped by
    ``check_evidence`` (a fact-level refusal, not a structural one).
    """
    data = _load(text)
    _fields(
        data,
        _UNDERSTANDING_FIELDS,
        frozenset({"case_summary", "requested_actions", "withdrawn_actions"}),
        "$",
    )
    if data["schema_version"] != UNDERSTANDING_SCHEMA:
        raise ProposalError("unknown_schema", "$.schema_version")
    intent = _code(data["intent"], INTENTS, "$.intent")

    workflow_key = data["workflow_candidate"]
    workflow = None
    if workflow_key is not None:
        if not isinstance(workflow_key, str):
            raise ProposalError("expected_string", "$.workflow_candidate")
        workflow = catalog.workflow(workflow_key)
        if workflow is None:
            raise ProposalError("unknown_workflow", "$.workflow_candidate")
        if intent != "supported_hr":
            raise ProposalError("inconsistent_intent", "$.workflow_candidate")

    pathway = data["pathway_candidate"]
    if pathway is not None and (
        workflow is None or not isinstance(pathway, str) or not workflow.has_pathway(pathway)
    ):
        raise ProposalError("unknown_pathway", "$.pathway_candidate")

    topics: list[str] = []
    for i, topic in enumerate(_list(data["topics"], MAX_TOPICS, "$.topics")):
        if workflow is None or not isinstance(topic, str) or not workflow.has_topic(topic):
            raise ProposalError("unknown_topic", f"$.topics[{i}]")
        topics.append(topic)

    facts = tuple(
        _fact(raw, f"$.fact_proposals[{i}]", current_turn)
        for i, raw in enumerate(_list(data["fact_proposals"], MAX_FACTS, "$.fact_proposals"))
    )
    uncertainties = [
        _code(u, UNCERTAINTIES, f"$.uncertainties[{i}]")
        for i, u in enumerate(_list(data["uncertainties"], MAX_UNCERTAINTIES, "$.uncertainties"))
    ]
    summary = _text(data.get("case_summary"), MAX_SUMMARY_CHARS, "$.case_summary", nullable=True)
    actions = _actions(data, "requested_actions", workflow, current_turn)
    withdrawn = _actions(data, "withdrawn_actions", workflow, current_turn)
    return UnderstandingProposal(
        intent=intent,
        workflow=None if workflow is None else workflow.key,
        pathway=pathway,
        topics=_unique(topics, "$.topics"),
        facts=facts,
        uncertainties=cast(tuple[Uncertainty, ...], _unique(uncertainties, "$.uncertainties")),
        summary=summary,
        actions=actions,
        withdrawn=withdrawn,
    )


def _actions(
    data: dict[str, Any], field: str, workflow: CatalogWorkflow | None, current_turn: int
) -> tuple[RequestedAction, ...]:
    actions: list[RequestedAction] = []
    for i, raw in enumerate(_list(data.get(field, []), MAX_REQUESTED_ACTIONS, f"$.{field}")):
        where = f"$.{field}[{i}]"
        if not isinstance(raw, dict):
            raise ProposalError("expected_object", where)
        _fields(raw, _ACTION_FIELDS, frozenset(), where)
        key = raw["action"]
        if workflow is None or not isinstance(key, str) or not workflow.has_action(key):
            raise ProposalError("unknown_action", f"{where}.action")
        turn = raw["source_turn"]
        if not isinstance(turn, int) or isinstance(turn, bool) or not 0 <= turn <= current_turn:
            raise ProposalError("bad_turn", f"{where}.source_turn")
        excerpt = _text(raw["support_excerpt"], MAX_EXCERPT_CHARS, f"{where}.support_excerpt")
        assert excerpt is not None
        actions.append(RequestedAction(key, turn, excerpt))
    if len({a.action for a in actions}) != len(actions):
        raise ProposalError("duplicate_value", f"$.{field}")
    return tuple(actions)


# --- evidence -------------------------------------------------------------------------

_QUOTES: Final = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
_SPACE: Final = re.compile(r"\s+")
# Words that withdraw a decision explicitly ("no longer", "decided against"...); a change of
# topic or a vague phrase withdraws nothing.
_WITHDRAWAL: Final = re.compile(
    r"\b(?:no\s+longer|not\s+(?:going|planning)\s+to|not\s+considering|won't|will\s+not"
    r"|decided\s+(?:not|against)|don't\s+want\s+to|do\s+not\s+want\s+to|not\s+anymore"
    r"|changed\s+(?:my|our)\s+mind|dropp(?:ed|ing))\b"
)


def normalized(text: str) -> str:
    """Case, quotes, dashes and whitespace don't change what was said."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    return _SPACE.sub(" ", text).strip().casefold()


def check_evidence(
    proposal: UnderstandingProposal,
    catalog: RoutingCatalog,
    founder_messages: Sequence[str],
    blueprint_text: str,
) -> tuple[UnderstandingProposal, int]:
    """Keep the fact proposals the founder's own words (or the Blueprint) support.

    Returns the proposal with only those facts, and how many were dropped:
    an unknown fact key, an excerpt that isn't in the cited message (or the
    Blueprint view), or a Blueprint-sourced proposal with nothing to cite.
    """
    messages = [normalized(m) for m in founder_messages]
    blueprint = normalized(blueprint_text)
    kept: list[FactProposal] = []
    for fact in proposal.facts:
        excerpt = normalized(fact.excerpt)
        if fact.fact_key not in catalog.facts or not excerpt:
            continue
        if fact.provenance == "company_blueprint":
            source = blueprint
        else:
            assert fact.source_turn is not None
            source = messages[fact.source_turn] if fact.source_turn < len(messages) else ""
        if excerpt in source:
            kept.append(fact)
    # A requested decision needs the founder's own words too (it only ever adds checks).
    actions = tuple(
        a
        for a in proposal.actions
        if normalized(a.excerpt)
        and a.source_turn < len(messages)
        and normalized(a.excerpt) in messages[a.source_turn]
    )
    # A withdrawal only from the current message, in the founder's own explicit words, and
    # never of a decision the same message asks about (withdrawing only removes checks).
    current = len(messages) - 1
    asked = {a.action for a in actions}
    withdrawn = tuple(
        a
        for a in proposal.withdrawn
        if a.source_turn == current
        and a.action not in asked
        and normalized(a.excerpt)
        and normalized(a.excerpt) in messages[current]
        and _WITHDRAWAL.search(normalized(a.excerpt))
    )
    dropped = (
        len(proposal.facts) - len(kept) + len(proposal.actions) - len(actions)
        + len(proposal.withdrawn) - len(withdrawn)
    )  # fmt: skip
    return (
        UnderstandingProposal(
            intent=proposal.intent,
            workflow=proposal.workflow,
            pathway=proposal.pathway,
            topics=proposal.topics,
            facts=tuple(kept),
            uncertainties=proposal.uncertainties,
            summary=proposal.summary,
            actions=actions,
            withdrawn=withdrawn,
        ),
        dropped,
    )


def without_contradicted(
    proposal: UnderstandingProposal, contradicted: Callable[[FactProposal], bool]
) -> UnderstandingProposal:
    """Readings the founder's own words contradict or hedge establish nothing (M2-NEW-06).

    "I did NOT speak to the employee" cited for "discussed: yes" is real words
    and a wrong reading: it becomes an inferred proposal, so HeroOS asks
    instead of relying on it.
    """
    return UnderstandingProposal(
        intent=proposal.intent,
        workflow=proposal.workflow,
        pathway=proposal.pathway,
        topics=proposal.topics,
        facts=tuple(
            FactProposal(
                f.fact_key,
                f.value,
                f.confidence,
                f.provenance,
                f.source_turn,
                f.excerpt,
                "inferred",
            )
            if f.establishes and contradicted(f)
            else f
            for f in proposal.facts
        ),  # fmt: skip
        uncertainties=proposal.uncertainties,
        summary=proposal.summary,
        actions=proposal.actions,
        withdrawn=proposal.withdrawn,
    )


# --- grounded response ----------------------------------------------------------------


def parse_response(text: str, offered_targets: Sequence[str]) -> ResponseProposal:
    data = _load(text)
    _fields(data, _RESPONSE_FIELDS, _RESPONSE_OPTIONAL, "$")
    if data["schema_version"] != RESPONSE_SCHEMA:
        raise ProposalError("unknown_schema", "$.schema_version")
    reply = _text(data["reply"], MAX_REPLY_CHARS, "$.reply")
    assert reply is not None
    ids: list[str] = []
    for i, target in enumerate(
        _list(data.get("question_target_ids", []), MAX_TARGET_IDS, "$.question_target_ids")
    ):
        if not isinstance(target, str) or target not in offered_targets:
            raise ProposalError("unknown_target", f"$.question_target_ids[{i}]")
        ids.append(target)
    step = _text(data.get("safe_next_step"), MAX_NEXT_STEP_CHARS, "$.safe_next_step", nullable=True)
    return ResponseProposal(
        reply=reply, target_ids=_unique(ids, "$.question_target_ids"), safe_next_step=step
    )
