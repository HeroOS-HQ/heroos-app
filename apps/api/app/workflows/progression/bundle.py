"""Private rule bundles: schema, strict validation and loading (M2-03).

A rule bundle is a small, versioned, declarative JSON document holding the
business-rule content the generic progression engine runs: per jurisdiction,
the stages of each pathway, their order, their checklists, the rules that
govern starting and completing them, and the customer wording. The real
(``private``) bundle is proprietary and never lives in this repository; a
fictional ``synthetic`` bundle tests the engine.

Loading contract (``load_bundle``), all fail-closed:

- the backend reads one file from server-side storage, once, at startup; the
  browser never receives the bundle (only the API's per-Case answers);
- the file's SHA-256 must equal the configured pin, so an outdated or swapped
  file is refused instead of silently used;
- the JSON must match this schema exactly: unknown or missing fields, an
  unknown schema version, duplicate keys, cycles, unreachable stages, a rule
  reading an unknown or sensitive answer, or a bundle for a definition version
  this code doesn't serve are all refused;
- a synthetic bundle is refused in production.

Errors carry a fixed code and a structural location (indexes, never content).
Rules are data: there is no expression language and no ``eval``.

Schema ``heroos.rule-bundle/1``::

    {"schema", "bundle", "version", "provenance": "synthetic" | "private",
     "workflow", "definition_versions": [int], "serves_versions": [str],
     "notice": {"title", "body"} | null,
     "jurisdictions": {"<code>": {"pathways": [
        {"pathway", "entry": [stage], "select_rules": [rule], "stages": [
           {"key", "title", "summary", "optional", "terminal", "next": [stage],
            "checklist": [{"item", "prompt", "label", "help", "options"}],
            "start_rules": [rule], "complete_rules": [rule]}]}]}}}

A rule is ``{"key", "action": "warn" | "block" | "escalate", "require" | "when",
"provisional", "message": {"title", "body"}}``. ``require: P`` fires unless P
is definitely true; ``when: P`` fires unless P is definitely false. Either way
an unknown input fires the rule: missing information never lets a transition
through.
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
from app.workflows.definition import YES_NO_NOT_SURE, Option, Question, Step
from app.workflows.definition import current_definition as _current_definition
from app.workflows.progression import predicates
from app.workflows.progression.spec import PROGRESSIONS

SCHEMA: Final = "heroos.rule-bundle/1"
Provenance = Literal["synthetic", "private"]
Action = Literal["warn", "block", "escalate"]

# A bound on input, not a product rule.
MAX_BUNDLE_BYTES: Final = 1024 * 1024

BUNDLE_ID: Final = re.compile(r"^[a-z][a-z0-9-]{0,49}$")
# Same vocabulary as the stored rule-set versions (workflow_evaluations).
VERSION: Final = re.compile(r"^[a-z0-9][a-z0-9.-]{0,49}$")
# Stage keys are also step keys (path segments, ``workflow_submissions.step_key``).
STAGE_KEY: Final = re.compile(r"^[a-z][a-z_]{0,49}$")
ITEM_KEY: Final = re.compile(r"^[a-z][a-z_]{0,39}$")
RULE_KEY: Final = re.compile(r"^[a-z][a-z_]{0,59}$")
OPTION_VALUE: Final = re.compile(r"^[a-z][a-z_]{0,29}$")
SHA256_HEX: Final = re.compile(r"^[0-9a-f]{64}$")
# Checklist answers are stored as case facts under this prefix.
FACT_PREFIX: Final = "progress"
MAX_FACT_KEY: Final = 100

TEXT_LIMITS: Final[Mapping[str, int]] = {
    "title": 120,
    "summary": 1200,
    "body": 2000,
    "prompt": 300,
    "label": 120,
    "help": 600,
    "option": 120,
}
MAX_STAGES: Final = 40
MAX_CHECKLIST: Final = 20
MAX_RULES: Final = 40
MAX_OPTIONS: Final = 8


class RuleBundleError(ValueError):
    """The bundle is refused. ``code`` is fixed; ``location`` is structural only."""

    def __init__(self, code: str, location: str = "") -> None:
        self.code = code
        self.location = location
        suffix = f" at {location}" if location else ""
        super().__init__(f"rule bundle refused: {code}{suffix}")


@dataclass(frozen=True, slots=True)
class Message:
    title: str
    body: str


@dataclass(frozen=True, slots=True)
class BundleRule:
    key: str
    action: Action
    # The rule fires unless this is definitely FALSE (``require`` is negated).
    trigger: predicates.Predicate
    # "require" or "when", as written (kept for the canonical digest).
    form: Literal["require", "when"]
    # Content still under review: shown as provisional, never as approved.
    provisional: bool
    message: Message


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    item: str
    # Stored as a case fact under this key.
    fact_key: str
    prompt: str
    label: str
    help: str | None
    options: tuple[Option, ...]


@dataclass(frozen=True, slots=True)
class Stage:
    key: str
    pathway: str
    title: str
    summary: str
    optional: bool
    terminal: bool
    next: tuple[str, ...]
    checklist: tuple[ChecklistItem, ...]
    start_rules: tuple[BundleRule, ...]
    complete_rules: tuple[BundleRule, ...]

    def checklist_step(self) -> Step:
        """The checklist as a step the answers route can validate and save."""
        return Step(
            key=self.key,
            title=self.title,
            intro=self.summary,
            questions=tuple(
                Question(
                    key=item.fact_key,
                    kind="choice",
                    prompt=item.prompt,
                    label=item.label,
                    help=item.help,
                    options=item.options,
                )
                for item in self.checklist
            ),
        )


@dataclass(frozen=True, slots=True)
class PathwayProgram:
    pathway: str
    entry: tuple[str, ...]
    select_rules: tuple[BundleRule, ...]
    stages: tuple[Stage, ...]


@dataclass(frozen=True, slots=True)
class JurisdictionProgram:
    jurisdiction: str
    pathways: tuple[PathwayProgram, ...]

    def pathway(self, key: str) -> PathwayProgram | None:
        return next((p for p in self.pathways if p.pathway == key), None)

    def stage(self, key: str) -> Stage | None:
        return next((s for p in self.pathways for s in p.stages if s.key == key), None)

    def checklist_items(self) -> dict[str, ChecklistItem]:
        return {i.fact_key: i for p in self.pathways for s in p.stages for i in s.checklist}


@dataclass(frozen=True, slots=True)
class RuleBundle:
    bundle_id: str
    version: str
    provenance: Provenance
    workflow_key: str
    definition_versions: frozenset[int]
    # Earlier bundle versions whose Cases this version may continue.
    serves_versions: frozenset[str]
    notice: Message | None
    jurisdictions: Mapping[str, JurisdictionProgram]
    # SHA-256 of the canonical content (stored with every progress event).
    digest: str
    # SHA-256 of the file as deployed (the configured pin).
    file_sha256: str

    def program(self, jurisdiction: str | None) -> JurisdictionProgram | None:
        return None if jurisdiction is None else self.jurisdictions.get(jurisdiction)

    def serves(self, version: str) -> bool:
        return version == self.version or version in self.serves_versions


# --- parsing helpers -------------------------------------------------------------------


def _object(
    raw: object, where: str, required: set[str], optional: frozenset[str] = frozenset()
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise RuleBundleError("expected_object", where)
    keys = set(raw)
    if not required <= keys:
        raise RuleBundleError("missing_field", where)
    if not keys <= required | optional:
        raise RuleBundleError("unknown_field", where)
    return raw


def _text(raw: object, where: str, limit: str, *, optional: bool = False) -> str | None:
    if raw is None and optional:
        return None
    if (
        not isinstance(raw, str)
        or not raw.strip()
        or raw != raw.strip()
        or len(raw) > TEXT_LIMITS[limit]
        or any(not c.isprintable() for c in raw)
    ):
        raise RuleBundleError("invalid_text", where)
    return raw


def _required_text(raw: object, where: str, limit: str) -> str:
    text = _text(raw, where, limit)
    assert text is not None
    return text


def _key(raw: object, pattern: re.Pattern[str], where: str) -> str:
    if not isinstance(raw, str) or not pattern.fullmatch(raw):
        raise RuleBundleError("invalid_key", where)
    return raw


def _bool(raw: object, where: str) -> bool:
    if not isinstance(raw, bool):
        raise RuleBundleError("expected_boolean", where)
    return raw


def _list(raw: object, where: str, limit: int, *, allow_empty: bool = True) -> list[object]:
    if not isinstance(raw, list) or len(raw) > limit or (not raw and not allow_empty):
        raise RuleBundleError("invalid_list", where)
    return raw


def _keys(raw: object, pattern: re.Pattern[str], where: str, limit: int) -> tuple[str, ...]:
    values = tuple(
        _key(item, pattern, f"{where}[{i}]") for i, item in enumerate(_list(raw, where, limit))
    )
    if len(set(values)) != len(values):
        raise RuleBundleError("duplicate_key", where)
    return values


def _message(raw: object, where: str) -> Message:
    data = _object(raw, where, {"title", "body"})
    return Message(
        _required_text(data["title"], f"{where}.title", "title"),
        _required_text(data["body"], f"{where}.body", "body"),
    )


def _rule(raw: object, where: str) -> BundleRule:
    data = _object(
        raw, where, {"key", "action", "provisional", "message"}, frozenset({"require", "when"})
    )
    forms = [name for name in ("require", "when") if name in data]
    if len(forms) != 1:
        raise RuleBundleError("rule_needs_require_or_when", where)
    form: Literal["require", "when"] = "require" if forms[0] == "require" else "when"
    action = data["action"]
    if action not in ("warn", "block", "escalate"):
        raise RuleBundleError("invalid_action", f"{where}.action")
    try:
        predicate = predicates.parse(data[form], f"{where}.{form}")
    except predicates.PredicateError as error:
        raise RuleBundleError("invalid_condition", f"{where}.{form}") from error
    trigger = predicates.Not(predicate) if form == "require" else predicate
    return BundleRule(
        key=_key(data["key"], RULE_KEY, f"{where}.key"),
        action=action,
        trigger=trigger,
        form=form,
        provisional=_bool(data["provisional"], f"{where}.provisional"),
        message=_message(data["message"], f"{where}.message"),
    )


def _rules(raw: object, where: str) -> tuple[BundleRule, ...]:
    return tuple(
        _rule(item, f"{where}[{i}]") for i, item in enumerate(_list(raw, where, MAX_RULES))
    )


def _options(raw: object, where: str) -> tuple[Option, ...]:
    if raw is None:
        return YES_NO_NOT_SURE
    options = []
    for i, item in enumerate(_list(raw, where, MAX_OPTIONS, allow_empty=False)):
        data = _object(item, f"{where}[{i}]", {"value", "label"})
        options.append(
            Option(
                _key(data["value"], OPTION_VALUE, f"{where}[{i}].value"),
                _required_text(data["label"], f"{where}[{i}].label", "option"),
            )
        )
    if len({o.value for o in options}) != len(options):
        raise RuleBundleError("duplicate_key", where)
    return tuple(options)


def _checklist(raw: object, stage: str, where: str) -> tuple[ChecklistItem, ...]:
    items = []
    for i, entry in enumerate(_list(raw, where, MAX_CHECKLIST)):
        at = f"{where}[{i}]"
        data = _object(entry, at, {"item", "prompt", "label"}, frozenset({"help", "options"}))
        item = _key(data["item"], ITEM_KEY, f"{at}.item")
        fact_key = f"{FACT_PREFIX}.{stage}.{item}"
        if len(fact_key) > MAX_FACT_KEY:
            raise RuleBundleError("key_too_long", f"{at}.item")
        items.append(
            ChecklistItem(
                item=item,
                fact_key=fact_key,
                prompt=_required_text(data["prompt"], f"{at}.prompt", "prompt"),
                label=_required_text(data["label"], f"{at}.label", "label"),
                help=_text(data.get("help"), f"{at}.help", "help", optional=True),
                options=_options(data.get("options"), f"{at}.options"),
            )
        )
    if len({i.item for i in items}) != len(items):
        raise RuleBundleError("duplicate_key", where)
    return tuple(items)


def _stage(raw: object, pathway: str, where: str) -> Stage:
    data = _object(
        raw,
        where,
        {"key", "title", "summary", "optional", "terminal", "next"},
        frozenset({"checklist", "start_rules", "complete_rules"}),
    )
    key = _key(data["key"], STAGE_KEY, f"{where}.key")
    return Stage(
        key=key,
        pathway=pathway,
        title=_required_text(data["title"], f"{where}.title", "title"),
        summary=_required_text(data["summary"], f"{where}.summary", "summary"),
        optional=_bool(data["optional"], f"{where}.optional"),
        terminal=_bool(data["terminal"], f"{where}.terminal"),
        next=_keys(data["next"], STAGE_KEY, f"{where}.next", MAX_STAGES),
        checklist=_checklist(data.get("checklist", []), key, f"{where}.checklist"),
        start_rules=_rules(data.get("start_rules", []), f"{where}.start_rules"),
        complete_rules=_rules(data.get("complete_rules", []), f"{where}.complete_rules"),
    )


def _check_graph(program: PathwayProgram, where: str) -> None:
    """Entry and successors name stages of this pathway; acyclic; all reachable."""
    stages = {s.key: s for s in program.stages}
    if not program.entry or not set(program.entry) <= set(stages):
        raise RuleBundleError("invalid_entry", f"{where}.entry")
    for index, stage in enumerate(program.stages):
        if not set(stage.next) <= set(stages) or stage.key in stage.next:
            raise RuleBundleError("invalid_next", f"{where}.stages[{index}].next")
        if stage.terminal and stage.next:
            raise RuleBundleError("terminal_with_next", f"{where}.stages[{index}]")
    # Kahn's algorithm: every stage must be removable (no cycle).
    incoming = {key: 0 for key in stages}
    for stage in program.stages:
        for successor in stage.next:
            incoming[successor] += 1
    queue = [key for key, count in incoming.items() if count == 0]
    seen = 0
    while queue:
        key = queue.pop()
        seen += 1
        for successor in stages[key].next:
            incoming[successor] -= 1
            if incoming[successor] == 0:
                queue.append(successor)
    if seen != len(stages):
        raise RuleBundleError("stage_cycle", where)
    reachable: set[str] = set()
    frontier = list(program.entry)
    while frontier:
        key = frontier.pop()
        if key not in reachable:
            reachable.add(key)
            frontier += stages[key].next
    if reachable != set(stages):
        raise RuleBundleError("unreachable_stage", where)


def _check_references(
    program: JurisdictionProgram, where: str, readable: frozenset[str], sensitive: frozenset[str]
) -> None:
    """Rules read only known, non-sensitive answers and stages of this program."""
    checklist = program.checklist_items()
    stages = {s.key for p in program.pathways for s in p.stages}
    keys: set[str] = set()
    for p_index, pathway in enumerate(program.pathways):
        groups: list[tuple[str, tuple[BundleRule, ...], frozenset[str]]] = [
            (f"{where}.pathways[{p_index}].select_rules", pathway.select_rules, frozenset())
        ]
        for s_index, stage in enumerate(pathway.stages):
            at = f"{where}.pathways[{p_index}].stages[{s_index}]"
            own = frozenset(i.fact_key for i in stage.checklist)
            # A stage's own checklist is answered only once it has started.
            groups.append((f"{at}.start_rules", stage.start_rules, own))
            groups.append((f"{at}.complete_rules", stage.complete_rules, frozenset()))
        for location, rules, refused in groups:
            for r_index, rule in enumerate(rules):
                at = f"{location}[{r_index}]"
                if rule.key in keys:
                    raise RuleBundleError("duplicate_rule", at)
                keys.add(rule.key)
                for fact in predicates.fact_keys(rule.trigger):
                    if fact in sensitive:
                        raise RuleBundleError("sensitive_answer_referenced", at)
                    if fact in refused or (fact not in readable and fact not in checklist):
                        raise RuleBundleError("unknown_answer_referenced", at)
                if not set(predicates.stage_keys(rule.trigger)) <= stages:
                    raise RuleBundleError("unknown_stage_referenced", at)


def _canonical_digest(raw: Mapping[str, object]) -> str:
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise RuleBundleError("duplicate_json_key")
        data[key] = value
    return data


def _no_constants(name: str) -> object:
    raise RuleBundleError("invalid_json_number")


def parse_bundle(content: bytes, *, file_sha256: str) -> RuleBundle:
    """Validate a bundle's bytes against the schema and this code's definitions."""
    if len(content) > MAX_BUNDLE_BYTES:
        raise RuleBundleError("too_large")
    try:
        raw = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_no_duplicates,
            parse_constant=_no_constants,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuleBundleError("invalid_json") from error
    data = _object(
        raw,
        "$",
        {
            "schema",
            "bundle",
            "version",
            "provenance",
            "workflow",
            "definition_versions",
            "jurisdictions",
        },
        frozenset({"serves_versions", "notice"}),
    )
    if data["schema"] != SCHEMA:
        raise RuleBundleError("unsupported_schema", "$.schema")
    provenance = data["provenance"]
    if provenance not in ("synthetic", "private"):
        raise RuleBundleError("invalid_provenance", "$.provenance")
    workflow = data["workflow"]
    if not isinstance(workflow, str):
        raise RuleBundleError("unknown_workflow", "$.workflow")
    spec = PROGRESSIONS.get(workflow)
    definition = _current_definition(workflow)
    if spec is None or definition is None:
        raise RuleBundleError("unknown_workflow", "$.workflow")
    versions = _list(data["definition_versions"], "$.definition_versions", 16, allow_empty=False)
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 1 for v in versions):
        raise RuleBundleError("invalid_definition_versions", "$.definition_versions")
    # No silent use of rules written for another definition of the questions.
    if definition.version not in versions:
        raise RuleBundleError("definition_version_unsupported", "$.definition_versions")
    serves = _keys(data.get("serves_versions", []), VERSION, "$.serves_versions", 16)
    version = _key(data["version"], VERSION, "$.version")
    notice = None if data.get("notice") is None else _message(data["notice"], "$.notice")
    if provenance == "synthetic" and notice is None:
        # Synthetic rules are always announced as such on every Case they serve.
        raise RuleBundleError("synthetic_without_notice", "$.notice")

    questions = [q for s in definition.steps for q in s.questions]
    readable = frozenset(q.key for q in questions if not q.sensitive)
    sensitive = frozenset(q.key for q in questions if q.sensitive)
    step_keys = {s.key for s in definition.steps}
    unlocking = {p.key for p in spec.pathways if p.unlocks_stages}

    jurisdictions_raw = data["jurisdictions"]
    if not isinstance(jurisdictions_raw, dict) or not jurisdictions_raw:
        raise RuleBundleError("invalid_jurisdictions", "$.jurisdictions")
    programs: dict[str, JurisdictionProgram] = {}
    for code, program_raw in jurisdictions_raw.items():
        where = f"$.jurisdictions.{code}" if code in JURISDICTIONS else "$.jurisdictions"
        if code not in JURISDICTIONS:
            raise RuleBundleError("unsupported_jurisdiction", where)
        program_data = _object(program_raw, where, {"pathways"})
        pathways: list[PathwayProgram] = []
        for p_index, pathway_raw in enumerate(
            _list(program_data["pathways"], f"{where}.pathways", len(spec.pathways))
        ):
            at = f"{where}.pathways[{p_index}]"
            pathway_data = _object(
                pathway_raw, at, {"pathway", "entry", "stages"}, frozenset({"select_rules"})
            )
            pathway = pathway_data["pathway"]
            if pathway not in unlocking:
                # Unknown, or a pathway that never unlocks stages (undetermined).
                raise RuleBundleError("invalid_pathway", f"{at}.pathway")
            stages = tuple(
                _stage(stage_raw, pathway, f"{at}.stages[{s_index}]")
                for s_index, stage_raw in enumerate(
                    _list(pathway_data["stages"], f"{at}.stages", MAX_STAGES, allow_empty=False)
                )
            )
            program = PathwayProgram(
                pathway=pathway,
                entry=_keys(pathway_data["entry"], STAGE_KEY, f"{at}.entry", MAX_STAGES),
                select_rules=_rules(pathway_data.get("select_rules", []), f"{at}.select_rules"),
                stages=stages,
            )
            _check_graph(program, at)
            pathways.append(program)
        if len({p.pathway for p in pathways}) != len(pathways):
            raise RuleBundleError("duplicate_pathway", f"{where}.pathways")
        stage_list = [s.key for p in pathways for s in p.stages]
        if len(set(stage_list)) != len(stage_list):
            raise RuleBundleError("duplicate_stage", where)
        if set(stage_list) & step_keys:
            raise RuleBundleError("stage_shadows_step", where)
        jurisdiction_program = JurisdictionProgram(code, tuple(pathways))
        _check_references(jurisdiction_program, where, readable, sensitive)
        programs[code] = jurisdiction_program

    return RuleBundle(
        bundle_id=_key(data["bundle"], BUNDLE_ID, "$.bundle"),
        version=version,
        provenance=provenance,
        workflow_key=workflow,
        definition_versions=frozenset(versions),  # type: ignore[arg-type]  # ints, checked above
        serves_versions=frozenset(serves),
        notice=notice,
        jurisdictions=programs,
        digest=_canonical_digest(data),
        file_sha256=file_sha256,
    )


def load_bundle(path: Path, expected_sha256: str, *, production: bool) -> RuleBundle:
    """Read, verify against the pin, validate. Raises ``RuleBundleError``; never falls back."""
    if not SHA256_HEX.fullmatch(expected_sha256):
        raise RuleBundleError("invalid_pin")
    try:
        with path.open("rb") as handle:
            content = handle.read(MAX_BUNDLE_BYTES + 1)
    except OSError as error:
        raise RuleBundleError("unreadable") from error
    if len(content) > MAX_BUNDLE_BYTES:
        raise RuleBundleError("too_large")
    actual = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(actual, expected_sha256):
        raise RuleBundleError("checksum_mismatch")
    bundle = parse_bundle(content, file_sha256=actual)
    if production and bundle.provenance == "synthetic":
        raise RuleBundleError("synthetic_in_production")
    return bundle
