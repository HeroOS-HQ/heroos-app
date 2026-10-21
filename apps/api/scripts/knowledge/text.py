"""Scoping source text by jurisdiction, without changing a word of it.

Source text arrives as paragraphs. Each becomes one or more **segments**,
each tagged with the jurisdiction scope it may be shown in. In order of
precedence:

1. a ``region`` of the mapping (from one paragraph up to, not including,
   another) gives every paragraph in it a scope;
2. a paragraph or sentence that starts with the source's own label
   ("UAE Federal:", "DIFC:", with or without the scales emoji) takes that
   scope, and so do the sentences after it in the same paragraph until the
   next label;
3. a mapping ``scope_rule`` whose prefix starts a paragraph or a sentence
   gives it a scope (``level``: "paragraph" or "sentence");
4. otherwise the item's default scope.

Consecutive sentences of the same paragraph and scope are joined again with
a single space, so the stored text is the source text, split only where a
jurisdiction changes.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Final

from app.knowledge.bundle import sentences
from scripts.knowledge.sources import normalize

# A template's instructions may start "User Instructions: UAE Federal: ...".
_LEAD: Final = r"^(?:(?:User\s+)?Instructions?\s*:\s*)?(?:⚖️?\s*)?"
_LABELS: Final = (
    (re.compile(_LEAD + r"UAE\s+Federal(?:\s*/\s*MOHRE)?\s*:"), "uae_federal"),
    (re.compile(_LEAD + r"DIFC\s*:"), "difc"),
)


def label_scope(text: str) -> str | None:
    stripped = text.strip()
    for pattern, scope in _LABELS:
        if pattern.match(stripped):
            return scope
    return None


def starts(text: str, prefix: str) -> bool:
    return normalize(text).startswith(normalize(prefix))


def segment(
    paragraphs: Sequence[str],
    default: str,
    rules: Sequence[Mapping[str, str]] = (),
    regions: Sequence[Mapping[str, str]] = (),
) -> list[dict[str, str]]:
    """Scoped segments for ``paragraphs`` (see the module docstring)."""
    region_scope: list[str | None] = [None] * len(paragraphs)
    for region in regions:
        active = False
        for index, paragraph in enumerate(paragraphs):
            if starts(paragraph, region["from"]):
                active = True
            elif region.get("to") and starts(paragraph, region["to"]):
                active = False
            if active:
                region_scope[index] = region["scope"]
    out: list[dict[str, str]] = []
    for index, paragraph in enumerate(paragraphs):
        text = paragraph.strip()
        if not text:
            continue
        base = region_scope[index]
        if base is None:
            base = label_scope(text)
        if base is None:
            base = next(
                (
                    r["scope"]
                    for r in rules
                    if r.get("level", "paragraph") == "paragraph" and starts(text, r["match"])
                ),
                default,
            )
        pieces: list[tuple[str, str]] = []
        current = base
        for sentence in sentences(text):
            labelled = label_scope(sentence)
            if labelled is not None:
                current = labelled
            scope = next(
                (
                    r["scope"]
                    for r in rules
                    if r.get("level") == "sentence" and starts(sentence, r["match"])
                ),
                current,
            )
            if pieces and pieces[-1][0] == scope:
                pieces[-1] = (scope, f"{pieces[-1][1]} {sentence}")
            else:
                pieces.append((scope, sentence))
        if len(pieces) == 1:
            # One scope for the whole paragraph: keep it exactly as written.
            out.append({"scope": pieces[0][0], "text": text})
        else:
            out.extend({"scope": scope, "text": piece} for scope, piece in pieces)
    return out
