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
  The newest founder statement controls: a different value stated now, even
  hedged, voids the trusted one until it is confirmed again (stricter, never
  looser).
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
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
# The hedges among them, which count anywhere in the founder's sentence (a contrast word such as
# "but" only qualifies the words it is part of).
_HEDGES: Final = re.compile(
    r"\b(?:partly|partially|sort\s+of|kind\s+of|kinda|maybe|perhaps|probably|possibly|not\s+really"
    r"|not\s+exactly|i\s+think|i\s+guess|i\s+believe|i\s+suppose|more\s+or\s+less|in\s+a\s+way"
    r"|not\s+sure|unsure)\b"
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


# A weekday the founder names, in full or in its usual short forms ("sat night", "Thurs"): Monday
# is 0.
_WEEKDAY: Final = re.compile(
    r"\b(mon|tue|wed|thu|fri|sat|sun)(?:day|s|sday|nesday|r|rs|rsday|urday)?\b"
)
_WEEKDAYS: Final = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _another_weekday(value: str, words: str) -> bool:
    """A date reading whose own words name only other weekdays ("Saturday night" read as a
    Sunday): the model's arithmetic, never the founder's day (found in the acceptance run)."""
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return False
    named = {_WEEKDAYS.index(m) for m in _WEEKDAY.findall(words)}
    return bool(named) and day.weekday() not in named


# A day the founder names with its month ("Tuesday 20 October", "the 18th of October", "Oct 5",
# "14 to 16 October"), with a year only when they give one.
_MONTH_NAMES: Final = (
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
    ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
    ("oct", "october"), ("nov", "november"), ("dec", "december"),
)  # fmt: skip
_MONTH: Final = "(" + "|".join(n for names in _MONTH_NAMES for n in names) + r")\.?"
_DAY: Final = r"(\d{1,2})(?:st|nd|rd|th)?"
_YEAR: Final = r"(?:,?\s+(\d{4}))?"
_DAY_MONTH: Final = re.compile(
    rf"\b{_DAY}(?:\s*(?:-|to|until|till|and|&)\s*{_DAY})?(?:\s+of)?\s+{_MONTH}(?![\w']){_YEAR}"
)
_MONTH_DAY: Final = re.compile(rf"\b{_MONTH}\s+(?:the\s+)?{_DAY}(?![\w']){_YEAR}")


def _month(name: str) -> int:
    return next(i for i, names in enumerate(_MONTH_NAMES, 1) if name in names)


def named_days(words: str) -> tuple[tuple[int, int, int | None], ...]:
    """(month, day, year or None) for each day the words name with its month."""
    text = normalized(words)
    days: list[tuple[int, int, int | None]] = []
    for m in _DAY_MONTH.finditer(text):
        first, last, month, year = m.groups()
        for day in (first, last):
            if day is not None:
                days.append((_month(month), int(day), None if year is None else int(year)))
    for m in _MONTH_DAY.finditer(text):
        month, day, year = m.groups()
        days.append((_month(month), int(day), None if year is None else int(year)))
    return tuple(days)


def _on(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def dated(value: str, words: str, today: date) -> str | None:
    """A date reading checked against the day and month the founder's own words name.

    The understanding reads the expression; the server puts it on the calendar. When the words
    name the reading's day and month without a year, the year is the one that makes it the most
    recent such day not after ``today`` (an incident date): "Tuesday 20 October", read as
    2020-10-20 because that day was a Tuesday then too, is 2026-10-20 against 22 October 2026
    (found in the hybrid certification). Returns that date (the reading's own when it agrees);
    the reading unchanged when the words name no day with its month; None when they name days
    with their months but not the reading's, or one no year fits (a weekday it isn't on): the
    reading stays non-authoritative, never a guessed year.
    """
    days = named_days(words)
    if not days:
        return value
    try:
        read = date.fromisoformat(value)
    except ValueError:
        return value
    weekdays = {_WEEKDAYS.index(m) for m in _WEEKDAY.findall(normalized(words))}
    for month, day, year in days:
        if (month, day) != (read.month, read.day):
            continue
        if year is not None:
            on = _on(year, month, day)
        else:
            on = _on(today.year, month, day)
            if on is None or on > today:
                on = _on(today.year - 1, month, day)
        if on is None or (weekdays and on.weekday() not in weekdays):
            return None
        return on.isoformat()
    return None


# Doubt about what the founder knows, whatever the reading ("no" included): "not that I know of" is
# not a definite no, and "I'd need to check" is not a fact.
_DOUBT: Final = re.compile(
    r"\b(?:not\s+that\s+i\s+know|as\s+far\s+as\s+i\s+know|i\s+don'?t\s+think|i\s+do\s+not\s+think"
    r"|(?:need|have|got)\s+to\s+check|not\s+(?:100%|a\s+hundred\s+percent|certain))"
)
# Hearsay weakens a claim that something happened ("I was told there were messages"), never a
# "no" ("Nobody saw it. I was told about it afterwards" is a plain no: found in the final run).
_HEARSAY: Final = re.compile(
    r"\b(?:(?:i|we)\s+(?:was|were|have\s+been|'ve\s+been)\s+told|i'?m\s+told|i\s+heard"
    r"|apparently|supposedly|i\s+reckon)\b"
)


# The founder saying, in any words, that they don't know (a "not sure" reading needs such words).
_NOT_KNOWING: Final = re.compile(
    r"\b(?:not\s+sure|unsure|don'?t\s+know|do\s+not\s+know|dunno|idk|no\s+idea|no\s+clue"
    r"|not\s+certain|(?:need|have|got)\s+to\s+(?:check|ask|find\s+out)|check\s+with|find\s+out"
    r"|(?:wasn'?t|weren'?t|was\s+not|were\s+not)\s+there|(?:can'?t|cannot|don'?t)\s+remember"
    r"|(?:might|would|may)\s+know|not\s+aware|can'?t\s+say|(?:can'?t|cannot)\s+confirm|unclear"
    r"|no\s+way\s+to\s+know)"
)


# Words that add nothing to an answer ("to be honest", "tbh", "sorry").
_FILLER: Final = re.compile(
    r"\b(?:to\s+be\s+honest|tbh|honestly|really|sorry|i'?m\s+afraid|mate|lol|haha|right\s+now"
    r"|at\s+the\s+moment|yet|either|i(?:'d|'ll|'ve|'m|m)?|i\s+am|would|will|um+|uh+|hmm+|well|so"
    r"|just|actually|ok|okay)(?![\w'])"
)


def only_not_known(text: str) -> bool:
    """The answer says only that the founder doesn't know ("i don't know to be honest", "no idea
    tbh"): like a bare yes or no, it says nothing about which question it answers."""
    if len(text) > MAX_ANSWER_CHARS or not says_not_known(text):
        return False
    rest = _FILLER.sub(" ", _NOT_KNOWING.sub(" ", normalized(text)))
    return not _WORD.findall(rest)


def says_not_known(text: str) -> bool:
    """The words say the founder doesn't know (found live: "i havent said anything to her yet",
    an answer to another question, was read as not knowing whether it was raised before)."""
    return _NOT_KNOWING.search(normalized(text)) is not None


def doubtful(text: str) -> bool:
    """Words of doubt anywhere in the founder's words: a hedge, doubt about what they know,
    hearsay, or not knowing."""
    words = normalized(text)
    return (
        _HEDGES.search(words) is not None
        or _DOUBT.search(words) is not None
        or _HEARSAY.search(words) is not None
        or says_not_known(text)
    )


# --- hedge scope: a doubt qualifies the proposition it is part of ------------------------------

_SENTENCE_BREAK: Final = re.compile(r"[.!?\n]")
# Where a sentence divides into propositions: punctuation, or a contrast word ("He was late again,
# but I don't think I need his side": the lateness is said plainly, only the opinion is doubtful).
_CLAUSE_BREAK: Final = re.compile(r"[,;:()]|\s-\s|\s(?=(?:but|although|though|whereas|however)\b)")
# Doubt about what was just said, wherever it stands in the sentence ("..., but I'd need to check
# with HR"), unless it names its own subject ("not sure about the date", "I don't know if he was
# told": a proposition of its own).
_VERIFYING: Final = re.compile(
    r"\b(?:(?:need|have|got)\s+to\s+(?:check|ask|find\s+out|verify|confirm)|check\s+with|verify"
    r"|not\s+(?:100%|a\s+hundred\s+percent|certain|sure|aware)|unsure|as\s+far\s+as\s+i\s+know"
    r"|not\s+that\s+i\s+know|(?:can'?t|cannot)\s+(?:confirm|remember|say)|don'?t\s+(?:know|remember)"
    r"|no\s+idea|dunno|idk)(?![\w'])(?!\s+(?:about|if|whether|when|what|who|how|why|where|which)\b)"
)
# A hedge opening a sentence qualifies all of it ("I think he was told, but not in writing").
_OPENING_HEDGE: Final = re.compile(
    r"^\W*(?:(?:honestly|well|so|and|but|ok|okay|tbh|to\s+be\s+honest)\W+)*(?:i\s+think|i\s+believe"
    r"|i\s+guess|i\s+suppose|i\s+reckon|maybe|perhaps|probably|possibly|apparently|supposedly"
    r"|i\s+heard|(?:i|we)\s+(?:was|were)\s+told|i'?m\s+told|not\s+sure|i'?m\s+not\s+sure)\b"
    r"(?!\s+(?:about|if|whether|when|what|who|how|why|where|which)\b)"
)
# What is left of a clause that only doubts ("I think", "or so I was told", "at least I don't
# think so") once its doubt is taken out.
_DOUBT_ONLY_REST: Final = re.compile(
    r"\b(?:and|or|but|though|although|so|at\s+least|that|it|this|too|i\s+mean|anyway|yeah|yes|no"
    r"|not|really|just|we|you)\b"
)


def _doubts_the_sentence(clause: str) -> bool:
    """A clause that doubts what the sentence says rather than saying something of its own."""
    if _VERIFYING.search(clause):
        return True
    if not doubtful(clause):
        return False
    rest = clause
    for words in (_DOUBT, _HEDGES, _HEARSAY, _NOT_KNOWING, _QUALIFIERS):
        rest = words.sub(" ", rest)
    rest = _DOUBT_ONLY_REST.sub(" ", _FILLER.sub(" ", rest))
    return not _WORD.findall(rest)


def proposition(message: str, excerpt: str) -> str:
    """The founder's words a reading of ``excerpt`` rests on, for weighing doubt (normalized; the
    excerpt itself when it isn't found).

    A hedge qualifies the proposition it is part of, never the whole message: the clause of the
    sentence that holds the excerpt counts, with a doubt about the whole sentence (a clause that
    only doubts: "..., but I'd need to check", "I think.") and a hedge opening the sentence.
    "I haven't spoken to her about it, and honestly I don't think I need her side" states plainly
    that it wasn't discussed (found in the hybrid certification: the opinion's "I don't think"
    made the first statement doubtful). Words without such a break keep their doubt together:
    "I think he was late and his manager warned him" stays doubtful throughout.
    """
    text, quoted = normalized(message), normalized(excerpt)
    at = text.find(quoted)
    if not quoted or at < 0:
        return excerpt
    start = max((m.end() for m in _SENTENCE_BREAK.finditer(text, 0, at)), default=0)
    found = _SENTENCE_BREAK.search(text, at + len(quoted))
    sentence = text[start : found.start() if found else len(text)]
    at -= start
    cuts = [0, *(m.start() for m in _CLAUSE_BREAK.finditer(sentence)), len(sentence)]
    clauses = [(a, b) for a, b in zip(cuts, cuts[1:], strict=False) if a < b]
    opening = _OPENING_HEDGE.search(sentence) is not None
    kept = [
        sentence[a:b].strip(" ,;:()-")
        for i, (a, b) in enumerate(clauses)
        if (a < at + len(quoted) and b > at)
        or (i == 0 and opening)
        or _doubts_the_sentence(sentence[a:b])
    ]
    return " ".join(k for k in kept if k)


MAX_LEADING_CHARS: Final = 400
# A plain yes or no opening a longer answer: it ends at punctuation, a dash, or the conjunction
# that goes on ("No. The rule was never explained to her", "Yes, but only once", "No and we
# don't have any evidence either").
_LEADING: Final = re.compile(r"(\w+)\s*(?:[,.;:!?]+|\s-+|\s(?=(?:and|but|so)\b))")


# Where the statement after an opening yes or no ends: a clause or a sentence.
_ANSWER_BREAK: Final = re.compile(
    r"[,;:()]|\s-\s|[.!?\n]|\s(?=(?:but|although|though|whereas|however)\b)"
)


def _answer_span(text: str) -> str:
    """A reply's opening yes or no with the statement after it, which the answer rests on: "No. I
    was told he never got it." is hearsay, "No, I haven't spoken to her, and honestly I don't
    think I need her side" is a plain no ("Yes. Well, ...": a filler is not that statement)."""
    words = normalized(text).lstrip(" \"'(")
    opening = re.match(r"\S+\W*", words)
    if opening is None:
        return words
    for m in _ANSWER_BREAK.finditer(words, opening.end()):
        said = _DOUBT_ONLY_REST.sub(" ", _FILLER.sub(" ", words[opening.end() : m.start()]))
        if _WORD.findall(said):
            return words[: m.start()]
    return words


def leading_answer(text: str) -> str | None:
    """``yes`` or ``no`` when the message opens with a plain yes or no and goes on; None
    otherwise (a bare answer is ``parse_yes_no``'s; "No idea" opens with no plain answer)."""
    if len(text) > MAX_LEADING_CHARS:
        return None
    words = normalized(text).lstrip(" \"'(")
    match = _LEADING.match(words)
    if match is None or not words[match.end() :].strip(" .!?,;:-\"')"):
        return None
    first = match.group(1)
    return "yes" if first in _YES else "no" if first in _NO else None


def answer_in_words(schema: FactSchema, message: str, read: str | None) -> Value | None:
    """The answer a longer reply to this fact's question opens with, when it can be relied on.

    "No. The rule was never explained to her and she was not given the policy" answers "Had
    the employee been told what was expected of them?" with no: the reply opens with a plain
    yes or no, nothing in it is uncertain, and the understanding read the same answer for this
    fact from it (``read``: its reading of the current message for this fact). "No, nobody has
    heard from him" says nothing about where something happened: no such reading comes from
    it, and the "No" alone answers nothing. Found live: a founder who answered "No. The rule
    was never explained to her ..." was asked the same question again, three times.
    """
    lead = leading_answer(message)
    if lead is None or read is None or schema.kind not in ("yes_no", "choice"):
        return None
    if doubtful(proposition(message, _answer_span(message))):
        return None
    answer = canonical(schema, lead)
    if answer is None or answer == NOT_SURE or canonical(schema, read) != answer:
        return None
    return answer


def contradicted(
    value: str, excerpt: str, schema: FactSchema | None = None, context: str | None = None
) -> bool:
    """A reading the founder's own words don't support exactly.

    An affirmative reading of negative or hedged words ("I did NOT speak to
    him", "I sort of spoke to him"), any reading of hedged words, an exact
    number read from approximate words ("basically all week"), and a date on
    another weekday than the one its words name ("Saturday night" as a Sunday). ``context``: the
    founder's words the excerpt's proposition rests on (``proposition``), where a hedge counts
    too (found live: "i think her manager gave her a verbal warning ..., but honestly id need
    to check" cited without its first and last words was noted as a fact).
    """
    reading = _bare(value)
    words = normalized(excerpt)
    around = normalized(context) if context else words
    if schema is not None and schema.kind == "count" and _ROUGHLY.search(words):
        return True
    if schema is not None and schema.kind == "date" and _another_weekday(reading, words):
        return True
    if reading != NOT_SURE and _DOUBT.search(around):
        return True
    if reading not in (NOT_SURE, "no", "false") and _HEARSAY.search(around):
        return True
    qualified = _QUALIFIERS.search(words) is not None or _HEDGES.search(around) is not None
    if reading in ("yes", "true", "y") or reading.startswith("yes"):
        return _NEGATION.search(words) is not None or qualified
    return qualified and reading not in ("no", "false", NOT_SURE)


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
    answered_in_words: bool = False,
    answers: Mapping[str, str] | None = None,
) -> TrustOutcome:
    """This turn's facts by trust level, from what the founder said and the trusted prior state.

    A direct answer to the one question HeroOS asked is trusted: the answer on its own ("No"),
    or a longer reply that opens with it ("No. The rule was never explained to her") when the
    understanding read the message as answering that question (``answered_in_words``) and read
    the same answer for its fact from it (``answers``: its readings of the current message, by
    fact key, before any check; ``answer_in_words``).
    """
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
        read = (answers or {}).get(asked.key) if answered_in_words else None
        if asked.kind == "fact" and schema is not None:
            answer = canonical(schema, message)
            if answer is None:
                answer = answer_in_words(schema, message, read)
            if answer is not None:
                engine[asked.key], sources[asked.key] = answer, "direct_answer"
                answered = asked.key
        elif asked.kind == "confirm" and schema is not None and asked.candidate is None:
            # The fact's own question asked again (HeroOS had a reading of what the founder
            # said): a direct answer to that question, never "yes, that's right".
            answer = canonical(schema, message)
            if answer is None:
                answer = answer_in_words(schema, message, read)
            if answer is not None:
                engine[asked.key], sources[asked.key] = answer, "confirmation"
                answered = asked.key
        elif asked.kind == "confirm" and schema is not None:
            reply = parse_yes_no(message)
            opening = proposition(message, _answer_span(message))
            lead = None if read is None or doubtful(opening) else leading_answer(message)
            if reply is None and lead is not None and read is not None:
                # "Yes, that's right ..." confirms the reading; "No, ..." declines it (the
                # understanding read the reply's own value for the fact: it must agree).
                agrees = canonical(schema, read) == asked.candidate
                reply = lead if (lead == "yes") == agrees else None
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
        # The founder's newest statement controls: a different value voids the trusted one until
        # it is confirmed again, said plainly or not (a correction that reduces certainty reduces
        # it; found in the final run: "Nobody actually saw it", read as hedged, left "witnesses:
        # yes" trusted). Stricter only: nothing becomes trusted here.
        if (
            fact.current
            and key in engine
            and key != answered
            and schema is not None
            and canonical(schema, fact.value) != engine[key]
        ):
            engine.pop(key)
            sources.pop(key, None)
        # Saying they don't know is said plainly, whatever confidence the reading carries (the
        # evidence check only keeps "not sure" from words that say so).
        not_known = schema is not None and canonical(schema, fact.value) == NOT_SURE
        if (not fact.explicit and not not_known) or contradicted(fact.value, fact.excerpt, schema):
            proposed.append(key)
            continue
        conversational[key] = fact.value

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
