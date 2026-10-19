"""Private document-template bundles: schema, strict validation and loading (M2-04C).

A template bundle is a small, versioned, declarative JSON document holding the
letter and email templates the generic preview engine fills: their wording as
structured text blocks, the fields an employer fills in, the choices between
alternative paragraphs, and the workflow stages (per jurisdiction) at which
each template may be previewed. The real (``private``) bundle is proprietary
and never lives in this repository; a fictional ``synthetic`` bundle tests the
engine.

Loading contract (``load_template_bundle``), all fail-closed:

- the backend reads one file from server-side storage, once, at startup; the
  browser never receives the bundle (only one available template at a time,
  to an administrator of a Case at that template's stage);
- the file's SHA-256 must equal the configured pin, so an outdated or swapped
  file is refused instead of silently used;
- the JSON must match this schema exactly: unknown or missing fields, an
  unknown schema version, duplicate keys, a reference to an unknown field or
  choice, an unused field or choice, a precondition reading a sensitive
  answer, or content beyond the bounds below are all refused;
- the bundle must name the installed rule bundle, and every stage and
  checklist answer it refers to must exist in it (``check_against_rules``);
- production refuses a synthetic bundle and a bundle whose wording is still
  provisional.

Errors carry a fixed code and a structural location (indexes and keys, never
wording). Templates are data: there is no template language, no HTML and no
``eval``; a field is replaced by the employer's text, verbatim.

Schema ``heroos.template-bundle/1``::

    {"schema", "bundle", "version", "provenance": "synthetic" | "private",
     "approval": "provisional" | "approved", "workflow",
     "rule_bundle": {"bundle", "versions": [str]},
     "notice": {"title", "body"} | null,
     "fields": [{"key", "label", "kind": "text" | "long_text" | "date" | "list",
                 "max"?, "items"?, "help"?, "suggest"?: "company_name" | "subject_name",
                 "reminder"?: bool}],
     "templates": [{"key", "code", "title", "kind": "letter" | "email" | "minutes",
        "version", "source_sha256": hex | null, "review": "employer" | "specialist_first",
        "jurisdictions": {"<code>": {"stages": [stage], "require"?: predicate}},
        "instructions": [block], "choices": [choice], "body": [block]}]}

    choice  = {"key", "label", "help"?, "multiple": bool, "options": [{"value", "label"}]}
    block   = {"type": "heading" | "paragraph" | "item", "content": [segment],
               "when"?: {"choice", "in": [value]}, "repeat"?: "<list field>"}
            | {"type": "table", "rows": [[[segment]]], "when"?: {...}}
    segment = {"text": str} | {"field": key} | {"blank": label} | {"break": true}

``review: "specialist_first"`` marks a template that needs a person's specialist
review before it may be offered; no such review exists in HeroOS yet, so these
templates are never available. A ``repeat`` block is repeated once per item of
a list field (inside it, that field stands for the item); a list field can
only be used in its own repeat blocks.
"""

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from app.workflows.conditions import JURISDICTIONS
from app.workflows.definition import current_definition
from app.workflows.progression import predicates
from app.workflows.progression.bundle import FACT_PREFIX, RuleBundle
from app.workflows.progression.spec import PROGRESSIONS

SCHEMA: Final = "heroos.template-bundle/1"
Provenance = Literal["synthetic", "private"]
Approval = Literal["provisional", "approved"]
FieldKind = Literal["text", "long_text", "date", "list"]
TemplateKind = Literal["letter", "email", "minutes"]
Review = Literal["employer", "specialist_first"]
BlockType = Literal["heading", "paragraph", "item", "table"]
# Case facts a field may be suggested from (the employer can change or clear it).
Suggestion = Literal["company_name", "subject_name"]

# Bounds on input, not product rules.
MAX_BUNDLE_BYTES: Final = 1024 * 1024
MAX_FIELDS: Final = 120
MAX_TEMPLATES: Final = 32
MAX_TEMPLATE_FIELDS: Final = 60
MAX_BLOCKS: Final = 400
MAX_INSTRUCTIONS: Final = 100
MAX_SEGMENTS: Final = 64
MAX_CHOICES: Final = 8
MAX_OPTIONS: Final = 8
MAX_ROWS: Final = 40
MAX_CELLS: Final = 8
MAX_STAGES: Final = 40
MAX_LIST_ITEMS: Final = 30
MAX_SEGMENT_TEXT: Final = 4000
MAX_TEMPLATE_VERSION: Final = 10_000
# Largest value a field may accept, by kind (a date is always YYYY-MM-DD).
MAX_VALUE: Final[Mapping[str, int]] = {"text": 300, "long_text": 4000, "list": 300}

BUNDLE_ID: Final = re.compile(r"^[a-z][a-z0-9-]{0,49}$")
VERSION: Final = re.compile(r"^[a-z0-9][a-z0-9.-]{0,49}$")
# Stable internal identifiers, independent of display codes ("EX-01"):
# renumbering a template changes its code, never its key.
TEMPLATE_KEY: Final = re.compile(r"^[a-z][a-z0-9_]{0,30}(\.[a-z][a-z0-9_]{0,30}){0,2}$")
FIELD_KEY: Final = TEMPLATE_KEY
CODE: Final = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,11}$")
CHOICE_KEY: Final = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
OPTION_VALUE: Final = re.compile(r"^[a-z][a-z0-9_]{0,29}$")
STAGE_KEY: Final = re.compile(r"^[a-z][a-z_]{0,49}$")
SHA256_HEX: Final = re.compile(r"^[0-9a-f]{64}$")

TEXT_LIMITS: Final[Mapping[str, int]] = {
    "title": 120,
    "body": 2000,
    "label": 120,
    "help": 600,
    "option": 120,
}
SUGGESTIONS: Final = ("company_name", "subject_name")


class TemplateBundleError(ValueError):
    """The bundle is refused. ``code`` is fixed; ``location`` is structural only."""

    def __init__(self, code: str, location: str = "") -> None:
        self.code = code
        self.location = location
        suffix = f" at {location}" if location else ""
        super().__init__(f"template bundle refused: {code}{suffix}")


@dataclass(frozen=True, slots=True)
class Message:
    title: str
    body: str


@dataclass(frozen=True, slots=True)
class FieldSpec:
    key: str
    label: str
    kind: FieldKind
    # Characters per value (per item for a list); None for a date.
    max_length: int | None
    # Items a list may hold; None for other kinds.
    max_items: int | None
    help: str | None
    suggest: Suggestion | None
    # Show the "keep to the facts, leave out personal details" reminder.
    reminder: bool


@dataclass(frozen=True, slots=True)
class Option:
    value: str
    label: str


@dataclass(frozen=True, slots=True)
class ChoiceSpec:
    key: str
    label: str
    help: str | None
    multiple: bool
    options: tuple[Option, ...]

    def option(self, value: str) -> Option | None:
        return next((o for o in self.options if o.value == value), None)


@dataclass(frozen=True, slots=True)
class Segment:
    kind: Literal["text", "field", "blank", "break"]
    # text: the wording; field: the field key; blank: the label of a line left
    # empty for a handwritten entry (a signature, a date); break: None.
    value: str | None


@dataclass(frozen=True, slots=True)
class Condition:
    choice: str
    values: frozenset[str]


@dataclass(frozen=True, slots=True)
class Block:
    type: BlockType
    content: tuple[Segment, ...]
    # Tables only: rows of cells of segments.
    rows: tuple[tuple[tuple[Segment, ...], ...], ...]
    when: Condition | None
    repeat: str | None


@dataclass(frozen=True, slots=True)
class Binding:
    """Where a template may be previewed in one jurisdiction."""

    stages: frozenset[str]
    # Must be definitely TRUE (unknown counts as not met).
    require: predicates.Predicate | None


@dataclass(frozen=True, slots=True)
class Template:
    key: str
    code: str
    title: str
    kind: TemplateKind
    version: int
    source_sha256: str | None
    review: Review
    jurisdictions: Mapping[str, Binding]
    instructions: tuple[Block, ...]
    choices: tuple[ChoiceSpec, ...]
    body: tuple[Block, ...]
    # The fields the template uses, in order of first use.
    fields: tuple[str, ...]

    def choice(self, key: str) -> ChoiceSpec | None:
        return next((c for c in self.choices if c.key == key), None)


@dataclass(frozen=True, slots=True)
class TemplateBundle:
    bundle_id: str
    version: str
    provenance: Provenance
    approval: Approval
    workflow_key: str
    rule_bundle_id: str
    rule_bundle_versions: frozenset[str]
    notice: Message | None
    fields: Mapping[str, FieldSpec]
    templates: tuple[Template, ...]
    # SHA-256 of the canonical content.
    digest: str
    # SHA-256 of the file as deployed (the configured pin).
    file_sha256: str

    def template(self, key: str) -> Template | None:
        return next((t for t in self.templates if t.key == key), None)


# --- parsing helpers -------------------------------------------------------------------


def _object(
    raw: object, where: str, required: set[str], optional: frozenset[str] = frozenset()
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise TemplateBundleError("expected_object", where)
    keys = set(raw)
    if not required <= keys:
        raise TemplateBundleError("missing_field", where)
    if not keys <= required | optional:
        raise TemplateBundleError("unknown_field", where)
    return raw


def _text(raw: object, where: str, limit: str) -> str:
    """Display text: trimmed, printable, bounded."""
    if (
        not isinstance(raw, str)
        or not raw.strip()
        or raw != raw.strip()
        or len(raw) > TEXT_LIMITS[limit]
        or not raw.isprintable()
    ):
        raise TemplateBundleError("invalid_text", where)
    return raw


def _optional_text(raw: object, where: str, limit: str) -> str | None:
    return None if raw is None else _text(raw, where, limit)


def _key(raw: object, pattern: re.Pattern[str], where: str) -> str:
    if not isinstance(raw, str) or not pattern.fullmatch(raw):
        raise TemplateBundleError("invalid_key", where)
    return raw


def _bool(raw: object, where: str) -> bool:
    if not isinstance(raw, bool):
        raise TemplateBundleError("expected_boolean", where)
    return raw


def _int(raw: object, where: str, low: int, high: int) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool) or not low <= raw <= high:
        raise TemplateBundleError("invalid_number", where)
    return raw


def _list(raw: object, where: str, limit: int, *, allow_empty: bool = True) -> list[object]:
    if not isinstance(raw, list) or len(raw) > limit or (not raw and not allow_empty):
        raise TemplateBundleError("invalid_list", where)
    return raw


def _keys(raw: object, pattern: re.Pattern[str], where: str, limit: int) -> tuple[str, ...]:
    values = tuple(
        _key(item, pattern, f"{where}[{i}]")
        for i, item in enumerate(_list(raw, where, limit, allow_empty=False))
    )
    if len(set(values)) != len(values):
        raise TemplateBundleError("duplicate_key", where)
    return values


def _message(raw: object, where: str) -> Message:
    data = _object(raw, where, {"title", "body"})
    return Message(
        _text(data["title"], f"{where}.title", "title"),
        _text(data["body"], f"{where}.body", "body"),
    )


def _field(raw: object, where: str) -> FieldSpec:
    data = _object(
        raw,
        where,
        {"key", "label", "kind"},
        frozenset({"max", "items", "help", "suggest", "reminder"}),
    )
    kind = data["kind"]
    if kind not in ("text", "long_text", "date", "list"):
        raise TemplateBundleError("invalid_field_kind", f"{where}.kind")
    max_length: int | None = None
    if kind == "date":
        if "max" in data:
            raise TemplateBundleError("unknown_field", f"{where}.max")
    else:
        if "max" not in data:
            raise TemplateBundleError("missing_field", f"{where}.max")
        max_length = _int(data["max"], f"{where}.max", 1, MAX_VALUE[kind])
    max_items: int | None = None
    if kind == "list":
        if "items" not in data:
            raise TemplateBundleError("missing_field", f"{where}.items")
        max_items = _int(data["items"], f"{where}.items", 1, MAX_LIST_ITEMS)
    elif "items" in data:
        raise TemplateBundleError("unknown_field", f"{where}.items")
    suggest = data.get("suggest")
    if suggest is not None and (suggest not in SUGGESTIONS or kind != "text"):
        raise TemplateBundleError("invalid_suggestion", f"{where}.suggest")
    reminder = _bool(data.get("reminder", False), f"{where}.reminder")
    if reminder and kind == "date":
        raise TemplateBundleError("invalid_reminder", f"{where}.reminder")
    return FieldSpec(
        key=_key(data["key"], FIELD_KEY, f"{where}.key"),
        label=_text(data["label"], f"{where}.label", "label"),
        kind=kind,
        max_length=max_length,
        max_items=max_items,
        help=_optional_text(data.get("help"), f"{where}.help", "help"),
        suggest=suggest,
        reminder=reminder,
    )


def _choice(raw: object, where: str) -> ChoiceSpec:
    data = _object(raw, where, {"key", "label", "multiple", "options"}, frozenset({"help"}))
    options = []
    for i, item in enumerate(
        _list(data["options"], f"{where}.options", MAX_OPTIONS, allow_empty=False)
    ):
        option = _object(item, f"{where}.options[{i}]", {"value", "label"})
        options.append(
            Option(
                _key(option["value"], OPTION_VALUE, f"{where}.options[{i}].value"),
                _text(option["label"], f"{where}.options[{i}].label", "option"),
            )
        )
    if len(options) < 2:
        raise TemplateBundleError("invalid_list", f"{where}.options")
    if len({o.value for o in options}) != len(options):
        raise TemplateBundleError("duplicate_key", f"{where}.options")
    return ChoiceSpec(
        key=_key(data["key"], CHOICE_KEY, f"{where}.key"),
        label=_text(data["label"], f"{where}.label", "label"),
        help=_optional_text(data.get("help"), f"{where}.help", "help"),
        multiple=_bool(data["multiple"], f"{where}.multiple"),
        options=tuple(options),
    )


def _segment(raw: object, where: str, *, fields_allowed: bool) -> Segment:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise TemplateBundleError("invalid_segment", where)
    ((name, value),) = raw.items()
    if name == "text":
        # Wording runs between fields: spaces at either end are significant.
        if (
            not isinstance(value, str)
            or not value
            or len(value) > MAX_SEGMENT_TEXT
            or not value.isprintable()
        ):
            raise TemplateBundleError("invalid_text", f"{where}.text")
        return Segment("text", value)
    if name == "field" and fields_allowed:
        return Segment("field", _key(value, FIELD_KEY, f"{where}.field"))
    if name == "blank" and fields_allowed:
        return Segment("blank", _text(value, f"{where}.blank", "label"))
    if name == "break":
        if value is not True:
            raise TemplateBundleError("invalid_segment", f"{where}.break")
        return Segment("break", None)
    raise TemplateBundleError("invalid_segment", where)


def _segments(
    raw: object, where: str, *, fields_allowed: bool, allow_empty: bool = False
) -> tuple[Segment, ...]:
    return tuple(
        _segment(item, f"{where}[{i}]", fields_allowed=fields_allowed)
        for i, item in enumerate(_list(raw, where, MAX_SEGMENTS, allow_empty=allow_empty))
    )


def _condition(raw: object, where: str) -> Condition:
    data = _object(raw, where, {"choice", "in"})
    choice = _key(data["choice"], CHOICE_KEY, f"{where}.choice")
    values = _keys(data["in"], OPTION_VALUE, f"{where}.in", MAX_OPTIONS)
    return Condition(choice, frozenset(values))


def _block(raw: object, where: str, *, instructions: bool) -> Block:
    if not isinstance(raw, dict):
        raise TemplateBundleError("expected_object", where)
    kind = raw.get("type")
    fields_allowed = not instructions
    if kind == "table" and not instructions:
        data = _object(raw, where, {"type", "rows"}, frozenset({"when"}))
        rows = []
        for r, row in enumerate(_list(data["rows"], f"{where}.rows", MAX_ROWS, allow_empty=False)):
            cells = _list(row, f"{where}.rows[{r}]", MAX_CELLS, allow_empty=False)
            rows.append(
                tuple(
                    _segments(
                        cell,
                        f"{where}.rows[{r}][{c}]",
                        fields_allowed=True,
                        allow_empty=True,
                    )
                    for c, cell in enumerate(cells)
                )
            )
        when = None if "when" not in data else _condition(data["when"], f"{where}.when")
        return Block("table", (), tuple(rows), when, None)
    if kind not in ("heading", "paragraph", "item"):
        raise TemplateBundleError("invalid_block_type", f"{where}.type")
    optional = frozenset() if instructions else frozenset({"when", "repeat"})
    data = _object(raw, where, {"type", "content"}, optional)
    when = None if "when" not in data else _condition(data["when"], f"{where}.when")
    repeat = None if "repeat" not in data else _key(data["repeat"], FIELD_KEY, f"{where}.repeat")
    content = _segments(data["content"], f"{where}.content", fields_allowed=fields_allowed)
    return Block(kind, content, (), when, repeat)


def _block_segments(block: Block) -> list[Segment]:
    return [*block.content, *(s for row in block.rows for cell in row for s in cell)]


def _check_template_references(
    blocks: tuple[Block, ...],
    choices: tuple[ChoiceSpec, ...],
    fields: Mapping[str, FieldSpec],
    where: str,
) -> tuple[str, ...]:
    """Fields and choices used by the body exist and fit; returns the fields in first-use order."""
    by_choice = {c.key: c for c in choices}
    used: list[str] = []
    conditioned: set[str] = set()
    for index, block in enumerate(blocks):
        at = f"{where}.body[{index}]"
        if block.when is not None:
            choice = by_choice.get(block.when.choice)
            if choice is None:
                raise TemplateBundleError("unknown_choice", f"{at}.when")
            if not block.when.values <= {o.value for o in choice.options}:
                raise TemplateBundleError("unknown_option", f"{at}.when")
            conditioned.add(choice.key)
        if block.repeat is not None:
            spec = fields.get(block.repeat)
            if spec is None or spec.kind != "list":
                raise TemplateBundleError("invalid_repeat", f"{at}.repeat")
            if not any(s.kind == "field" and s.value == block.repeat for s in block.content):
                raise TemplateBundleError("repeat_without_item", at)
            if block.repeat not in used:
                used.append(block.repeat)
        for segment in _block_segments(block):
            if segment.kind != "field" or segment.value is None:
                continue
            spec = fields.get(segment.value)
            if spec is None:
                raise TemplateBundleError("unknown_field_reference", at)
            # A list is written item by item, in its own repeat blocks only.
            if spec.kind == "list" and segment.value != block.repeat:
                raise TemplateBundleError("list_outside_repeat", at)
            if segment.value not in used:
                used.append(segment.value)
    unused = [c.key for c in choices if c.key not in conditioned]
    if unused:
        raise TemplateBundleError("unused_choice", f"{where}.choices")
    if len(used) > MAX_TEMPLATE_FIELDS:
        raise TemplateBundleError("too_many_fields", where)
    return tuple(used)


def _binding(
    raw: object, where: str, readable: frozenset[str], sensitive: frozenset[str]
) -> Binding:
    data = _object(raw, where, {"stages"}, frozenset({"require"}))
    stages = _keys(data["stages"], STAGE_KEY, f"{where}.stages", MAX_STAGES)
    require = None
    if "require" in data:
        try:
            require = predicates.parse(data["require"], f"{where}.require")
        except predicates.PredicateError as error:
            raise TemplateBundleError("invalid_condition", f"{where}.require") from error
        for fact in predicates.fact_keys(require):
            if fact in sensitive:
                raise TemplateBundleError("sensitive_answer_referenced", f"{where}.require")
            # Stage checklist answers are checked against the rule bundle later.
            if fact not in readable and not fact.startswith(f"{FACT_PREFIX}."):
                raise TemplateBundleError("unknown_answer_referenced", f"{where}.require")
    return Binding(frozenset(stages), require)


def _template(
    raw: object,
    where: str,
    fields: Mapping[str, FieldSpec],
    provenance: Provenance,
    readable: frozenset[str],
    sensitive: frozenset[str],
) -> Template:
    data = _object(
        raw,
        where,
        {
            "key",
            "code",
            "title",
            "kind",
            "version",
            "source_sha256",
            "review",
            "jurisdictions",
            "body",
        },
        frozenset({"instructions", "choices"}),
    )
    kind = data["kind"]
    if kind not in ("letter", "email", "minutes"):
        raise TemplateBundleError("invalid_template_kind", f"{where}.kind")
    review = data["review"]
    if review not in ("employer", "specialist_first"):
        raise TemplateBundleError("invalid_review", f"{where}.review")
    source = data["source_sha256"]
    if provenance == "private":
        # Every private template is traceable to the approved source document.
        if not isinstance(source, str) or not SHA256_HEX.fullmatch(source):
            raise TemplateBundleError("invalid_source_sha256", f"{where}.source_sha256")
    elif source is not None:
        raise TemplateBundleError("synthetic_with_source", f"{where}.source_sha256")
    jurisdictions_raw = data["jurisdictions"]
    if not isinstance(jurisdictions_raw, dict) or not jurisdictions_raw:
        raise TemplateBundleError("invalid_jurisdictions", f"{where}.jurisdictions")
    bindings: dict[str, Binding] = {}
    for code, binding_raw in jurisdictions_raw.items():
        if code not in JURISDICTIONS:
            raise TemplateBundleError("unsupported_jurisdiction", f"{where}.jurisdictions")
        bindings[code] = _binding(binding_raw, f"{where}.jurisdictions.{code}", readable, sensitive)
    choices = tuple(
        _choice(item, f"{where}.choices[{i}]")
        for i, item in enumerate(_list(data.get("choices", []), f"{where}.choices", MAX_CHOICES))
    )
    if len({c.key for c in choices}) != len(choices):
        raise TemplateBundleError("duplicate_key", f"{where}.choices")
    instructions = tuple(
        _block(item, f"{where}.instructions[{i}]", instructions=True)
        for i, item in enumerate(
            _list(data.get("instructions", []), f"{where}.instructions", MAX_INSTRUCTIONS)
        )
    )
    body = tuple(
        _block(item, f"{where}.body[{i}]", instructions=False)
        for i, item in enumerate(
            _list(data["body"], f"{where}.body", MAX_BLOCKS, allow_empty=False)
        )
    )
    used = _check_template_references(body, choices, fields, where)
    return Template(
        key=_key(data["key"], TEMPLATE_KEY, f"{where}.key"),
        code=_key(data["code"], CODE, f"{where}.code"),
        title=_text(data["title"], f"{where}.title", "title"),
        kind=kind,
        version=_int(data["version"], f"{where}.version", 1, MAX_TEMPLATE_VERSION),
        source_sha256=source if isinstance(source, str) else None,
        review=review,
        jurisdictions=bindings,
        instructions=instructions,
        choices=choices,
        body=body,
        fields=used,
    )


def _canonical_digest(raw: Mapping[str, object]) -> str:
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise TemplateBundleError("duplicate_json_key")
        data[key] = value
    return data


def _no_constants(name: str) -> object:
    raise TemplateBundleError("invalid_json_number")


def parse_template_bundle(content: bytes, *, file_sha256: str) -> TemplateBundle:
    """Validate a bundle's bytes against the schema and this code's workflow definitions."""
    if len(content) > MAX_BUNDLE_BYTES:
        raise TemplateBundleError("too_large")
    try:
        raw = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_no_duplicates,
            parse_constant=_no_constants,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TemplateBundleError("invalid_json") from error
    data = _object(
        raw,
        "$",
        {
            "schema",
            "bundle",
            "version",
            "provenance",
            "approval",
            "workflow",
            "rule_bundle",
            "fields",
            "templates",
        },
        frozenset({"notice"}),
    )
    if data["schema"] != SCHEMA:
        raise TemplateBundleError("unsupported_schema", "$.schema")
    provenance = data["provenance"]
    if provenance not in ("synthetic", "private"):
        raise TemplateBundleError("invalid_provenance", "$.provenance")
    approval = data["approval"]
    if approval not in ("provisional", "approved"):
        raise TemplateBundleError("invalid_approval", "$.approval")
    if provenance == "synthetic" and approval != "provisional":
        # Fictional wording is never approved content.
        raise TemplateBundleError("synthetic_approved", "$.approval")
    workflow = data["workflow"]
    if not isinstance(workflow, str):
        raise TemplateBundleError("unknown_workflow", "$.workflow")
    definition = current_definition(workflow)
    if definition is None or workflow not in PROGRESSIONS:
        raise TemplateBundleError("unknown_workflow", "$.workflow")
    notice = None if data.get("notice") is None else _message(data["notice"], "$.notice")
    if provenance == "synthetic" and notice is None:
        # Synthetic templates are always announced as such with every preview.
        raise TemplateBundleError("synthetic_without_notice", "$.notice")
    rules = _object(data["rule_bundle"], "$.rule_bundle", {"bundle", "versions"})
    rule_bundle_id = _key(rules["bundle"], BUNDLE_ID, "$.rule_bundle.bundle")
    rule_versions = _keys(rules["versions"], VERSION, "$.rule_bundle.versions", 16)

    questions = [q for s in definition.steps for q in s.questions]
    readable = frozenset(q.key for q in questions if not q.sensitive)
    sensitive = frozenset(q.key for q in questions if q.sensitive)

    fields: dict[str, FieldSpec] = {}
    for i, item in enumerate(_list(data["fields"], "$.fields", MAX_FIELDS, allow_empty=False)):
        spec = _field(item, f"$.fields[{i}]")
        if spec.key in fields:
            raise TemplateBundleError("duplicate_key", "$.fields")
        fields[spec.key] = spec
    templates = tuple(
        _template(item, f"$.templates[{i}]", fields, provenance, readable, sensitive)
        for i, item in enumerate(
            _list(data["templates"], "$.templates", MAX_TEMPLATES, allow_empty=False)
        )
    )
    if len({t.key for t in templates}) != len(templates):
        raise TemplateBundleError("duplicate_key", "$.templates")
    if len({t.code for t in templates}) != len(templates):
        raise TemplateBundleError("duplicate_code", "$.templates")
    used = {key for t in templates for key in t.fields}
    if set(fields) - used:
        raise TemplateBundleError("unused_field", "$.fields")

    return TemplateBundle(
        bundle_id=_key(data["bundle"], BUNDLE_ID, "$.bundle"),
        version=_key(data["version"], VERSION, "$.version"),
        provenance=provenance,
        approval=approval,
        workflow_key=workflow,
        rule_bundle_id=rule_bundle_id,
        rule_bundle_versions=frozenset(rule_versions),
        notice=notice,
        fields=fields,
        templates=templates,
        digest=_canonical_digest(data),
        file_sha256=file_sha256,
    )


def check_against_rules(templates: TemplateBundle, rules: RuleBundle | None) -> None:
    """The bundle fits the installed rule bundle: same workflow, known stages and answers.

    Templates are bound to the rule bundle's stages, so a template bundle never
    runs without the rules it was written for.
    """
    if rules is None:
        raise TemplateBundleError("rules_not_installed")
    if (
        rules.bundle_id != templates.rule_bundle_id
        or rules.version not in templates.rule_bundle_versions
        or rules.workflow_key != templates.workflow_key
    ):
        raise TemplateBundleError("rule_bundle_mismatch", "$.rule_bundle")
    for t_index, template in enumerate(templates.templates):
        for code, binding in template.jurisdictions.items():
            where = f"$.templates[{t_index}].jurisdictions.{code}"
            program = rules.program(code)
            if program is None:
                raise TemplateBundleError("jurisdiction_not_in_rules", where)
            stages = {s.key for p in program.pathways for s in p.stages}
            if not binding.stages <= stages:
                raise TemplateBundleError("unknown_stage", f"{where}.stages")
            if binding.require is None:
                continue
            checklist = program.checklist_items()
            for fact in predicates.fact_keys(binding.require):
                if fact.startswith(f"{FACT_PREFIX}.") and fact not in checklist:
                    raise TemplateBundleError("unknown_answer_referenced", f"{where}.require")
            if not set(predicates.stage_keys(binding.require)) <= stages:
                raise TemplateBundleError("unknown_stage_referenced", f"{where}.require")


def load_template_bundle(path: Path, expected_sha256: str, *, production: bool) -> TemplateBundle:
    """Read, verify against the pin, validate. Raises ``TemplateBundleError``; never falls back."""
    if not SHA256_HEX.fullmatch(expected_sha256):
        raise TemplateBundleError("invalid_pin")
    try:
        with path.open("rb") as handle:
            content = handle.read(MAX_BUNDLE_BYTES + 1)
    except OSError as error:
        raise TemplateBundleError("unreadable") from error
    if len(content) > MAX_BUNDLE_BYTES:
        raise TemplateBundleError("too_large")
    actual = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(actual, expected_sha256):
        raise TemplateBundleError("checksum_mismatch")
    bundle = parse_template_bundle(content, file_sha256=actual)
    if production and bundle.provenance == "synthetic":
        raise TemplateBundleError("synthetic_in_production")
    if production and bundle.approval != "approved":
        raise TemplateBundleError("provisional_in_production")
    return bundle
