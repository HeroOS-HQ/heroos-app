"""What the conversation already covered: for the next turn's questions and wording only.

A persisted conversation keeps, between turns (in its checkpoint):

- ``said``: what the founder stated about a fact (the server's canonical reading of an
  ESTABLISHED_CONVERSATIONAL value, or ``STATED`` for a fact with no canonical form), so a
  fact said many messages ago is still said once the understanding phase no longer sees it,
  with where it came from (``Reading``: the founder message, and which of its statements);
- ``asked``: per question HeroOS asked, how many times, and how the founder's next message
  related to it the last time (answered it, said they don't know, or didn't answer);
- ``turns``: how many founder messages came before the current one (the messages' numbers).

From these, each question's **coverage** (``coverage``): whether the founder already answered it
in the conversation, plainly, in their own story, without certainty, or said they don't know.
Coverage is about asking, never about trust: a question the founder answered in their story is
not asked again as if they hadn't (found in the final pass: "nobody ever explained the rule to
her", then "had the employee been told what was expected of them?"), while the fact stays as
trusted as it was (a reading the engine can rely on still needs a direct answer or a
confirmation, asked only when a step the founder wants to take needs it).

It is never trusted state: no rule reads it, nothing is saved to the Case from it, and it
only ever makes HeroOS ask less (and acknowledge accurately). The founder's newest
statement still controls: a fact they hedge or correct in the current message replaces
what was said before (``carry``), and so does every reading taken from the same words as
the one they corrected (``superseded``); every other reading stands.
"""

import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from app.evaluation.facts import NOT_SURE, Asked, canonical, normalized
from app.evaluation.model import TrustedFactState, Value
from app.evaluation.presentation import display
from app.evaluation.snapshot import WorkflowExecution

MAX_REMEMBERED: Final = 24
MAX_TURNS: Final = 100_000
# A question the founder didn't answer this many times isn't asked again: HeroOS may say
# why it matters, never repeat it.
MAX_UNANSWERED: Final = 2
# A fact the founder stated that has no canonical form (a methodology fact in their words).
STATED: Final = "stated"
JURISDICTION: Final = "jurisdiction"
# A reading whose words aren't known (kept from before readings recorded their source): never
# taken as resting on another reading's words.
UNKNOWN_WORDS: Final = -1

# How a reading covers its question: "stated" (said plainly: an ESTABLISHED_CONVERSATIONAL
# reading, noted and carried), "implied" (the founder's words clearly imply it without saying it in
# those terms: "she says she just counted it wrong" implies the concern was put to her), "uncertain"
# (with words of doubt: "I think someone may have spoken to her") or "rough" (only roughly or in
# part: "last week"). Only a stated reading is ever said again as the founder's fact: the others
# only keep the question from being asked as if the founder hadn't spoken about it.
Certainty = Literal["stated", "implied", "uncertain", "rough"]
CERTAINTIES: Final[tuple[Certainty, ...]] = ("stated", "implied", "uncertain", "rough")
# Where a question stands in the conversation (``ConversationMemory.coverage``).
Coverage = Literal[
    "unanswered",
    # Trusted: a direct answer, a confirmation, the Blueprint or the continuation.
    "answered_explicitly",
    # Said plainly or clearly implied in the founder's own words, or answered in words the server
    # can't read as the answer: not asked again, confirmed only when a step needs it.
    "answered_from_narrative",
    # Said without certainty, or only roughly: not asked again as if never mentioned.
    "answered_uncertain",
    "unknown_to_founder",
    # The founder said the question doesn't fit their situation.
    "not_applicable",
    # The current message withdrew what was said about it, with nothing in its place.
    "superseded",
]
COVERED: Final[frozenset[Coverage]] = frozenset({"answered_from_narrative", "answered_uncertain"})

# "hedged": the founder answered, but not with certainty ("I think so", "sort of");
# "approximate": they answered only roughly or in part ("last week"), with no doubt in it;
# "not_applicable": they said the question doesn't fit their situation ("n/a, he never came in").
Outcome = Literal[
    "pending", "answered", "not_sure", "unanswered", "hedged", "approximate", "not_applicable"
]
OUTCOMES: Final[tuple[Outcome, ...]] = (
    "pending", "answered", "not_sure", "unanswered", "hedged", "approximate", "not_applicable",
)  # fmt: skip
# Never asked again after one of these replies.
_DONE: Final = frozenset({"answered", "not_sure", "not_applicable"})
# Asked this many times with any of these replies, a question isn't asked again.
_ONCE_MORE: Final = frozenset({"unanswered", "hedged", "approximate", "answered"})


@dataclass(frozen=True, slots=True)
class AskRecord:
    times: int
    last: Outcome


@dataclass(frozen=True, slots=True)
class Reading:
    """What the founder said about one fact, and where it came from: the founder message
    (``turn``; the conversation's first message is 0) and which of that message's statements it
    rests on (``words``: readings taken from the same words share it, so a correction of one is
    a correction of them all)."""

    value: Value
    turn: int
    words: int = UNKNOWN_WORDS
    certainty: Certainty = "stated"


@dataclass(frozen=True, slots=True)
class ConversationMemory:
    said: Mapping[str, Reading] = field(default_factory=dict)
    asked: Mapping[str, AskRecord] = field(default_factory=dict)
    # Founder messages before the current one: the current message is number ``turns``.
    turns: int = 0
    # The step results HeroOS's replies already explained ("<action>:<disposition>"), so a reply
    # never explains the same one again (found in the final run: the same "can't take that step
    # yet" in every reply).
    told: tuple[str, ...] = ()

    def settled(self) -> frozenset[str]:
        """What is never asked again: said, answered, not known, not applicable, or asked often
        enough."""
        done = {
            key
            for key, record in self.asked.items()
            if record.last in _DONE
            or (record.last in _ONCE_MORE and record.times >= MAX_UNANSWERED)
        }
        return frozenset({*self.said, *done})

    def coverage(
        self,
        key: str,
        trusted: Mapping[str, Value] | None = None,
        withdrawn: Collection[str] = (),
    ) -> Coverage:
        """Where the question about ``key`` stands: ``trusted`` holds the turn's ENGINE_TRUSTED
        values, ``withdrawn`` the readings the current message took back (``superseded``)."""
        if trusted is not None and key in trusted:
            return "unknown_to_founder" if trusted[key] == NOT_SURE else "answered_explicitly"
        reading = self.said.get(key)
        record = self.asked.get(key)
        last = None if record is None else record.last
        if (reading is not None and reading.value == NOT_SURE) or last == "not_sure":
            return "unknown_to_founder"
        if last == "not_applicable":
            return "not_applicable"
        if reading is not None:
            stated = reading.certainty in ("stated", "implied")
            return "answered_from_narrative" if stated else "answered_uncertain"
        if last == "answered":
            return "answered_from_narrative"
        if last in ("hedged", "approximate"):
            return "answered_uncertain"
        return "superseded" if key in withdrawn else "unanswered"

    def not_known(self) -> frozenset[str]:
        said = {k for k, r in self.said.items() if r.value == NOT_SURE}
        return frozenset(said | {k for k, r in self.asked.items() if r.last == "not_sure"})

    def asked_enough(self, key: str) -> bool:
        """Whether the question about ``key`` is never asked again: the founder said they don't
        know, or it was asked twice and the founder answered it only in their own words (which
        the server can't rely on), uncertainly, roughly, or not at all."""
        record = self.asked.get(key)
        return record is not None and (
            record.last in ("not_sure", "not_applicable")
            or (record.last in _ONCE_MORE and record.times >= MAX_UNANSWERED)
        )


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
    for key, reading in memory.said.items():
        if key in facts.conversational or key in facts.engine or key in hedged:
            continue
        if reading.certainty != "stated":
            continue  # it only covers the question: never the founder's fact
        if reading.value != STATED and key in execution.schemas:
            carried[key] = str(reading.value)
    return carried


# The words a reading rests on: its content words (four letters or more).
_CONTENT: Final = re.compile(r"[a-z0-9']{4,}")


def same_words(first: str, second: str) -> bool:
    """Whether two texts say the same thing in mostly the same words (two readings of one message,
    or two questions): one contains the other, or most of the shorter one's content words are the
    other's."""
    a, b = normalized(first), normalized(second)
    shorter = a if len(a) <= len(b) else b
    if len(shorter.split()) >= 2 and (a in b or b in a):
        return True
    words_a, words_b = set(_CONTENT.findall(a)), set(_CONTENT.findall(b))
    least = min(len(words_a), len(words_b))
    return least > 0 and len(words_a & words_b) / least >= 0.6


def provenance(
    stated: Sequence[tuple[str, int | None, str]], current: int, turns: int
) -> dict[str, tuple[int, int]]:
    """Where this turn's readings came from: fact key -> (founder message, words).

    ``stated``: (fact key, the number of the message it was read from among the messages the
    understanding read, the founder's words cited), the current message's readings first when a
    fact was read twice; ``current``: the current message's number among them; ``turns``: its
    number in the conversation. Readings of one message whose words overlap share their words.
    """
    groups: dict[int, list[str]] = {}  # message -> the words of each of its statements
    sources: dict[str, tuple[int, int]] = {}
    for key, source, excerpt in stated:
        if source is None or key in sources:
            continue
        message = max(0, turns - (current - source))
        statements = groups.setdefault(message, [])
        words = next((i for i, w in enumerate(statements) if same_words(w, excerpt)), None)
        if words is None:
            words = len(statements)
            statements.append(excerpt)
        sources[key] = (message, words)
    return sources


def superseded(
    memory: ConversationMemory,
    affected: Collection[str],
    read_now: Collection[str],
    unknown: Collection[str] = (),
) -> frozenset[str]:
    """The earlier readings the current message no longer lets stand.

    ``affected``: the facts it corrects (another value) or makes uncertain; with them goes every
    reading taken from the same words of the same message as one of them that the
    understanding doesn't read again now (found live: "it was raised with him before",
    corrected to "that was another operative", left "discussed with him", read from the same
    words). Every other reading stands (found in the final run: a correction of one fact
    dropped every other reading, and those facts were asked for again).

    Only what the founder said plainly takes its words with it. A reading HeroOS drew from
    their words (implied, rough or uncertain) is HeroOS's reading, not their statement, and
    saying they don't know a fact (``unknown``: the affected facts now read as not sure) takes
    back nothing else: found in the certification run, "no idea" about whether he had been told
    the standard, implied from "he already has a written warning for the same thing", dropped
    the warning itself, and the founder was asked about it again.
    """
    dropped = set(affected)
    for key in affected:
        source = memory.said.get(key)
        if (
            source is None
            or source.words == UNKNOWN_WORDS
            or source.certainty != "stated"
            or key in unknown
        ):
            continue
        dropped |= {
            other
            for other, reading in memory.said.items()
            if other not in read_now
            and (reading.turn, reading.words) == (source.turn, source.words)
        }
    return frozenset(dropped)


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
    sources: Mapping[str, tuple[int, int]] | None = None,
    uncertain: Collection[str] = (),
    dropped: Collection[str] = (),
    does_not_apply: bool = False,
    touched: Mapping[str, Value] | None = None,
    implied: Collection[str] = (),
    hesitant: bool = False,
) -> ConversationMemory:
    """The memory after the founder's message: how it related to what HeroOS asked last turn.

    ``stated``: fact keys the current message stated; ``answered``: it answered the one
    question asked (a direct answer); ``does_not_know``: the understanding read that the
    founder doesn't know the answer; ``said``: this turn's readings (``said_values``), with
    where the ones read this turn came from (``sources``, from ``provenance``); ``hedged``:
    facts the current message touched without stating them, ``uncertain`` the ones among them
    with words of doubt (the others it gave only roughly); ``dropped``: earlier readings it no
    longer lets stand (``superseded``); ``does_not_apply``: the founder said the question doesn't
    fit their situation; ``touched``: this turn's readings of the ``hedged`` facts (canonical, or
    ``STATED``), kept as covering their question only (``implied`` the ones the founder's words
    clearly imply, ``uncertain`` the doubtful ones, the others rough); ``hesitant``: the founder
    replied to the question without a plain answer the server could read (words of doubt, or a
    "don't know" in words that don't say it plainly).
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
        elif does_not_apply and single:
            outcome = "not_applicable"
        elif key in hedged:
            # Clearly implied in their words: answered (never asked again as if it weren't).
            outcome = (
                "hedged" if key in uncertain else "answered" if key in implied else "approximate"
            )
        elif hesitant and single:
            # A reply to it without certainty ("I think so but I'm not 100% sure", "how would I
            # know"), with no reading of the fact: an uncertain answer, never "no answer" (found in
            # the coverage pass: asked again later with "one thing I still need to know").
            outcome = "hedged"
        else:
            outcome = "unanswered"
        asked[key] = AskRecord(record.times, outcome)
    kept = {k: r for k, r in memory.said.items() if k not in hedged and k not in dropped}
    for key, value in (touched or {}).items():
        if key not in hedged or key in said:
            continue
        certainty: Certainty = (
            "uncertain" if key in uncertain else "implied" if key in implied else "rough"
        )
        source = (sources or {}).get(key)
        turn, words = source if source is not None else (memory.turns, UNKNOWN_WORDS)
        kept[key] = Reading(value, turn, words, certainty)
    for key, value in said.items():
        source = (sources or {}).get(key)
        before = kept.get(key)
        if source is not None:
            kept[key] = Reading(value, *source)
        elif before is not None and before.certainty == "stated":
            # Carried or noted: still where it came from.
            kept[key] = Reading(value, before.turn, before.words)
        else:
            kept[key] = Reading(value, memory.turns)
    return ConversationMemory(
        said=_bounded(kept),
        asked=_bounded(asked),
        turns=min(memory.turns + 1, MAX_TURNS),
        told=memory.told,
    )


def record(
    memory: ConversationMemory, asked: Sequence[tuple[str, str]], told: Sequence[str] = ()
) -> ConversationMemory:
    """The memory after HeroOS's reply: the questions it asked now (kind, key), and the step
    results it explained (``told``)."""
    questions = dict(memory.asked)
    for kind, key in asked:
        if kind == "insistence":
            continue
        key = JURISDICTION if kind == "jurisdiction" else key
        earlier = questions.pop(key, None)
        questions[key] = AskRecord((0 if earlier is None else earlier.times) + 1, "pending")
    explained = [*memory.told, *(t for t in told if t not in memory.told)][-MAX_REMEMBERED:]
    return ConversationMemory(
        said=memory.said, asked=_bounded(questions), turns=memory.turns, told=tuple(explained)
    )


REPLIES: Final[Mapping[Outcome, str]] = {
    "answered": "answered it",
    "not_sure": "said they don't know (acknowledge that it's still unclear; don't ask it again)",
    "unanswered": ("didn't answer it (never treat it as answered; answer what they actually said)"),
    "hedged": (
        "answered it without being certain (acknowledge the uncertainty; never treat it as settled)"
    ),
    "approximate": (
        "answered it only roughly or in part (acknowledge what they gave as they gave it; they "
        "weren't uncertain, so never say they were)"
    ),
    "not_applicable": (
        "said the question doesn't fit their situation (accept that plainly; never ask it again "
        "or say their reply doesn't count)"
    ),
}


def _labels(
    label: Callable[[str], str],
    memory: ConversationMemory,
    seen: Collection[str],
    *,
    asked: Outcome,
    certainty: Certainty,
) -> list[str]:
    """The questions answered one way: in reply to HeroOS's question, or in the founder's story."""
    keys = [k for k, r in memory.asked.items() if r.last == asked]
    keys += [k for k, r in memory.said.items() if r.certainty == certainty and k not in keys]
    return [label(k) for k in keys if k not in seen and label(k)]


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
    said = {k: r.value for k, r in memory.said.items() if r.certainty == "stated"}
    for key, value in {**said, **conversational}.items():
        if key in seen or key in engine or value in (NOT_SURE, "not sure") or not label(key):
            continue
        shown = "see the conversation" if value == STATED else display(schemas.get(key), value)
        known.append({"about": label(key), "value": shown, "status": "said by the founder"})
        seen.add(key)
    for key, reading in memory.said.items():
        if key in seen or key in engine or reading.certainty != "implied" or not label(key):
            continue
        shown = (
            "see the conversation"
            if reading.value == STATED
            else display(schemas.get(key), reading.value)
        )
        known.append({"about": label(key), "value": shown,
                      "status": "clear from what the founder said"})  # fmt: skip
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
        "answered_without_certainty": _labels(
            label, memory, seen, asked="hedged", certainty="uncertain"
        ),
        "answered_only_roughly": _labels(
            label, memory, seen, asked="approximate", certainty="rough"
        ),
    }
    last = [q for q in previous if q.kind != "insistence"]
    if last:
        question = last[0]
        key = JURISDICTION if question.kind == "jurisdiction" else question.key
        outcome = memory.asked.get(key, AskRecord(1, "unanswered")).last
        if label(key) and outcome in REPLIES:
            view["last_question"] = {"about": label(key), "founder_reply": REPLIES[outcome]}
    return view
