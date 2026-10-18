"""Offline converter: a Word template → a template-bundle "working copy" (M2-04C, phase C3).

Usage (from apps/api; every output directory must be outside any git
repository, because outputs hold template wording)::

    uv run python -m scripts.template_import scan DOCX --out DIR
    uv run python -m scripts.template_import convert DOCX MAPPING --out DIR
    uv run python -m scripts.template_import verify DOCX MAPPING ENGINE_COPY SOURCE_MAP
    uv run python -m scripts.template_import assemble META ENGINE_COPY... --out FILE [--rules RULES]

The approved Word document is never modified (it is only read, by
``scripts.docx_reader``). The converter turns it into a **working copy**: the
template as bundle blocks (``app.documents.bundle``), where each
``[bracketed]`` gap is a named field. Wording is never typed in by a person
and never guessed by the tool:

- ``scan`` reports the document's structure and every bracketed gap, with
  what needs a person's decision: gaps that aren't (fully) highlighted,
  conditional or instruction-like gaps, highlighted text outside brackets,
  unbalanced brackets, text in headers or footers, comments, images. Its
  report holds wording, so it is written to a private directory; the console
  shows counts only.
- ``convert`` applies a **mapping** written by engineering and approved by the
  template owner (``heroos.template-mapping/1``): which gaps are which
  fields, which paragraphs are the employer instructions, which paragraph
  depends on which choice, which identical paragraphs repeat per list entry,
  and the explicitly approved wording changes ("patches"). Anything the
  mapping doesn't settle stops the conversion: an un-highlighted or partly
  highlighted gap is never mapped by its text alone, highlighted text outside
  brackets must be confirmed literal, and an unapproved patch is refused.
- Every conversion is **verified**: the working copy is turned back into
  text (each field replaced by the original gap, conditional prefixes and
  repeated paragraphs restored, approved patches reversed) and must equal
  the source document's text exactly, paragraph by paragraph. Only layout
  normalizations are allowed (a tab or non-breaking space becomes a space, a
  soft hyphen is dropped, empty paragraphs are skipped), and they are counted
  in the report. ``verify`` repeats the check later, on the stored files.
- ``assemble`` combines approved working copies into one private template
  bundle and validates it exactly as the API does at startup (optionally
  against the rule bundle). Its file name must end in
  ``.private-templates.json``.

Outputs: ``<key>.engine.json`` (the template, its fields and choices),
``<key>.source-map.json`` (where each block and field came from, for
verification), ``<key>.review.md`` (a side-by-side review pack for the
template owner) and ``<key>.conversion.json`` (counts and the verification
result, no wording). Nothing is sent anywhere.
"""

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from app.documents.bundle import (
    TemplateBundleError,
    check_against_rules,
    parse_template_bundle,
)
from app.workflows.progression.bundle import RuleBundleError, load_bundle
from scripts.docx_reader import Char, Document, DocxRefused, Paragraph, Table, read_docx

MAPPING_SCHEMA: Final = "heroos.template-mapping/1"
PLACEHOLDER: Final = re.compile(r"\[[^\[\]\n]*\]")
# Layout characters that become a plain space, or nothing, in a working copy.
SPACES: Final = frozenset("\t   ")
DROPPED: Final = frozenset("­")
# Brackets that look like placeholder marks but aren't the template convention.
NONSTANDARD_BRACKETS: Final = re.compile(r"[［］【】〔〕〖〗⟦⟧]")
CONDITIONAL_HINT: Final = re.compile(r"^\[\s*(if|where|when)\b", re.IGNORECASE)
INSTRUCTION_HINT: Final = re.compile(r"^\[\s*(select|choose|delete|remove|note)\b", re.IGNORECASE)


class ConversionError(ValueError):
    """The conversion is refused. ``code`` is fixed; ``location`` is structural only."""

    def __init__(self, code: str, location: str = "") -> None:
        self.code = code
        self.location = location
        suffix = f" at {location}" if location else ""
        super().__init__(f"conversion refused: {code}{suffix}")


# --- text helpers --------------------------------------------------------------------------


def normalize(text: str) -> tuple[str, int]:
    """Layout normalization (tabs, special spaces → space; soft hyphens dropped) and its count."""
    out: list[str] = []
    changed = 0
    for char in text:
        if char in SPACES:
            out.append(" ")
            changed += 1
        elif char in DROPPED:
            changed += 1
        else:
            out.append(char)
    return "".join(out), changed


@dataclass(frozen=True, slots=True)
class Gap:
    """One bracketed gap in a paragraph."""

    start: int
    end: int
    text: str
    # How much of it is highlighted: "full", "partial" or "none".
    marking: str
    # Which occurrence of this exact text in the paragraph (0-based).
    nth: int


def gaps(chars: Sequence[Char]) -> list[Gap]:
    text = "".join(c.char for c in chars)
    found: list[Gap] = []
    seen: dict[str, int] = {}
    for match in PLACEHOLDER.finditer(text):
        span = chars[match.start() : match.end()]
        marked = sum(1 for c in span if c.highlighted)
        marking = "full" if marked == len(span) else "none" if marked == 0 else "partial"
        nth = seen.get(match.group(), 0)
        seen[match.group()] = nth + 1
        found.append(Gap(match.start(), match.end(), match.group(), marking, nth))
    return found


def unbalanced(text: str) -> bool:
    stripped = PLACEHOLDER.sub("", text)
    return "[" in stripped or "]" in stripped


def highlighted_outside(chars: Sequence[Char], spans: Sequence[Gap]) -> bool:
    inside = {i for g in spans for i in range(g.start, g.end)}
    return any(c.highlighted and c.char.strip() and i not in inside for i, c in enumerate(chars))


# --- scan --------------------------------------------------------------------------------


def _paragraph_scan(paragraph: Paragraph) -> dict[str, Any]:
    found = gaps(paragraph.chars)
    notes = []
    if unbalanced(paragraph.text):
        notes.append("unbalanced_brackets")
    if highlighted_outside(paragraph.chars, found):
        notes.append("highlighted_text_outside_brackets")
    if NONSTANDARD_BRACKETS.search(paragraph.text):
        notes.append("nonstandard_brackets")
    return {
        "index": paragraph.index,
        "cell": None if paragraph.cell is None else list(paragraph.cell),
        "heading": paragraph.heading,
        "list_item": paragraph.list_item,
        "text": paragraph.text,
        "gaps": [
            {
                "text": g.text,
                "nth": g.nth,
                "marking": g.marking,
                "hint": "conditional"
                if CONDITIONAL_HINT.match(g.text)
                else "instruction"
                if INSTRUCTION_HINT.match(g.text)
                else "field",
            }
            for g in found
        ],
        "notes": notes,
    }


def scan(document: Document) -> dict[str, Any]:
    """The document's structure, every gap and everything a person must decide."""
    paragraphs = [_paragraph_scan(p) for p in document.paragraphs()]
    all_gaps = [g for p in paragraphs for g in p["gaps"]]
    review = sorted(
        {
            *(f"gap_{g['marking']}_highlight" for g in all_gaps if g["marking"] != "full"),
            *(f"gap_{g['hint']}" for g in all_gaps if g["hint"] != "field"),
            *(note for p in paragraphs for note in p["notes"]),
            *document.flags,
        }
    )
    return {
        "source_sha256": document.sha256,
        "summary": {
            "paragraphs": len(paragraphs),
            "tables": sum(1 for item in document.body if isinstance(item, Table)),
            "gaps": len(all_gaps),
            "gaps_fully_highlighted": sum(1 for g in all_gaps if g["marking"] == "full"),
            "gaps_partly_highlighted": sum(1 for g in all_gaps if g["marking"] == "partial"),
            "gaps_not_highlighted": sum(1 for g in all_gaps if g["marking"] == "none"),
            "conditional_hints": sum(1 for g in all_gaps if g["hint"] == "conditional"),
            "instruction_hints": sum(1 for g in all_gaps if g["hint"] == "instruction"),
        },
        "needs_review": review,
        "flags": document.flags,
        "paragraphs": paragraphs,
    }


# --- the mapping -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Patch:
    paragraph: int
    before: str
    after: str
    reference: str


@dataclass(frozen=True, slots=True)
class Conditional:
    paragraph: int
    prefix: str
    choice: str
    options: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Repeat:
    first: int
    last: int
    field: str


@dataclass(slots=True)
class MappingSpec:
    source_sha256: str
    template: dict[str, Any]
    instructions: tuple[int, int] | None
    fields: dict[str, str]
    # (paragraph, gap text, nth) → field key, or None for "literal text"
    occurrences: dict[tuple[int, str, int], str | None]
    conditionals: dict[int, Conditional]
    repeats: list[Repeat]
    patches: dict[int, list[Patch]]
    literal_highlights: frozenset[int]
    acknowledged: frozenset[str]
    field_specs: list[dict[str, Any]]
    choices: list[dict[str, Any]]


def _require(data: Mapping[str, Any], keys: set[str], optional: set[str], where: str) -> None:
    if not isinstance(data, dict):
        raise ConversionError("expected_object", where)
    if not keys <= set(data) or not set(data) <= keys | optional:
        raise ConversionError("invalid_mapping_fields", where)


def _index(value: Any, where: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConversionError("invalid_paragraph_index", where)
    return value


def parse_mapping(raw: Any) -> MappingSpec:
    _require(
        raw,
        {"schema", "source_sha256", "template", "field_specs"},
        {"instructions", "fields", "occurrences", "conditionals", "repeats", "patches",
         "literal_highlights", "acknowledged_flags", "choices"},
        "$",
    )  # fmt: skip
    if raw["schema"] != MAPPING_SCHEMA:
        raise ConversionError("unsupported_mapping_schema", "$.schema")
    _require(
        raw["template"],
        {"key", "code", "title", "kind", "version", "review", "jurisdictions"},
        set(),
        "$.template",
    )
    instructions = None
    if raw.get("instructions") is not None:
        _require(raw["instructions"], {"first", "last"}, set(), "$.instructions")
        first = _index(raw["instructions"]["first"], "$.instructions.first")
        last = _index(raw["instructions"]["last"], "$.instructions.last")
        if last < first:
            raise ConversionError("invalid_range", "$.instructions")
        instructions = (first, last)
    fields = raw.get("fields", {})
    if not isinstance(fields, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in fields.items()
    ):
        raise ConversionError("invalid_mapping_fields", "$.fields")
    occurrences: dict[tuple[int, str, int], str | None] = {}
    for i, item in enumerate(raw.get("occurrences", [])):
        where = f"$.occurrences[{i}]"
        _require(item, {"paragraph", "gap"}, {"nth", "field", "literal"}, where)
        if ("field" in item) == bool(item.get("literal", False)):
            raise ConversionError("occurrence_needs_field_or_literal", where)
        key = (
            _index(item["paragraph"], where),
            str(item["gap"]),
            _index(item.get("nth", 0), where),
        )
        if key in occurrences:
            raise ConversionError("duplicate_occurrence", where)
        occurrences[key] = item.get("field")
    conditionals: dict[int, Conditional] = {}
    for i, item in enumerate(raw.get("conditionals", [])):
        where = f"$.conditionals[{i}]"
        _require(item, {"paragraph", "prefix", "choice", "options"}, set(), where)
        paragraph = _index(item["paragraph"], where)
        if paragraph in conditionals:
            raise ConversionError("duplicate_conditional", where)
        conditionals[paragraph] = Conditional(
            paragraph,
            str(item["prefix"]),
            str(item["choice"]),
            tuple(str(o) for o in item["options"]),
        )
    repeats = []
    for i, item in enumerate(raw.get("repeats", [])):
        where = f"$.repeats[{i}]"
        _require(item, {"first", "last", "field"}, set(), where)
        first, last = _index(item["first"], where), _index(item["last"], where)
        if last <= first:
            raise ConversionError("invalid_range", where)
        repeats.append(Repeat(first, last, str(item["field"])))
    patches: dict[int, list[Patch]] = {}
    for i, item in enumerate(raw.get("patches", [])):
        where = f"$.patches[{i}]"
        _require(item, {"paragraph", "before", "after", "reference", "approved_by"}, set(), where)
        if not isinstance(item["approved_by"], str) or not item["approved_by"].strip():
            # Wording changes need the template owner's approval, recorded here.
            raise ConversionError("patch_not_approved", where)
        if not isinstance(item["before"], str) or not item["before"]:
            raise ConversionError("invalid_patch", where)
        paragraph = _index(item["paragraph"], where)
        patches.setdefault(paragraph, []).append(
            Patch(paragraph, item["before"], str(item["after"]), str(item["reference"]))
        )
    return MappingSpec(
        source_sha256=str(raw["source_sha256"]),
        template=raw["template"],
        instructions=instructions,
        fields=fields,
        occurrences=occurrences,
        conditionals=conditionals,
        repeats=repeats,
        patches=patches,
        literal_highlights=frozenset(
            _index(v, "$.literal_highlights") for v in raw.get("literal_highlights", [])
        ),
        acknowledged=frozenset(str(v) for v in raw.get("acknowledged_flags", [])),
        field_specs=list(raw["field_specs"]),
        choices=list(raw.get("choices", [])),
    )


# --- convert -----------------------------------------------------------------------------


@dataclass(slots=True)
class Stats:
    normalized: int = 0
    empty_paragraphs: int = 0
    patches: int = 0
    gaps: int = 0
    literal_gaps: int = 0
    confirmed_unhighlighted: int = 0


@dataclass(slots=True)
class Converted:
    blocks: list[dict[str, Any]]
    instructions: list[dict[str, Any]]
    # Per body block: the source paragraphs it came from and, per field
    # segment in order, the gap text it replaced.
    source: list[dict[str, Any]]
    instruction_source: list[int]
    stats: Stats = field(default_factory=Stats)
    patches: list[dict[str, Any]] = field(default_factory=list)


def _apply_patches(
    paragraph: Paragraph,
    chars: list[Char],
    spec: MappingSpec,
    stats: Stats,
    applied: list[dict[str, Any]],
) -> list[Char]:
    for patch in spec.patches.get(paragraph.index, []):
        text = "".join(c.char for c in chars)
        at = text.find(patch.before)
        if at < 0 or text.find(patch.before, at + 1) >= 0:
            raise ConversionError("patch_not_found_exactly_once", f"paragraph {paragraph.index}")
        end = at + len(patch.before)
        if any(g.start < end and at < g.end for g in gaps(chars)):
            # Gaps are mapped, never edited by a patch.
            raise ConversionError("patch_overlaps_gap", f"paragraph {paragraph.index}")
        chars = [*chars[:at], *(Char(c, False) for c in patch.after), *chars[end:]]
        stats.patches += 1
        applied.append(
            {
                "paragraph": paragraph.index,
                "before": patch.before,
                "after": patch.after,
                "reference": patch.reference,
            }
        )
    return chars


def _text_segments(text: str, stats: Stats, where: str) -> list[dict[str, Any]]:
    """Wording as text and break segments (line breaks inside a paragraph)."""
    out: list[dict[str, Any]] = []
    normalized, changed = normalize(text)
    stats.normalized += changed
    for i, line in enumerate(normalized.split("\n")):
        if i > 0:
            out.append({"break": True})
        if line:
            if not line.isprintable():
                raise ConversionError("unprintable_character", where)
            out.append({"text": line})
    return out


def _segments(
    paragraph: Paragraph,
    chars: list[Char],
    spec: MappingSpec,
    stats: Stats,
) -> tuple[list[dict[str, Any]], list[str]]:
    """A paragraph's segments, and the gap text each field segment replaced (in order)."""
    where = f"paragraph {paragraph.index}"
    found = gaps(chars)
    text = "".join(c.char for c in chars)
    # A person confirms these paragraphs' marks are wording, not placeholders.
    if paragraph.index not in spec.literal_highlights:
        if highlighted_outside(chars, found):
            raise ConversionError("highlighted_text_outside_brackets", where)
        if NONSTANDARD_BRACKETS.search(text):
            raise ConversionError("nonstandard_brackets", where)
    segments: list[dict[str, Any]] = []
    replaced: list[str] = []
    position = 0
    for gap in found:
        override_key = (paragraph.index, gap.text, gap.nth)
        if override_key in spec.occurrences:
            field_key = spec.occurrences[override_key]
            if gap.marking != "full" and field_key is not None:
                stats.confirmed_unhighlighted += 1
        elif gap.marking == "full" and gap.text in spec.fields:
            field_key = spec.fields[gap.text]
        elif gap.marking != "full":
            # Never mapped by its text alone: a person confirms it.
            raise ConversionError("unconfirmed_gap", where)
        else:
            raise ConversionError("unmapped_gap", where)
        stats.gaps += 1
        if field_key is None:
            stats.literal_gaps += 1
            continue  # literal text: stays part of the wording
        segments += _text_segments(text[position : gap.start], stats, where)
        segments.append({"field": field_key})
        replaced.append(gap.text)
        position = gap.end
    segments += _text_segments(text[position:], stats, where)
    return segments, replaced


def _block_type(paragraph: Paragraph) -> str:
    return "heading" if paragraph.heading else "item" if paragraph.list_item else "paragraph"


def convert(document: Document, spec: MappingSpec) -> Converted:
    """The working copy's blocks and its source map, or ``ConversionError``."""
    if spec.source_sha256 != document.sha256:
        raise ConversionError("source_mismatch", "$.source_sha256")
    unacknowledged = set(document.flags) - spec.acknowledged
    if unacknowledged:
        # Text in headers or footers, comments, images: a person decides.
        raise ConversionError("unreviewed_flags", ",".join(sorted(unacknowledged)))
    converted = Converted([], [], [], [])
    stats = converted.stats
    known = {p.index for p in document.paragraphs()}
    for index in [*spec.conditionals, *spec.patches, *spec.literal_highlights]:
        if index not in known:
            raise ConversionError("unknown_paragraph", f"paragraph {index}")
    used_conditionals: set[int] = set()

    for item in document.body:
        if isinstance(item, Table):
            rows = []
            source_rows = []
            for row in item.rows:
                cells = []
                source_cells = []
                for cell in row:
                    cell_segments: list[dict[str, Any]] = []
                    cell_replaced: list[str] = []
                    cell_paragraphs: list[int] = []
                    for paragraph in cell:
                        chars = _apply_patches(
                            paragraph, list(paragraph.chars), spec, stats, converted.patches
                        )
                        if not "".join(c.char for c in chars).strip():
                            stats.empty_paragraphs += 1
                            continue
                        segments, replaced = _segments(paragraph, chars, spec, stats)
                        if cell_segments:
                            cell_segments.append({"break": True})
                        cell_segments += segments
                        cell_replaced += replaced
                        cell_paragraphs.append(paragraph.index)
                    cells.append(cell_segments)
                    source_cells.append({"paragraphs": cell_paragraphs, "gaps": cell_replaced})
                rows.append(cells)
                source_rows.append(source_cells)
            converted.blocks.append({"type": "table", "rows": rows})
            converted.source.append({"table": item.index, "rows": source_rows})
            continue

        paragraph = item
        in_instructions = (
            spec.instructions is not None
            and spec.instructions[0] <= paragraph.index <= spec.instructions[1]
        )
        chars = _apply_patches(paragraph, list(paragraph.chars), spec, stats, converted.patches)
        text = "".join(c.char for c in chars)
        if not text.strip():
            stats.empty_paragraphs += 1
            continue
        if in_instructions:
            # Employer guidance: wording only (its brackets stay text), never in the document.
            segments = _text_segments(text, stats, f"paragraph {paragraph.index}")
            converted.instructions.append({"type": _block_type(paragraph), "content": segments})
            converted.instruction_source.append(paragraph.index)
            continue
        block: dict[str, Any] = {"type": _block_type(paragraph)}
        conditional = spec.conditionals.get(paragraph.index)
        prefix = ""
        if conditional is not None:
            if not text.startswith(conditional.prefix):
                raise ConversionError(
                    "conditional_prefix_not_found", f"paragraph {paragraph.index}"
                )
            prefix = conditional.prefix
            chars = chars[len(prefix) :]
            block["when"] = {"choice": conditional.choice, "in": list(conditional.options)}
            used_conditionals.add(paragraph.index)
        segments, replaced = _segments(paragraph, chars, spec, stats)
        if not segments:
            raise ConversionError("empty_after_mapping", f"paragraph {paragraph.index}")
        block["content"] = segments
        converted.blocks.append(block)
        converted.source.append(
            {"paragraphs": [paragraph.index], "gaps": [replaced], "prefix": normalize(prefix)[0]}
        )

    if spec.instructions is not None and not converted.instruction_source:
        raise ConversionError("no_instructions_in_range", "$.instructions")
    _collapse_repeats(converted, spec)
    return converted


def _collapse_repeats(converted: Converted, spec: MappingSpec) -> None:
    """Consecutive identical paragraphs named by a repeat become one repeat block."""
    for repeat in spec.repeats:
        where = f"paragraphs {repeat.first}-{repeat.last}"
        positions = [
            i
            for i, source in enumerate(converted.source)
            if source.get("paragraphs") and len(source["paragraphs"]) == 1
            and repeat.first <= source["paragraphs"][0] <= repeat.last and "table" not in source
        ]  # fmt: skip
        if len(positions) < 2 or positions != list(
            range(positions[0], positions[0] + len(positions))
        ):
            raise ConversionError("invalid_repeat_range", where)
        blocks = [converted.blocks[i] for i in positions]
        if (
            any(b != blocks[0] for b in blocks)
            or {"field": repeat.field} not in blocks[0]["content"]
        ):
            raise ConversionError("repeat_paragraphs_differ", where)
        sources = [converted.source[i] for i in positions]
        merged = {
            "paragraphs": [s["paragraphs"][0] for s in sources],
            "gaps": [s["gaps"][0] for s in sources],
            "prefix": sources[0]["prefix"],
            "repeat": True,
        }
        block = {**blocks[0], "repeat": repeat.field}
        start = positions[0]
        converted.blocks[start : start + len(positions)] = [block]
        converted.source[start : start + len(positions)] = [merged]


# --- verification ------------------------------------------------------------------------


def _segments_text(segments: Sequence[Mapping[str, Any]], replaced: Sequence[str]) -> str:
    """Segments back to text: each field becomes the gap it replaced."""
    out = ""
    gaps_left = list(replaced)
    for segment in segments:
        if "text" in segment:
            out += segment["text"]
        elif "break" in segment:
            out += "\n"
        elif "field" in segment:
            if not gaps_left:
                raise ConversionError("source_map_mismatch")
            out += gaps_left.pop(0)
        else:
            raise ConversionError("unexpected_segment")
    if gaps_left:
        raise ConversionError("source_map_mismatch")
    return out


def _source_texts(document: Document, spec: MappingSpec) -> dict[int, str]:
    """Each source paragraph's text after approved patches and layout normalization."""
    texts: dict[int, str] = {}
    for paragraph in document.paragraphs():
        text = paragraph.text
        for patch in spec.patches.get(paragraph.index, []):
            text = text.replace(patch.before, patch.after, 1)
        texts[paragraph.index] = normalize(text)[0]
    return texts


def _rebuilt(segments: Sequence[Mapping[str, Any]], replaced: Sequence[str]) -> str | None:
    """Segments back to text, or None if they no longer fit their source map."""
    try:
        return _segments_text(segments, replaced)
    except (ConversionError, KeyError, TypeError):
        return None


def verify(
    document: Document, spec: MappingSpec, engine: Mapping[str, Any], source_map: Mapping[str, Any]
) -> list[str]:
    """Every difference between the working copy and the source (empty: identical)."""
    try:
        return _verify(document, spec, engine, source_map)
    except (KeyError, TypeError, ValueError, IndexError):
        return ["working copy or source map: not in the expected structure"]


def _verify(
    document: Document, spec: MappingSpec, engine: Mapping[str, Any], source_map: Mapping[str, Any]
) -> list[str]:
    problems: list[str] = []
    if (
        source_map.get("source_sha256") != document.sha256
        or engine.get("template", {}).get("source_sha256") != document.sha256
    ):
        return ["source_sha256 differs"]
    expected = _source_texts(document, spec)
    template = engine["template"]
    used: list[int] = []

    for index, block in zip(
        source_map["instructions"], template.get("instructions", []), strict=False
    ):
        rebuilt = _rebuilt(block["content"], [])
        used.append(index)
        if rebuilt != expected[index]:
            problems.append(f"paragraph {index}: instructions differ")
    if len(source_map["instructions"]) != len(template.get("instructions", [])):
        problems.append("instructions: block count differs")

    blocks = template["body"]
    if len(blocks) != len(source_map["body"]):
        return [*problems, "body: block count differs"]
    for block, source in zip(blocks, source_map["body"], strict=True):
        if block["type"] == "table":
            for r, row in enumerate(block["rows"]):
                for c, cell in enumerate(row):
                    cell_source = source["rows"][r][c]
                    rebuilt = _rebuilt(cell, cell_source["gaps"])
                    original = "\n".join(expected[i] for i in cell_source["paragraphs"])
                    used += cell_source["paragraphs"]
                    if rebuilt != original:
                        problems.append(f"table {source['table']} row {r} cell {c}: text differs")
            continue
        for index, replaced in zip(source["paragraphs"], source["gaps"], strict=True):
            text = _rebuilt(block["content"], replaced)
            used.append(index)
            if text is None or source["prefix"] + text != expected[index]:
                problems.append(f"paragraph {index}: text differs")
    # Every non-empty source paragraph is accounted for, once, in order.
    nonempty = [i for i, text in sorted(expected.items()) if text.strip()]
    if sorted(used) != nonempty or len(set(used)) != len(used):
        problems.append("paragraphs: missing, repeated or extra")
    return problems


# --- outputs -----------------------------------------------------------------------------


def _check_bundle_content(template: dict[str, Any], field_specs: list[dict[str, Any]]) -> None:
    """The working copy is valid bundle content (the API's own parser decides)."""
    bundle = {
        "schema": "heroos.template-bundle/1",
        "bundle": "conversion-check",
        "version": "check",
        "provenance": "private",
        "approval": "provisional",
        "workflow": "disciplinary",
        "rule_bundle": {"bundle": "unchecked", "versions": ["unchecked"]},
        "notice": None,
        "fields": field_specs,
        "templates": [template],
    }
    try:
        parse_template_bundle(json.dumps(bundle).encode(), file_sha256="0" * 64)
    except TemplateBundleError as error:
        raise ConversionError(f"invalid_working_copy:{error.code}", error.location) from error


def build_outputs(document: Document, spec: MappingSpec) -> dict[str, Any]:
    converted = convert(document, spec)
    used = {
        segment["field"]
        for block in converted.blocks
        for segment in [
            *block.get("content", []),
            *(seg for row in block.get("rows", []) for cell in row for seg in cell),
        ]
        if "field" in segment
    }
    field_specs = [f for f in spec.field_specs if f.get("key") in used]
    missing = used - {f.get("key") for f in field_specs}
    if missing:
        raise ConversionError("field_without_spec", ",".join(sorted(missing)))
    template = {
        **spec.template,
        "source_sha256": document.sha256,
        "instructions": converted.instructions,
        "choices": spec.choices,
        "body": converted.blocks,
    }
    _check_bundle_content(template, field_specs)
    engine = {"template": template, "fields": field_specs}
    source_map = {
        "source_sha256": document.sha256,
        "instructions": converted.instruction_source,
        "body": converted.source,
    }
    problems = verify(document, spec, engine, source_map)
    if problems:
        raise ConversionError("verification_failed", "; ".join(problems[:5]))
    stats = converted.stats
    report = {
        "template": spec.template["key"],
        "code": spec.template["code"],
        "source_sha256": document.sha256,
        "verification": "PASS",
        "blocks": len(converted.blocks),
        "instruction_blocks": len(converted.instructions),
        "fields": len(field_specs),
        "gaps": stats.gaps,
        "literal_gaps": stats.literal_gaps,
        "confirmed_unhighlighted_gaps": stats.confirmed_unhighlighted,
        "approved_patches": stats.patches,
        "layout_normalizations": stats.normalized,
        "empty_paragraphs_skipped": stats.empty_paragraphs,
        "acknowledged_flags": sorted(spec.acknowledged),
    }
    return {
        "engine": engine,
        "source_map": source_map,
        "report": report,
        "review": review_pack(document, spec, engine, source_map, converted.patches, report),
    }


def _shown(segments: Sequence[Mapping[str, Any]], labels: Mapping[str, str]) -> str:
    out = ""
    for segment in segments:
        if "text" in segment:
            out += segment["text"]
        elif "break" in segment:
            out += " / "
        elif "field" in segment:
            out += f"⟦{labels.get(segment['field'], segment['field'])}⟧"
        elif "blank" in segment:
            out += f"[{segment['blank']}: ______]"
    return out


def review_pack(
    document: Document,
    spec: MappingSpec,
    engine: Mapping[str, Any],
    source_map: Mapping[str, Any],
    patches: Sequence[Mapping[str, Any]],
    report: Mapping[str, Any],
) -> str:
    """A side-by-side review for the template owner (private: it holds the wording)."""
    template = engine["template"]
    labels = {f["key"]: f["label"] for f in engine["fields"]}
    original = {p.index: p.text for p in document.paragraphs()}
    lines = [
        f"# Working copy review: {template['code']} {template['title']}",
        "",
        f"- Source document SHA-256: `{document.sha256}`",
        f"- Verification: **{report['verification']}**: every word of the source is unchanged, "
        f"except the {report['approved_patches']} approved change(s) listed below and "
        f"{report['layout_normalizations']} layout normalization(s) (tabs or special spaces "
        "shown as a plain space, soft hyphens dropped).",
        f"- Gaps that became fields: {report['gaps'] - report['literal_gaps']}; kept as wording: "
        f"{report['literal_gaps']}; not highlighted in the source but confirmed as fields: "
        f"{report['confirmed_unhighlighted_gaps']}.",
        f"- Flags reviewed: {', '.join(report['acknowledged_flags']) or 'none'}.",
        "",
        "## Fields",
        "",
        "| Field | Label | Kind |",
        "| --- | --- | --- |",
        *(f"| `{f['key']}` | {f['label']} | {f['kind']} |" for f in engine["fields"]),
        "",
        "## Choices",
        "",
        *(
            f"- **{c['label']}** ({'one or more' if c['multiple'] else 'one'}): "
            + ", ".join(o["label"] for o in c["options"])
            for c in template.get("choices", [])
        ),
        "" if template.get("choices") else "None.",
        "",
        "## Approved changes",
        "",
    ]
    if patches:
        lines += ["| Paragraph | Before | After | Reference |", "| --- | --- | --- | --- |"]
        lines += [
            f"| {p['paragraph']} | {p['before']} | {p['after'] or '(removed)'} | {p['reference']} |"
            for p in patches
        ]
    else:
        lines.append("None.")
    lines += ["", "## Employer instructions (shown beside the form, never in the document)", ""]
    for block in template.get("instructions", []):
        lines.append(f"> {_shown(block['content'], labels)}")
    lines += ["", "## Side by side", ""]
    for block, source in zip(template["body"], source_map["body"], strict=True):
        if block["type"] == "table":
            lines.append(f"### Table {source['table']}")
            for row in block["rows"]:
                lines.append("| " + " | ".join(_shown(cell, labels) for cell in row) + " |")
            lines.append("")
            continue
        heading = ", ".join(str(i) for i in source["paragraphs"])
        lines.append(
            f"### Paragraph {heading}" + (" (repeated per entry)" if block.get("repeat") else "")
        )
        for index in source["paragraphs"]:
            lines.append(f"- Source: {original[index]}")
        condition = block.get("when")
        if condition:
            lines.append(
                f"- Shown when **{condition['choice']}** is {' or '.join(condition['in'])}"
            )
        lines.append(f"- Working copy: {_shown(block['content'], labels)}")
        lines.append("")
    return "\n".join(lines) + "\n"


def assemble(meta: Mapping[str, Any], engines: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """One private template bundle from approved working copies (validated by the caller)."""
    required = {"bundle", "version", "approval", "workflow", "rule_bundle"}
    if (
        not isinstance(meta, dict)
        or not required <= set(meta)
        or not set(meta) <= required | {"notice"}
    ):
        raise ConversionError("invalid_meta", "$")
    fields: dict[str, dict[str, Any]] = {}
    for engine in engines:
        for spec in engine["fields"]:
            known = fields.get(spec["key"])
            if known is not None and known != spec:
                raise ConversionError("conflicting_field", spec["key"])
            fields[spec["key"]] = spec
    return {
        "schema": "heroos.template-bundle/1",
        "bundle": meta["bundle"],
        "version": meta["version"],
        "provenance": "private",
        "approval": meta["approval"],
        "workflow": meta["workflow"],
        "rule_bundle": meta["rule_bundle"],
        "notice": meta.get("notice"),
        "fields": list(fields.values()),
        "templates": [engine["template"] for engine in engines],
    }


# --- CLI -----------------------------------------------------------------------------------


def inside_git_repository(path: Path) -> bool:
    """Whether ``path`` would be inside a git working tree (outputs hold template wording)."""
    current = path.resolve()
    return any((candidate / ".git").exists() for candidate in (current, *current.parents))


def _private_dir(path: Path) -> Path:
    if inside_git_repository(path):
        raise ConversionError("output_inside_git_repository")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ConversionError("unreadable_json", path.name) from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="template_import", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    scan_cmd = commands.add_parser("scan", help="report a document's gaps and what needs review")
    scan_cmd.add_argument("docx", type=Path)
    scan_cmd.add_argument("--out", type=Path, required=True)
    convert_cmd = commands.add_parser("convert", help="convert a document with an approved mapping")
    convert_cmd.add_argument("docx", type=Path)
    convert_cmd.add_argument("mapping", type=Path)
    convert_cmd.add_argument("--out", type=Path, required=True)
    verify_cmd = commands.add_parser(
        "verify", help="check a stored working copy against its source"
    )
    verify_cmd.add_argument("docx", type=Path)
    verify_cmd.add_argument("mapping", type=Path)
    verify_cmd.add_argument("engine", type=Path)
    verify_cmd.add_argument("source_map", type=Path)
    assemble_cmd = commands.add_parser(
        "assemble", help="combine working copies into a private bundle"
    )
    assemble_cmd.add_argument("meta", type=Path)
    assemble_cmd.add_argument("engines", type=Path, nargs="+")
    assemble_cmd.add_argument("--out", type=Path, required=True)
    assemble_cmd.add_argument("--rules", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "scan":
            out = _private_dir(args.out)
            result = scan(read_docx(args.docx))
            _write(
                out / f"scan-{result['source_sha256'][:12]}.json",
                json.dumps(result, indent=2, ensure_ascii=False),
            )
            print(json.dumps({"source_sha256": result["source_sha256"], **result["summary"],
                              "needs_review": result["needs_review"]}, indent=2))  # fmt: skip
            return 0
        if args.command == "convert":
            out = _private_dir(args.out)
            spec = parse_mapping(_load_json(args.mapping))
            outputs = build_outputs(read_docx(args.docx), spec)
            key = spec.template["key"]
            _write(
                out / f"{key}.engine.json",
                json.dumps(outputs["engine"], indent=2, ensure_ascii=False),
            )
            _write(
                out / f"{key}.source-map.json",
                json.dumps(outputs["source_map"], indent=2, ensure_ascii=False),
            )
            _write(out / f"{key}.review.md", outputs["review"])
            _write(out / f"{key}.conversion.json", json.dumps(outputs["report"], indent=2))
            print(json.dumps(outputs["report"], indent=2))
            return 0
        if args.command == "verify":
            spec = parse_mapping(_load_json(args.mapping))
            problems = verify(
                read_docx(args.docx), spec, _load_json(args.engine), _load_json(args.source_map)
            )
            print("verification: PASS" if not problems else f"verification: FAIL ({len(problems)})")
            for problem in problems:
                print(f"  {problem}")
            return 0 if not problems else 1
        # assemble
        if not args.out.name.endswith(".private-templates.json"):
            raise ConversionError("output_name_must_end_private_templates_json")
        _private_dir(args.out.parent)
        bundle = assemble(_load_json(args.meta), [_load_json(path) for path in args.engines])
        content = json.dumps(bundle, indent=2, ensure_ascii=False).encode()
        parsed = parse_template_bundle(content, file_sha256=hashlib.sha256(content).hexdigest())
        if args.rules is not None:
            rules = load_bundle(
                args.rules, hashlib.sha256(args.rules.read_bytes()).hexdigest(), production=False
            )
            check_against_rules(parsed, rules)
        args.out.write_bytes(content)
        args.out.chmod(0o600)
        print(f"bundle:      {parsed.bundle_id} {parsed.version} ({parsed.approval})")
        print(f"pin:         HEROOS_TEMPLATE_BUNDLE_SHA256={parsed.file_sha256}")
        print(f"templates:   {', '.join(t.code for t in parsed.templates)}")
        return 0
    except (DocxRefused, ConversionError, TemplateBundleError, RuleBundleError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
