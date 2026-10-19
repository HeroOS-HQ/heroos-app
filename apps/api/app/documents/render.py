"""Filling a template into a preview (M2-04C): structured text, never markup.

``render`` turns a template, the employer's values and choices into blocks of
typed segments: wording (``text``), an employer value (``value``), a visible
gap for something not given (``missing``), a line left blank for a
handwritten entry (``blank``) and a line break (``break``). There is no
template language and no HTML: a value is inserted exactly as typed, as text,
so nothing an employer types can change the template, run anything or become
markup or a link. The browser renders segments as text nodes.

Choices select alternative paragraphs. While a choice isn't made, its first
conditional paragraph becomes a visible "choose ..." gap and the others are
left out, so a preview never silently picks an alternative. A repeat block
is written once per list entry (a gap when the list is missing).

Pure: no database, no logging, nothing remembered.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

from app.documents.bundle import Block, FieldSpec, Segment, Template
from app.documents.values import Value

MONTHS: Final = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

SegmentKind = Literal["text", "value", "missing", "blank", "break"]


@dataclass(frozen=True, slots=True)
class OutSegment:
    kind: SegmentKind
    # text / value: the text to show; None otherwise.
    text: str | None = None
    # value / missing: the field (or, for a choice gap, the choice) it stands for.
    field: str | None = None
    # missing / blank: what belongs there.
    label: str | None = None


@dataclass(frozen=True, slots=True)
class OutBlock:
    type: Literal["heading", "paragraph", "item", "table"]
    segments: tuple[OutSegment, ...] = ()
    rows: tuple[tuple[tuple[OutSegment, ...], ...], ...] = ()


@dataclass(frozen=True, slots=True)
class Rendered:
    blocks: tuple[OutBlock, ...]
    # Fields and choices still to fill in, in order of first appearance.
    missing: tuple[str, ...]


def format_date(value: str) -> str:
    """``YYYY-MM-DD`` as a day, month name and year ("18 October 2026")."""
    parsed = date.fromisoformat(value)
    return f"{parsed.day} {MONTHS[parsed.month - 1]} {parsed.year}"


def _shown(spec: FieldSpec, value: str) -> str:
    return format_date(value) if spec.kind == "date" else value


def _segments(
    segments: tuple[Segment, ...],
    fields: Mapping[str, FieldSpec],
    values: Mapping[str, Value],
    missing: list[str],
    item: tuple[str, str] | None = None,
) -> tuple[OutSegment, ...]:
    out: list[OutSegment] = []
    for segment in segments:
        if segment.kind == "text":
            out.append(OutSegment("text", text=segment.value))
        elif segment.kind == "blank":
            out.append(OutSegment("blank", label=segment.value))
        elif segment.kind == "break":
            out.append(OutSegment("break"))
        else:
            key = segment.value
            assert key is not None
            spec = fields[key]
            if item is not None and item[0] == key:
                out.append(OutSegment("value", text=item[1], field=key))
                continue
            value = values.get(key)
            if isinstance(value, str):
                out.append(OutSegment("value", text=_shown(spec, value), field=key))
            else:
                if key not in missing:
                    missing.append(key)
                out.append(OutSegment("missing", field=key, label=spec.label))
    return tuple(out)


def _block(
    block: Block,
    fields: Mapping[str, FieldSpec],
    values: Mapping[str, Value],
    missing: list[str],
) -> list[OutBlock]:
    if block.type == "table":
        rows = tuple(
            tuple(_segments(cell, fields, values, missing) for cell in row) for row in block.rows
        )
        return [OutBlock("table", rows=rows)]
    if block.repeat is None:
        return [OutBlock(block.type, _segments(block.content, fields, values, missing))]
    entries = values.get(block.repeat)
    if not isinstance(entries, tuple):
        # One block showing the gap where the entries go.
        return [OutBlock(block.type, _segments(block.content, fields, values, missing))]
    return [
        OutBlock(
            block.type,
            _segments(block.content, fields, values, missing, item=(block.repeat, entry)),
        )
        for entry in entries
    ]


def render_blocks(
    blocks: tuple[Block, ...],
    choice_labels: Mapping[str, str],
    fields: Mapping[str, FieldSpec],
    values: Mapping[str, Value],
    choices: Mapping[str, frozenset[str]],
) -> Rendered:
    missing: list[str] = []
    out: list[OutBlock] = []
    gaps_shown: set[str] = set()
    for block in blocks:
        if block.when is not None:
            selected = choices.get(block.when.choice)
            if selected is None:
                if block.when.choice not in gaps_shown:
                    gaps_shown.add(block.when.choice)
                    if block.when.choice not in missing:
                        missing.append(block.when.choice)
                    label = f"Choose: {choice_labels[block.when.choice]}"
                    gap = OutSegment("missing", field=block.when.choice, label=label)
                    out.append(OutBlock("paragraph", (gap,)))
                continue
            if not selected & block.when.values:
                continue
        out += _block(block, fields, values, missing)
    return Rendered(tuple(out), tuple(missing))


def render(
    template: Template,
    fields: Mapping[str, FieldSpec],
    values: Mapping[str, Value],
    choices: Mapping[str, frozenset[str]],
) -> Rendered:
    """The template's body filled with the given values and choices."""
    labels = {c.key: c.label for c in template.choices}
    return render_blocks(template.body, labels, fields, values, choices)


def render_instructions(template: Template) -> tuple[OutBlock, ...]:
    """The employer guidance shown beside the form (wording only, never in the preview)."""
    return render_blocks(template.instructions, {}, {}, {}, {}).blocks
