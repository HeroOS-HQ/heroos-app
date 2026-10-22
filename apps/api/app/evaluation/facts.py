"""The fact trust pipeline: PROPOSED -> ESTABLISHED_CONVERSATIONAL -> ENGINE_TRUSTED.

- **PROPOSED**: the AI's reading only (inferred, approximate, low confidence,
  hedged, or contradicted by the founder's own words). Never executable.
- **ESTABLISHED_CONVERSATIONAL**: the founder clearly said it (M2-NEW-05's
  evidence check found their words) or the Blueprint holds it. The
  conversation uses it (it is never asked again); a rule never reads it. The
  quoted words are real; the AI's interpretation of them may not be: "I did
  NOT speak to the employee" cited for "discussed: yes" stays PROPOSED here.
- **ENGINE_TRUSTED**: a canonical, server-typed value (an option of the
  workflow definition or the rule bundle, a whole number, a date) that the
  server itself derived, never the AI. Three ways only:

  1. a **direct answer** to the one question HeroOS asked last turn, parsed
     deterministically against that fact's schema ("Yes." -> ``yes``,
     "Eight." -> ``8``; "I sort of spoke to him" and "basically all week"
     parse to nothing);
  2. a **confirmation** of what the founder said in passing, when a decision
     needs it: HeroOS asks that fact's own question again ("So I can rely on it
     for this step: has a disciplinary sanction already been issued for this same
     incident?") and the answer is parsed as in (1), so it means what it says
     about the question, never "yes, that's right"; or, for a fact with no
     question of its own, HeroOS asks "is it <canonical value>?" (the server
     canonicalized what the founder said) and the founder answers yes;
  3. the **Company Blueprint** (e.g. the number of employees).

  Earlier engine-trusted values come back through the encrypted continuation
  (``app.evaluation.continuation``). HeroOS's own words are never a source.
  The newest explicit founder statement controls: a different value stated
  now voids the trusted one until it is confirmed again (stricter, never
  looser).
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from app.evaluation.model import FactSource, TrustedFactState, TwoState, Value
from app.evaluation.snapshot import FactSchema, WorkflowExecution
from app.workflows.conditions import Tri

# NOT_SURE is re-exported: the canonical "Not sure" answer, for the gateway (no workflow import).
from app.workflows.definition import NOT_SURE as NOT_SURE
from app.workflows.definition import Option

MAX_ANSWER_CHARS: Final = 160

_QUOTES: Final = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
_WORD: Final = re.compile(r"[a-z0-9']+")
_YES: Final = frozenset({"yes", "yeah", "yep", "yup", "correct", "affirmative"})
_NO: Final = frozenset({"no", "nope", "nah"})
_NOT_SURE: Final = (
    "not sure", "unsure", "don't know", "dont know", "do not know", "no idea", "not certain",
    "i'm not sure", "im not sure",
    # The canonical value itself (a reading of "I don't know", noted for the Case record).
    NOT_SURE,
)  # fmt: skip
# Words that make a short answer more than a plain yes or no.
_QUALIFIERS: Final = re.compile(
    r"\b(?:but|although|though|except|unless|partly|partially|sort\s+of|kind\s+of|kinda|maybe"
    r"|perhaps|probably|possibly|sometimes|not\s+really|not\s+exactly|i\s+think|i\s+guess"
    r"|i\s+believe|i\s+suppose|more\s+or\s+less|in\s+a\s+way|not\s+sure|unsure)\b"
)
_NEGATION: Final = re.compile(r"\b(?:not|never|no|nobody|nothing|didn't|hasn't|haven't|wasn't"
                              r"|weren't|isn't|aren't|doesn't|don't|won't|can't|couldn't)\b"
                              r"|n't\b")  # fmt: skip
_APPROXIMATE: Final = re.compile(
    r"\b(?:about|around|roughly|approximately|approx|almost|nearly|some|few|couple|several"
    r"|over|under|more\s+than|less\s+than|at\s+least|at\s+most|or\s+so|ish|basically|maybe"
    r"|probably|perhaps|i\s+think|or|to|between|week|weeks|month|months|all)\b|~|-\s*\d|\+"
)
_NUMBER_WORDS: Final = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "ninety": 90, "once": 1, "twice": 2,
}  # fmt: skip
_UNITS: Final = frozenset({
    "day", "days", "working", "calendar", "time", "times", "warning", "warnings", "week", "weeks",
    "month", "months", "occasion", "occasions", "incident", "incidents", "people", "employees",
    "staff",
})  # fmt: skip
_ACKNOWLEDGED: Final = frozenset({
    "ok", "okay", "understood", "noted", "got it", "i understand", "i see", "fair enough",
    "thanks", "thank you", "makes sense", "that makes sense", "right",
})  # fmt: skip
_INSISTS: Final = re.compile(
    r"\b(?:still\s+want|want\s+to\s+(?:go\s+ahead|proceed)|go\s+ahead|proceed\s+anyway"
    r"|proceed\s+regardless|do\s+it\s+anyway|regardless|anyway|insist)\b"
)


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES).casefold()
    return " ".join(text.split())


def _bare(text: str) -> str:
    """The answer without surrounding punctuation."""
    return normalized(text).strip(" .!?,;:\"'()")


def parse_yes_no(text: str) -> str | None:
    """``yes``, ``no`` or ``not_sure`` for a bare answer; None for anything else.

    Only the answer on its own counts ("Yes", "No.", "Nope", "Not sure"). A yes
    or no followed by more words ("No, they haven't contacted anyone", "Yes, he
    has") is never read as the answer: the rest may be about something else.
    It is not trusted here; HeroOS confirms it, or notes it for the Case record.
    """
    if len(text) > MAX_ANSWER_CHARS:
        return None
    answer = _bare(text)
    if answer in _NOT_SURE or answer.removeprefix("i ") in _NOT_SURE:
        return NOT_SURE
    words = _WORD.findall(answer)
    if len(words) != 1:
        return None
    if words[0] in _YES:
        return "yes"
    if words[0] in _NO:
        return "no"
    return None


def parse_count(text: str, maximum: int | None = None) -> int | None:
    """A whole number stated exactly ("8", "eight", "8 days", "twice"); None for anything else."""
    if len(text) > MAX_ANSWER_CHARS:
        return None
    answer = _bare(text)
    if _APPROXIMATE.search(answer):
        return None
    words = _WORD.findall(answer)
    numbers = [w for w in words if w.isdigit() or w in _NUMBER_WORDS]
    if len(numbers) != 1 or any(w not in _UNITS and w != numbers[0] for w in words):
        return None
    word = numbers[0]
    value = int(word) if word.isdigit() else _NUMBER_WORDS[word]
    if maximum is not None and value > maximum:
        return None
    return value


def parse_choice(text: str, options: Sequence[Option]) -> str | None:
    """An option of the question: its value or label as written, a bare Yes / No, or Not sure."""
    if len(text) > MAX_ANSWER_CHARS:
        return None
    answer = _bare(text)
    values = {o.value: normalized(o.label) for o in options}
    for value, label in values.items():
        if answer in (normalized(value), label.strip(" .")):
            return value
    plain = parse_yes_no(text)
    if plain == NOT_SURE and NOT_SURE in values:
        return NOT_SURE
    if plain in ("yes", "no"):
        # A bare "Yes" / "No" picks the one option whose label starts with it (e.g.
        # "No, outside work"); "No, <anything else>" is not this option's label.
        lead = "yes" if plain == "yes" else "no"
        matches = [v for v, label in values.items() if _WORD.findall(label)[:1] == [lead]]
        if len(matches) == 1:
            return matches[0]
    return None


def parse_date(text: str) -> str | None:
    answer = _bare(text)
    if answer in _NOT_SURE:
        return NOT_SURE
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", answer)
    if match is None:
        return None
    return answer if FactSchema("date", "date", "date").valid(answer) else None


def canonical(schema: FactSchema, text: str) -> Value | None:
    """The canonical value of ``text`` under ``schema``, or None (never a guess)."""
    if schema.kind == "yes_no":
        value = parse_yes_no(text)
        return value if value is not None and schema.valid(value) else None
    if schema.kind == "choice":
        return parse_choice(text, schema.options)
    if schema.kind == "count":
        return parse_count(text, schema.maximum)
    if schema.kind == "date":
        return parse_date(text)
    return None


InsistenceAnswer = Literal["insists", "declines", "acknowledged"]


def parse_insistence(text: str) -> InsistenceAnswer | None:
    """The answer to "do you still intend to proceed despite this caution?".

    Only a plain yes (or an explicit "I still want to go ahead") is insistence;
    tone, repetition and emphasis never are. "OK" or "understood" only
    acknowledges the caution.
    """
    if len(text) > MAX_ANSWER_CHARS:
        return None
    answer = _bare(text)
    plain = parse_yes_no(text)
    if plain == "yes":
        return "insists"
    if plain == "no":
        return "declines"
    parts = [part.strip() for part in re.split(r"[,.!;]+", answer) if part.strip()]
    if parts and all(part in _ACKNOWLEDGED for part in parts):
        return "acknowledged"
    if _INSISTS.search(answer) and not _NEGATION.search(answer) and not _QUALIFIERS.search(answer):
        return "insists"
    return None


_ROUGHLY: Final = re.compile(
    r"\b(?:about|around|roughly|approximately|almost|nearly|some|few|couple|several|more\s+than"
    r"|less\s+than|at\s+least|at\s+most|or\s+so|basically|all\s+(?:week|month)|a\s+(?:week|month))\b"
)


def contradicted(value: str, excerpt: str, schema: FactSchema | None = None) -> bool:
    """A reading the founder's own words don't support exactly.

    An affirmative reading of negative or hedged words ("I did NOT speak to
    him", "I sort of spoke to him"), any reading of hedged words, and an exact
    number read from approximate words ("basically all week").
    """
    reading = _bare(value)
    words = normalized(excerpt)
    if schema is not None and schema.kind == "count" and _ROUGHLY.search(words):
        return True
    if reading in ("yes", "true", "y") or reading.startswith("yes"):
        return _NEGATION.search(words) is not None or _QUALIFIERS.search(words) is not None
    return _QUALIFIERS.search(words) is not None and reading not in ("no", "false", NOT_SURE)


# --- the pipeline ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatedFact:
    """A fact proposal that passed M2-NEW-05's evidence check (the founder's words exist)."""

    key: str
    value: str
    excerpt: str
    # Explicit and confident (``FactProposal.establishes``).
    explicit: bool
    # From the current founder message.
    current: bool


AskedKind = Literal["fact", "confirm", "insistence", "jurisdiction"]


@dataclass(frozen=True, slots=True)
class Asked:
    """What HeroOS asked last turn (from the continuation; never from a browser's text)."""

    kind: AskedKind
    # A fact key, a two-state rule key, or "jurisdiction".
    key: str
    candidate: Value | None = None


@dataclass(frozen=True, slots=True)
class PriorState:
    """The trusted state the previous turn left (an empty one when there is none)."""

    engine: Mapping[str, Value] = field(default_factory=dict)
    # The matter (workflow) the state belongs to.
    workflow: str | None = None
    # The founder's trusted answer about this employee's jurisdiction:
    # "confirmed", "different" or "not_sure".
    jurisdiction: str | None = None
    two_state: Mapping[str, TwoState] = field(default_factory=dict)
    asked: tuple[Asked, ...] = ()
    # Trusted state was lost mid-conversation: what must be confirmed again is.
    reconfirm: bool = False


@dataclass(frozen=True, slots=True)
class TrustOutcome:
    facts: TrustedFactState
    jurisdiction: str | None
    two_state: Mapping[str, TwoState]
    # Candidates the founder declined this turn (never offered again as the value).
    declined: frozenset[str]
    # This message answered the question HeroOS asked (so the steps it concerned stay evaluated).
    answered: bool = False


JURISDICTION_ANSWERS: Final = {"yes": "confirmed", "no": "different", NOT_SURE: "not_sure"}


def trust_facts(
    execution: WorkflowExecution,
    *,
    stated: Sequence[StatedFact],
    message: str,
    prior: PriorState,
    blueprint: Mapping[str, object],
) -> TrustOutcome:
    """This turn's facts by trust level, from what the founder said and the trusted prior state."""
    schemas = execution.schemas
    engine: dict[str, Value] = {}
    sources: dict[str, FactSource] = {}
    for key, value in prior.engine.items():
        schema = schemas.get(key)
        if schema is not None and schema.kind != "blueprint" and schema.valid(value):
            engine[key], sources[key] = value, "continuation"
    jurisdiction = prior.jurisdiction
    two_state = dict(prior.two_state)
    declined: set[str] = set()
    answered: str | None = None
    replied = False

    if len(prior.asked) == 1:
        asked = prior.asked[0]
        schema = schemas.get(asked.key)
        if asked.kind == "fact" and schema is not None:
            answer = canonical(schema, message)
            if answer is not None:
                engine[asked.key], sources[asked.key] = answer, "direct_answer"
                answered = asked.key
        elif asked.kind == "confirm" and schema is not None and asked.candidate is None:
            # The fact's own question asked again (HeroOS had a reading of what the founder
            # said): a direct answer to that question, never "yes, that's right".
            answer = canonical(schema, message)
            if answer is not None:
                engine[asked.key], sources[asked.key] = answer, "confirmation"
                answered = asked.key
        elif asked.kind == "confirm" and schema is not None:
            reply = parse_yes_no(message)
            if reply == "yes" and asked.candidate is not None and schema.valid(asked.candidate):
                engine[asked.key], sources[asked.key] = asked.candidate, "confirmation"
                answered = asked.key
            elif reply == "no":
                engine.pop(asked.key, None)
                declined.add(asked.key)
                replied = True
        elif asked.kind == "jurisdiction":
            reply = parse_yes_no(message)
            if reply is not None:
                jurisdiction = JURISDICTION_ANSWERS[reply]
                replied = True
        elif asked.kind == "insistence":
            answer = parse_insistence(message)
            current = two_state.get(asked.key)
            if answer is not None and current is not None:
                insists = {"insists": Tri.TRUE, "declines": Tri.FALSE}.get(answer, current.insists)
                two_state[asked.key] = TwoState(current.rule, current.shown, True, insists)
                replied = True

    newest: dict[str, StatedFact] = {}
    for fact in stated:
        if fact.current or fact.key not in newest:
            newest[fact.key] = fact
    conversational: dict[str, str] = {}
    proposed: list[str] = []
    for key, fact in newest.items():
        schema = schemas.get(key)
        if not fact.explicit or contradicted(fact.value, fact.excerpt, schema):
            proposed.append(key)
            continue
        conversational[key] = fact.value
        # The founder's newest explicit statement controls: a different value voids the
        # trusted one until it is confirmed again.
        if (
            fact.current
            and key in engine
            and key != answered
            and schema is not None
            and canonical(schema, fact.value) != engine[key]
        ):
            engine.pop(key)
            sources.pop(key, None)

    for key, schema in schemas.items():
        if schema.kind == "blueprint" and schema.blueprint is not None:
            held = blueprint.get(schema.blueprint)
            if isinstance(held, (int, str)) and not isinstance(held, bool):
                engine[key], sources[key] = held, "blueprint"

    return TrustOutcome(
        facts=TrustedFactState(
            engine=dict(sorted(engine.items())),
            sources=dict(sorted(sources.items())),
            conversational=dict(sorted(conversational.items())),
            proposed=tuple(sorted(set(proposed))),
        ),
        jurisdiction=jurisdiction,
        two_state=two_state,
        declined=frozenset(declined),
        answered=replied or answered is not None,
    )


def candidate(schema: FactSchema, state: TrustedFactState) -> Value | None:
    """What to ask the founder to confirm: the server's canonical reading of what they said."""
    said = state.conversational.get(schema.key)
    return None if said is None else canonical(schema, said)
