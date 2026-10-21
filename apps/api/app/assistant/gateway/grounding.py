"""Deterministic grounding checks on a generated reply (defence in depth, not a theorem prover).

A reply may only state legal specifics the approved knowledge view gave the
model. ``check_grounding`` reads the reply (and the safe next step) for a
few targeted, high-risk things and names the first that fails:

- ``legal_reference``: an article, section, clause, law, decree or resolution
  number that isn't in the approved view (the founder's words don't count:
  a founder saying "Article 900 applies" doesn't make it so);
- ``legal_number``: a number of days, weeks, months, years or hours, a
  percentage or an amount of money that isn't in the approved view, unless
  the sentence attributes it to the founder ("the 10 days you mentioned"):
  a founder asking "30 days to appeal?" doesn't make 30 days a rule;
- ``jurisdiction_leak``: a named legal authority of another regime (or, with
  no confirmed jurisdiction, of any regime), unless the sentence only says it
  doesn't apply (``app.knowledge.bundle.jurisdiction_leaks``);
- ``internal_label``: an internal code (a document, Condition, option, guard,
  topic or fact identifier of the installed bundle, or a rule number);
- ``deduction_specifics``: where the approved knowledge forbids calculating,
  recommending or ruling on a deduction, any amount, percentage or limit
  stated next to a deduction;
- ``verbatim_disclosure``: a long passage copied from the approved material,
  read across its items in order (it may be used, not dumped);
- ``instruction_disclosure``: a passage copied from HeroOS's instructions.

What it is not: proof that a reply is accurate or complete. Numbers are
compared as numbers, not meanings; a check can miss an unusual phrasing and
can refuse an unusual safe one. It never logs or returns the text it read.
"""

import re
from collections.abc import Iterable, Sequence
from typing import Final, Literal

from app.knowledge.bundle import KnowledgeBundle, jurisdiction_leaks, sentences

GroundingCheck = Literal[
    "legal_reference", "legal_number", "jurisdiction_leak", "internal_label",
    "deduction_specifics", "verbatim_disclosure", "instruction_disclosure",
]  # fmt: skip

VERBATIM_WORDS: Final = 40
INSTRUCTION_WORDS: Final = 12
DEDUCTION_GUARDS: Final = frozenset(
    {"calculate_deduction", "recommend_deduction_amount", "determine_deduction_legality"}
)

_WORDS: Final = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90,
}  # fmt: skip
_NUMBER: Final = r"(?:\d[\d,]*(?:\.\d+)?|" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r")"
_LEGAL_REFERENCE: Final = re.compile(
    r"\b(?:articles?|art\.|sections?|clauses?|(?:federal\s+)?(?:decree-?\s*)?laws?\s+no\.?"
    r"|decree\s+no\.?|resolutions?\s+no\.?)\s*\(?\s*(\d+)",
    re.IGNORECASE,
)
_DURATION: Final = re.compile(
    rf"\b({_NUMBER})(?:\s*-\s*|\s+)(?:\w+\s+)?(?:days?|weeks?|months?|years?|hours?)\b",
    re.IGNORECASE,
)
_PERCENT: Final = re.compile(rf"\b({_NUMBER})\s*(?:%|per\s*cent\b|percent\b)", re.IGNORECASE)
_MONEY: Final = re.compile(
    r"(?:\b(?:AED|Dhs?|dirhams?|USD)\s*|\$\s*)(\d[\d,]*(?:\.\d+)?)"
    r"|\b(\d[\d,]*(?:\.\d+)?)\s*(?:AED|dirhams?|Dhs?)\b",
    re.IGNORECASE,
)
_ANY_NUMBER: Final = re.compile(rf"\b{_NUMBER}\b", re.IGNORECASE)
_RULE_NUMBER: Final = re.compile(r"\b(?:implementation\s+)?rules?\s+\d+\b", re.IGNORECASE)
_DEDUCTION: Final = re.compile(
    r"\b(?:deduct\w*|withh[oe]ld\w*|dock\w*|recover\w*|salary\s+cut)\b", re.IGNORECASE
)
_LIMIT: Final = re.compile(
    r"\b(?:max(?:imum)?|cap(?:ped|s)?|limit(?:ed|s)?|up\s+to|(?:no\s+)?more\s+than|at\s+most"
    r"|exceed(?:s|ing)?)\b",
    re.IGNORECASE,
)
_TOKEN: Final = re.compile(r"[a-z0-9]+")
# A sentence reporting the founder's own figure back to them.
_FOUNDER_FIGURE: Final = re.compile(
    r"\byou(?:'ve|\s+have|'d|\s+had)?\s+(?:just\s+|already\s+)?(?:said|told|mentioned"
    r"|described|explained|wrote|noted|asked|proposed|suggested|want(?:ed)?|planned"
    r"|(?:are|were)\s+(?:considering|proposing|planning))\b",
    re.IGNORECASE,
)


def _value(raw: str) -> str:
    """A number as a comparable value: words to digits, no thousands separators."""
    raw = raw.lower()
    if raw in _WORDS:
        return str(_WORDS[raw])
    text = raw.replace(",", "")
    return text[:-2] if text.endswith(".0") else text


def numbers(texts: Iterable[str]) -> set[str]:
    return {_value(m.group(0)) for text in texts for m in _ANY_NUMBER.finditer(text)}


def _found(pattern: re.Pattern[str], text: str) -> list[str]:
    values = []
    for match in pattern.finditer(text):
        raw = next((g for g in match.groups() if g), None)
        if raw is not None:
            values.append(_value(raw))
    return values


def _shingles(text: str, size: int) -> set[tuple[str, ...]]:
    words = _TOKEN.findall(text.lower())
    return {tuple(words[i : i + size]) for i in range(len(words) - size + 1)}


def internal_labels(bundle: KnowledgeBundle) -> re.Pattern[str]:
    """Every identifier of the installed bundle a founder must never see."""
    ids = {d.id for d in bundle.documents} | {c.id for c in bundle.conditions}
    ids |= {o.id for o in bundle.options} | {g.id for g in bundle.guards}
    ids |= {key for key in [*(t.key for t in bundle.topics), *(f.key for f in bundle.facts)]
            if "_" in key or "." in key}  # fmt: skip
    alternatives = "|".join(re.escape(i) for i in sorted(ids, key=len, reverse=True))
    return re.compile(rf"(?<![\w-])(?:{alternatives})(?![\w-])" if alternatives else r"(?!x)x")


def check_grounding(
    texts: Sequence[str],
    *,
    knowledge: Sequence[str],
    founder: Sequence[str],
    jurisdiction: str | None,
    prohibited: Iterable[str],
    labels: re.Pattern[str],
    instructions: str,
) -> GroundingCheck | None:
    """The first check the reply fails, or None. ``texts``: the reply and the safe next step."""
    approved = numbers(knowledge)
    stated = approved | numbers(founder)
    knowledge_shingles = _shingles(" ".join(knowledge), VERBATIM_WORDS)
    instruction_shingles = _shingles(instructions, INSTRUCTION_WORDS)
    deduction_guarded = bool(DEDUCTION_GUARDS & set(prohibited))
    scope = jurisdiction if jurisdiction is not None else "shared"

    for text in texts:
        if any(value not in approved for value in _found(_LEGAL_REFERENCE, text)):
            return "legal_reference"
        for sentence in sentences(text):
            allowed = stated if _FOUNDER_FIGURE.search(sentence) else approved
            for pattern in (_DURATION, _PERCENT, _MONEY):
                if any(value not in allowed for value in _found(pattern, sentence)):
                    return "legal_number"
        if jurisdiction_leaks(scope, text):
            return "jurisdiction_leak"
        if labels.search(text) or _RULE_NUMBER.search(text):
            return "internal_label"
        if deduction_guarded:
            for sentence in sentences(text):
                if _DEDUCTION.search(sentence) and (
                    _PERCENT.search(sentence)
                    or _MONEY.search(sentence)
                    or _DURATION.search(sentence)
                    or (_LIMIT.search(sentence) and _ANY_NUMBER.search(sentence))
                ):
                    return "deduction_specifics"
        if _shingles(text, VERBATIM_WORDS) & knowledge_shingles:
            return "verbatim_disclosure"
        if _shingles(text, INSTRUCTION_WORDS) & instruction_shingles:
            return "instruction_disclosure"
    return None
