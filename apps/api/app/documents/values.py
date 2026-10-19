"""What an employer types into a template's fields and choices (M2-04C): validation only.

Values are taken exactly as typed (never trimmed, rewritten or inferred) and
used once, to draw a preview: nothing here stores, logs or remembers them.
Messages are fixed and never repeat a submitted value.

- text: one line, no control or invisible formatting characters, bounded;
- long text: line breaks and tabs allowed, nothing else invisible, bounded;
- date: exactly ``YYYY-MM-DD``, a real date from 1990 to 2100;
- list: one to ``items`` entries, each a bounded line of text.

A field left out is simply missing (the preview shows a visible gap); an
empty or blank value is refused, so "missing" always means "not given".
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final

from app.documents.bundle import FieldSpec, Template
from app.workflows.answers import TEXT_CONTROL_CHARACTERS

EARLIEST: Final = date(1990, 1, 1)
LATEST: Final = date(2100, 12, 31)

Value = str | tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValueProblem:
    # ("values", key) or ("choices", key); the key is the template's own, never
    # a submitted one (an unknown key is reported without it).
    loc: tuple[str, ...]
    message: str


def line_error(value: str, limit: int) -> str | None:
    if value.strip() == "":
        return "must not be empty"
    if value != value.strip():
        return "must not start or end with whitespace"
    if not value.isprintable():
        return "must not contain control characters"
    if len(value) > limit:
        return f"must be at most {limit} characters"
    return None


def _text_error(value: str, limit: int) -> str | None:
    if value.strip() == "":
        return "must not be empty"
    if value != value.strip():
        return "must not start or end with whitespace"
    if any(not c.isprintable() and c not in TEXT_CONTROL_CHARACTERS for c in value):
        return "must not contain control characters"
    if len(value) > limit:
        return f"must be at most {limit} characters"
    return None


def _date_error(value: str) -> str | None:
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return "must be a date (YYYY-MM-DD)"
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return "must be a date (YYYY-MM-DD)"
    if not EARLIEST <= parsed <= LATEST:
        return "must be between 1990 and 2100"
    return None


def _value_error(spec: FieldSpec, value: object) -> str | None:
    if spec.kind == "list":
        if not isinstance(value, list | tuple) or not all(isinstance(i, str) for i in value):
            return "must be a list of text entries"
        assert spec.max_items is not None and spec.max_length is not None
        if not value:
            return "must have at least one entry"
        if len(value) > spec.max_items:
            return f"must have at most {spec.max_items} entries"
        for item in value:
            error = line_error(item, spec.max_length)
            if error is not None:
                return f"has an entry that {error}"
        return None
    if not isinstance(value, str):
        return "must be text"
    if spec.kind == "date":
        return _date_error(value)
    assert spec.max_length is not None
    if spec.kind == "long_text":
        return _text_error(value, spec.max_length)
    return line_error(value, spec.max_length)


def validate_values(
    template: Template,
    fields: Mapping[str, FieldSpec],
    values: Mapping[str, object],
    choices: Mapping[str, object],
) -> tuple[dict[str, Value], dict[str, frozenset[str]], list[ValueProblem]]:
    """The accepted values and choices, and every error (all checked, none echoed)."""
    errors: list[ValueProblem] = []
    accepted: dict[str, Value] = {}
    own = set(template.fields)
    if any(key not in own for key in values):
        errors.append(ValueProblem(("values",), "has a field this template doesn't use"))
    for key in template.fields:
        if key not in values:
            continue
        error = _value_error(fields[key], values[key])
        if error is not None:
            errors.append(ValueProblem(("values", key), error))
            continue
        value = values[key]
        accepted[key] = tuple(value) if isinstance(value, list | tuple) else str(value)

    selected: dict[str, frozenset[str]] = {}
    known = {c.key for c in template.choices}
    if any(key not in known for key in choices):
        errors.append(ValueProblem(("choices",), "has a choice this template doesn't have"))
    for choice in template.choices:
        if choice.key not in choices:
            continue
        raw = choices[choice.key]
        if not isinstance(raw, list | tuple) or not all(isinstance(v, str) for v in raw):
            errors.append(ValueProblem(("choices", choice.key), "must be a list of options"))
            continue
        if not raw or len(set(raw)) != len(raw):
            errors.append(ValueProblem(("choices", choice.key), "must name distinct options"))
            continue
        if any(choice.option(v) is None for v in raw):
            errors.append(ValueProblem(("choices", choice.key), "is not an option of this choice"))
            continue
        if not choice.multiple and len(raw) != 1:
            errors.append(ValueProblem(("choices", choice.key), "must name exactly one option"))
            continue
        selected[choice.key] = frozenset(raw)
    return accepted, selected, errors
