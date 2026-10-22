"""What the conversation already covered: for the next turn's questions and wording only.

A persisted conversation keeps, between turns (in its checkpoint):

- ``said``: what the founder stated about a fact (the server's canonical reading of an
  ESTABLISHED_CONVERSATIONAL value, or ``STATED`` for a fact with no canonical form), so a
  fact said many messages ago is still said once the understanding phase no longer sees it;
- ``asked``: per question HeroOS asked, how many times, and how the founder's next message
  related to it the last time (answered it, said they don't know, or didn't answer).

It is never trusted state: no rule reads it, nothing is saved to the Case from it, and it
only ever makes HeroOS ask less (and acknowledge accurately). The founder's newest
statement still controls: a fact they hedge or correct in the current message replaces
what was said before (``carry``).
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from app.evaluation.facts import NOT_SURE, Asked, canonical
from app.evaluation.model import TrustedFactState, Value
from app.evaluation.presentation import display
from app.evaluation.snapshot import WorkflowExecution

MAX_REMEMBERED: Final = 24
# A question the founder didn't answer this many times isn't asked again: HeroOS may say
# why it matters, never repeat it.
MAX_UNANSWERED: Final = 2
# A fact the founder stated that has no canonical form (a methodology fact in their words).
STATED: Final = "stated"
JURISDICTION: Final = "jurisdiction"

# "hedged": the founder answered, but not with certainty ("I think so", "sort of").
Outcome = Literal["pending", "answered", "not_sure", "unanswered", "hedged"]
OUTCOMES: Final[tuple[Outcome, ...]] = (
    "pending", "answered", "not_sure", "unanswered", "hedged",
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class AskRecord:
    times: int
    last: Outcome


@dataclass(frozen=True, slots=True)
class ConversationMemory:
    said: Mapping[str, Value] = field(default_factory=dict)
    asked: Mapping[str, AskRecord] = field(default_factory=dict)

    def settled(self) -> frozenset[str]:
        """What is never asked again: said, answered, not known, or ignored too often."""
        done = {
            key
            for key, record in self.asked.items()
            if record.last in ("answered", "not_sure")
            or (record.last in ("unanswered", "hedged") and record.times >= MAX_UNANSWERED)
        }
        return frozenset({*self.said, *done})

    def not_known(self) -> frozenset[str]:
        said = {k for k, v in self.said.items() if v == NOT_SURE}
        return frozenset(said | {k for k, r in self.asked.items() if r.last == "not_sure"})


def _bounded[V](items: Mapping[str, V]) -> dict[str, V]:
    """The newest entries (insertion order), at most ``MAX_REMEMBERED``."""
    return dict(list(items.items())[-MAX_REMEMBERED:])


def said_values(execution: WorkflowExecution, facts: TrustedFactState) -> dict[str, Value]:
    """This turn's conversational readings as the memory keeps them (canonical, or STATED)."""
    values: dict[str, Value] = {}
    for key, said in facts.conversational.items():
        if key in facts.engine:
            continue  # trusted: the continuation and the Case hold it
        schema = execution.schemas.get(key)
        value = None if schema is None else canonical(schema, said)
        values[key] = value if value is not None else STATED
    return values


def carry(
    execution: WorkflowExecution,
    facts: TrustedFactState,
    memory: ConversationMemory,
    *,
    hedged: Collection[str],
) -> dict[str, str]:
    """What the founder said earlier that this turn's understanding didn't read again.

    Readings only (ESTABLISHED_CONVERSATIONAL, never trusted). A key the current
    message stated, hedged or corrected is left out: the newest statement controls.
    """
    carried: dict[str, str] = {}
    for key, value in memory.said.items():
        if key in facts.conversational or key in facts.engine or key in hedged:
            continue
        if value != STATED and key in execution.schemas:
            carried[key] = str(value)
    return carried


def resolve(
    memory: ConversationMemory,
    *,
    previous: Sequence[Asked],
    facts: TrustedFactState | None,
    stated: Collection[str],
    answered: bool,
    does_not_know: bool,
    jurisdiction_answered: bool,
    said: Mapping[str, Value],
    hedged: Collection[str],
    replied: bool = False,
) -> ConversationMemory:
    """The memory after the founder's message: how it related to what HeroOS asked last turn.

    ``stated``: fact keys the current message stated; ``answered``: it answered the one
    question asked (a direct answer); ``does_not_know``: the understanding read that the
    founder doesn't know the answer; ``said``: this turn's readings (``said_values``).
    """
    asked = dict(memory.asked)
    single = len(previous) == 1
    for question in previous:
        key = JURISDICTION if question.kind == "jurisdiction" else question.key
        if question.kind == "insistence":
            continue  # its safeguard's protocol, asked again by design
        record = asked.get(key, AskRecord(1, "pending"))
        values = () if facts is None else (facts.engine.get(key), facts.conversational.get(key))
        outcome: Outcome
        if question.kind == "jurisdiction":
            outcome = "answered" if jurisdiction_answered else "unanswered"
            if does_not_know and single:
                outcome = "not_sure"
            elif replied and outcome == "unanswered" and single:
                # Answered in their own words, which the server can't read as yes or no.
                outcome = "hedged"
        elif NOT_SURE in values:
            outcome = "not_sure"
        elif key in stated or (answered and single):
            outcome = "answered"
        elif does_not_know and single:
            outcome = "not_sure"
        elif key in hedged:
            outcome = "hedged"
        else:
            outcome = "unanswered"
        asked[key] = AskRecord(record.times, outcome)
    kept = {k: v for k, v in memory.said.items() if k not in hedged}
    kept.update(said)
    return ConversationMemory(said=_bounded(kept), asked=_bounded(asked))


def record(memory: ConversationMemory, asked: Sequence[tuple[str, str]]) -> ConversationMemory:
    """The memory after HeroOS's reply: the questions it asked now (kind, key)."""
    questions = dict(memory.asked)
    for kind, key in asked:
        if kind == "insistence":
            continue
        key = JURISDICTION if kind == "jurisdiction" else key
        earlier = questions.pop(key, None)
        questions[key] = AskRecord((0 if earlier is None else earlier.times) + 1, "pending")
    return ConversationMemory(said=memory.said, asked=_bounded(questions))


REPLIES: Final[Mapping[Outcome, str]] = {
    "answered": "answered it",
    "not_sure": "said they don't know (acknowledge that it's still unclear; don't ask it again)",
    "unanswered": ("didn't answer it (never treat it as answered; answer what they actually said)"),
    "hedged": (
        "answered it without being certain (acknowledge the uncertainty; never treat it as settled)"
    ),
}


def conversation_view(
    execution: WorkflowExecution | None,
    labels: Mapping[str, str],
    facts: TrustedFactState | None,
    memory: ConversationMemory,
    previous: Sequence[Asked],
    established: Sequence[tuple[str, str]] = (),
) -> dict[str, object]:
    """The compact, server-owned conversation state the response phase reads.

    What is known (confirmed, or said by the founder), what the founder doesn't know,
    what HeroOS asked without an answer, and how the current message related to the last
    question. Labels and display values only: never a key, an id or a raw record.
    """
    schemas = {} if execution is None else execution.schemas

    def label(key: str) -> str:
        return (
            labels.get(key, "")
            if key != JURISDICTION
            else ("which employment jurisdiction applies to this employee")
        )

    known: list[dict[str, object]] = []
    seen: set[str] = set()
    engine = {} if facts is None else facts.engine
    conversational = {} if facts is None else facts.conversational
    sources = {} if facts is None else facts.sources
    for key, value in engine.items():
        if value == NOT_SURE or sources.get(key) == "blueprint" or not label(key):
            continue
        known.append({"about": label(key), "value": display(schemas.get(key), value),
                      "status": "confirmed by the founder"})  # fmt: skip
        seen.add(key)
    for key, value in {**memory.said, **conversational}.items():
        if key in seen or key in engine or value in (NOT_SURE, "not sure") or not label(key):
            continue
        shown = "see the conversation" if value == STATED else display(schemas.get(key), value)
        known.append({"about": label(key), "value": shown, "status": "said by the founder"})
        seen.add(key)
    for key, value in established:
        # This turn's explicit statements, as the founder put them (no execution profile needed).
        if key not in seen and value not in (NOT_SURE, "not sure") and label(key):
            known.append({"about": label(key), "value": value, "status": "said by the founder"})
            seen.add(key)
    not_known = {*memory.not_known(), *(k for k, v in engine.items() if v == NOT_SURE),
                 *(k for k, v in conversational.items() if v == NOT_SURE)}  # fmt: skip
    unanswered = [
        label(k)
        for k, r in memory.asked.items()
        if r.last == "unanswered" and k not in seen and k not in not_known and label(k)
    ]
    view: dict[str, object] = {
        "known": known,
        "founder_does_not_know": sorted(label(k) for k in not_known if label(k)),
        "asked_before_without_an_answer": unanswered,
        "answered_without_certainty": [
            label(k) for k, r in memory.asked.items() if r.last == "hedged" and label(k)
        ],
    }
    last = [q for q in previous if q.kind != "insistence"]
    if last:
        question = last[0]
        key = JURISDICTION if question.kind == "jurisdiction" else question.key
        outcome = memory.asked.get(key, AskRecord(1, "unanswered")).last
        if label(key) and outcome in REPLIES:
            view["last_question"] = {"about": label(key), "founder_reply": REPLIES[outcome]}
    return view
