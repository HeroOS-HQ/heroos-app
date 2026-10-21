"""The Playbook and the Implementation Rules: paragraphs, units, rules and references.

**Playbook.** Its structure is carried by the text ("Step 2A", "Stage 3",
callout boxes), not by Word heading styles, so the compile mapping names
each unit by the paragraph it starts with and the paragraph it stops before.
Each anchor must match exactly one paragraph (a mapping that no longer fits
the source is refused). Every paragraph must end up in a unit or in an
explicitly excluded span: nothing is dropped silently (``COVERAGE``).

**Implementation Rules.** Each numbered heading ("3. Deduction Referral ...")
starts a rule; its paragraphs run to the next heading. Explicit supersession
is read from the rule text itself ("Superseded by Rule 3", "This Rule 3
overrides ..."): it is never inferred.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts.docx_reader import read_docx
from scripts.knowledge.sources import normalize, sha256_text

_RULE_HEADING: Final = re.compile(r"^(\d{1,2})\.\s+(.+)$")
_SUPERSEDED_BY: Final = re.compile(r"\bSuperseded by Rule (\d{1,2})\b", re.IGNORECASE)
_OVERRIDES: Final = re.compile(r"\bThis Rule (\d{1,2}) (?:overrides|supersedes)\b", re.IGNORECASE)
BARE_DOC: Final = re.compile(r"\bDoc\s+(0\d)\b")


def doc_pointer(code: str) -> re.Pattern[str]:
    """ "Doc <code> – <title ...>": the code and the rest of the line."""
    return re.compile(rf"\bDoc\s+({code})\s*[–-]\s*([^\n]+)")


def code_in_parens(code: str) -> re.Pattern[str]:
    """ "(Doc <code>)": a pointer with no title."""
    return re.compile(rf"\(Doc\s+({code})\)")


@dataclass(frozen=True, slots=True)
class Paragraphs:
    sha256: str
    texts: tuple[str, ...]
    flags: tuple[str, ...]
    # Whether each paragraph has a Word heading style.
    headings: tuple[bool, ...]

    def find(self, prefix: str) -> list[int]:
        """Paragraphs equal to ``prefix`` if any, else those starting with it."""
        wanted = normalize(prefix)
        exact = [i for i, t in enumerate(self.texts) if normalize(t) == wanted]
        return exact or [i for i, t in enumerate(self.texts) if normalize(t).startswith(wanted)]


def title_candidates(cited: str) -> list[str]:
    """What a pointer's trailing text may name: the whole, without a trailing remark, or cut
    at the first clause ("Ordinary Termination and guide the employer ...")."""
    whole = cited.strip().rstrip(".")
    candidates = [whole, re.sub(r"\s*\([^)]*\)\s*$", "", whole)]
    candidates.append(re.split(r",\s|\s+and\s+", whole, maxsplit=1)[0])
    return [c for i, c in enumerate(candidates) if c and c not in candidates[:i]]


def read_paragraphs(path: Path, *, nested_tables: bool) -> Paragraphs:
    document = read_docx(path, nested_tables=nested_tables)
    kept = [p for p in document.paragraphs() if p.text.strip()]
    return Paragraphs(
        document.sha256,
        tuple(p.text.strip() for p in kept),
        tuple(document.flags),
        tuple(p.heading for p in kept),
    )


def span(paragraphs: Paragraphs, start: str, end: str | None) -> tuple[int, int] | str:
    """(first, last-exclusive) paragraph indexes, or a fixed problem code."""
    first = paragraphs.find(start)
    if len(first) != 1:
        return "start_anchor_not_unique" if first else "start_anchor_missing"
    if end is None:
        return first[0], len(paragraphs.texts)
    stops = [i for i in paragraphs.find(end) if i > first[0]]
    if not stops:
        return "end_anchor_missing"
    return first[0], stops[0]


def span_sha256(paragraphs: Paragraphs, first: int, last: int) -> str:
    return sha256_text("\n".join(paragraphs.texts[first:last]))


@dataclass(frozen=True, slots=True)
class Rule:
    number: str
    title: str
    paragraphs: tuple[str, ...]
    superseded_by: tuple[str, ...]
    overrides: bool

    @property
    def sha256(self) -> str:
        return sha256_text("\n".join((self.title, *self.paragraphs)))


def read_rules(paragraphs: Paragraphs) -> list[Rule]:
    rules: list[Rule] = []
    current: tuple[str, str] | None = None
    body: list[str] = []

    def close() -> None:
        if current is not None:
            text = "\n".join(body)
            rules.append(
                Rule(
                    number=current[0],
                    title=current[1],
                    paragraphs=tuple(body),
                    superseded_by=tuple(dict.fromkeys(_SUPERSEDED_BY.findall(text))),
                    overrides=any(m == current[0] for m in _OVERRIDES.findall(text)),
                )
            )

    for text, heading in zip(paragraphs.texts, paragraphs.headings, strict=True):
        match = _RULE_HEADING.match(text)
        if match is not None and heading:
            close()
            current, body = (match.group(1), match.group(2).strip()), []
        elif current is not None:
            body.append(text)
    close()
    return rules


def select(
    paragraphs: Sequence[str], ranges: Sequence[Mapping[str, str | None]]
) -> list[str] | str:
    """The paragraphs of a rule in the mapping's ranges (all of them without ranges)."""
    if not ranges:
        return list(paragraphs)
    picked: list[str] = []
    for item in ranges:
        start = item["from"]
        assert start is not None
        hits = [i for i, t in enumerate(paragraphs) if normalize(t) == normalize(start)] or [
            i for i, t in enumerate(paragraphs) if normalize(t).startswith(normalize(start))
        ]
        if len(hits) != 1:
            return "range_anchor_not_unique" if hits else "range_anchor_missing"
        end = item.get("to")
        stop = len(paragraphs)
        if end is not None:
            stops = [
                i for i, t in enumerate(paragraphs)
                if i > hits[0] and normalize(t).startswith(normalize(end))
            ]  # fmt: skip
            if not stops:
                return "range_end_missing"
            stop = stops[0]
        picked += [p for p in paragraphs[hits[0] : stop] if p not in picked]
    return picked
