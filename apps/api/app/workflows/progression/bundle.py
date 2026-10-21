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

**Conversation rules (M2-NEW-06, optional).** ``"conversation"`` holds the
deterministic rules Ask HeroOS may run on a conversation's trusted facts
before any Case exists (``app.evaluation``)::

    "conversation": {
      "facts": [{"key", "kind": "yes_no" | "count" | "choice",
                 "options": [{"value", "label"}] (choice), "max": int (count)}],
      "jurisdictions": {"<code>": {
         "rules": [rule + optional "follow_up"],
         "actions": [{"action": "<option id>", "rules": [rule + optional "follow_up"]}]}}}

``facts`` types the facts the rules read that no question of the workflow
definition owns (a definition question keeps its own options). ``rules``
are bindable to a knowledge Condition by an execution profile, never by name;
``actions`` are an employer decision's mandatory prerequisites. A rule may
compare whole numbers (``compare``) and carry a ``follow_up``:
``{"action", "when": "employer_insists"}`` (a two-state caution: stronger
only once the employer explicitly insists) or ``{"action", "when":
"condition_specific", "if": P}``. Conversation rules never read a sensitive
answer or a stage. A bundle without the section has no conversation rules.
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
from app.workflows.definition import YES_NO_NOT_SURE, Option, Question, Step, WorkflowDefinition
from app.workflows.definition import current_definition as _current_definition
from app.workflows.progression import predicates
from app.workflows.progression.spec import PROGRESSIONS, ProgressionSpec

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
# Conversation rules (M2-NEW-06): knowledge fact keys and option ids.
CONVERSATION_FACT_KEY: Final = re.compile(r"^[a-z][a-z0-9_.]{0,99}$")
ACTION_ID: Final = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,79}$")
CONVERSATION_FACT_KINDS: Final = ("yes_no", "count", "choice")
FOLLOW_UP_WHEN: Final = ("employer_insists", "condition_specific")
MAX_CONVERSATION_FACTS: Final = 60
MAX_COUNT: Final = 1_000_000
SEVERITY: Final[Mapping[str, int]] = {"warn": 1, "block": 2, "escalate": 3}


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


ConversationFactKind = Literal["yes_no", "count", "choice"]


@dataclass(frozen=True, slots=True)
class ConversationFact:
    """A fact a conversation rule reads that no definition question types."""

    key: str
    kind: ConversationFactKind
    # yes_no: Yes / No / Not sure; choice: as written; count: none.
    options: tuple[Option, ...]
    # count only: the largest value accepted as an answer.
    maximum: int | None


@dataclass(frozen=True, slots=True)
class FollowUp:
    action: Action
    when: Literal["employer_insists", "condition_specific"]
    # condition_specific only: the follow-up applies unless this is definitely false.
    trigger: predicates.Predicate | None


@dataclass(frozen=True, slots=True)
class ConversationRule:
    rule: BundleRule
    follow_up: FollowUp | None


@dataclass(frozen=True, slots=True)
class ConversationProgram:
    jurisdiction: str
    # Bindable to a knowledge Condition by an execution profile (never by name).
    rules: tuple[ConversationRule, ...]
    # An employer decision (option id) -> its mandatory prerequisites.
    actions: Mapping[str, tuple[ConversationRule, ...]]

    def rule(self, key: str) -> ConversationRule | None:
        return next((r for r in self.rules if r.rule.key == key), None)


@dataclass(frozen=True, slots=True)
class ConversationRules:
    facts: tuple[ConversationFact, ...]
    jurisdictions: Mapping[str, ConversationProgram]

    def fact(self, key: str) -> ConversationFact | None:
        return next((f for f in self.facts if f.key == key), None)


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
    # Ask HeroOS's deterministic rules (M2-NEW-06); None: the bundle has none.
    conversation: ConversationRules | None = None

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


def _rule(
    raw: object, where: str, *, comparisons: bool = False, extra: frozenset[str] = frozenset()
) -> BundleRule:
    data = _object(
        raw,
        where,
        {"key", "action", "provisional", "message"},
        frozenset({"require", "when"}) | extra,
    )
    forms = [name for name in ("require", "when") if name in data]
    if len(forms) != 1:
        raise RuleBundleError("rule_needs_require_or_when", where)
    form: Literal["require", "when"] = "require" if forms[0] == "require" else "when"
    action = data["action"]
    if action not in ("warn", "block", "escalate"):
        raise RuleBundleError("invalid_action", f"{where}.action")
    try:
        predicate = predicates.parse(data[form], f"{where}.{form}", comparisons=comparisons)
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


def _conversation_fact(raw: object, where: str, questions: frozenset[str]) -> ConversationFact:
    data = _object(raw, where, {"key", "kind"}, frozenset({"options", "max"}))
    key = _key(data["key"], CONVERSATION_FACT_KEY, f"{where}.key")
    if key in questions or key.startswith(f"{FACT_PREFIX}."):
        # A definition question keeps its own options; a checklist answer is a Case's.
        raise RuleBundleError("fact_shadows_question", f"{where}.key")
    kind = data["kind"]
    if kind not in CONVERSATION_FACT_KINDS:
        raise RuleBundleError("invalid_fact_kind", f"{where}.kind")
    options: tuple[Option, ...] = ()
    maximum: int | None = None
    if kind == "choice":
        if "options" not in data or "max" in data:
            raise RuleBundleError("invalid_fact_kind", where)
        options = _options(data["options"], f"{where}.options")
    elif kind == "yes_no":
        if "options" in data or "max" in data:
            raise RuleBundleError("invalid_fact_kind", where)
        options = YES_NO_NOT_SURE
    else:
        if "options" in data:
            raise RuleBundleError("invalid_fact_kind", where)
        raw_max = data.get("max")
        if raw_max is not None and (
            not isinstance(raw_max, int)
            or isinstance(raw_max, bool)
            or not 1 <= raw_max <= MAX_COUNT
        ):
            raise RuleBundleError("invalid_fact_kind", f"{where}.max")
        maximum = raw_max
    return ConversationFact(key, kind, options, maximum)


def _conversation_rule(raw: object, where: str) -> ConversationRule:
    rule = _rule(raw, where, comparisons=True, extra=frozenset({"follow_up"}))
    assert isinstance(raw, dict)
    if "follow_up" not in raw:
        return ConversationRule(rule, None)
    at = f"{where}.follow_up"
    data = _object(raw["follow_up"], at, {"action", "when"}, frozenset({"if"}))
    action, when = data["action"], data["when"]
    if action not in SEVERITY or SEVERITY[str(action)] <= SEVERITY[rule.action]:
        # A follow-up only ever makes the rule stronger.
        raise RuleBundleError("invalid_follow_up", f"{at}.action")
    if when not in FOLLOW_UP_WHEN or (("if" in data) != (when == "condition_specific")):
        raise RuleBundleError("invalid_follow_up", f"{at}.when")
    trigger = None
    if "if" in data:
        try:
            trigger = predicates.parse(data["if"], f"{at}.if", comparisons=True)
        except predicates.PredicateError as error:
            raise RuleBundleError("invalid_condition", f"{at}.if") from error
    return ConversationRule(rule, FollowUp(action, when, trigger))  # type: ignore[arg-type]  # checked


def _conversation(
    raw: object, readable: frozenset[str], sensitive: frozenset[str]
) -> ConversationRules:
    """The optional conversation section: typed facts and per-jurisdiction rules."""
    where = "$.conversation"
    data = _object(raw, where, {"facts", "jurisdictions"})
    facts = tuple(
        _conversation_fact(item, f"{where}.facts[{i}]", readable | sensitive)
        for i, item in enumerate(_list(data["facts"], f"{where}.facts", MAX_CONVERSATION_FACTS))
    )
    if len({f.key for f in facts}) != len(facts):
        raise RuleBundleError("duplicate_key", f"{where}.facts")
    declared = {f.key: f for f in facts}
    numeric = frozenset(f.key for f in facts if f.kind == "count")
    jurisdictions_raw = data["jurisdictions"]
    if not isinstance(jurisdictions_raw, dict) or not jurisdictions_raw:
        raise RuleBundleError("invalid_jurisdictions", f"{where}.jurisdictions")
    programs: dict[str, ConversationProgram] = {}
    for code, program_raw in jurisdictions_raw.items():
        if code not in JURISDICTIONS:
            raise RuleBundleError("unsupported_jurisdiction", f"{where}.jurisdictions")
        at = f"{where}.jurisdictions.{code}"
        program = _object(program_raw, at, {"rules", "actions"})
        rules = tuple(
            _conversation_rule(item, f"{at}.rules[{i}]")
            for i, item in enumerate(_list(program["rules"], f"{at}.rules", MAX_RULES))
        )
        actions: dict[str, tuple[ConversationRule, ...]] = {}
        for i, entry in enumerate(_list(program["actions"], f"{at}.actions", MAX_RULES)):
            entry_at = f"{at}.actions[{i}]"
            entry_data = _object(entry, entry_at, {"action", "rules"})
            action = _key(entry_data["action"], ACTION_ID, f"{entry_at}.action")
            if action in actions:
                raise RuleBundleError("duplicate_key", entry_at)
            actions[action] = tuple(
                _conversation_rule(item, f"{entry_at}.rules[{j}]")
                for j, item in enumerate(
                    _list(entry_data["rules"], f"{entry_at}.rules", MAX_RULES, allow_empty=False)
                )
            )
            if any(r.follow_up is not None for r in actions[action]):
                # A follow-up (a two-state caution) comes from an approved Condition only.
                raise RuleBundleError("follow_up_on_prerequisite", entry_at)
        everything = [*rules, *(r for group in actions.values() for r in group)]
        keys = [r.rule.key for r in everything]
        if len(set(keys)) != len(keys):
            raise RuleBundleError("duplicate_rule", at)
        for index, item in enumerate(everything):
            triggers = [item.rule.trigger] + (
                [item.follow_up.trigger]
                if item.follow_up is not None and item.follow_up.trigger is not None
                else []
            )
            for trigger in triggers:
                if predicates.stage_keys(trigger):
                    raise RuleBundleError("stage_referenced_in_conversation", f"{at}[{index}]")
                for fact in predicates.fact_keys(trigger):
                    if fact in sensitive:
                        raise RuleBundleError("sensitive_answer_referenced", f"{at}[{index}]")
                    if fact not in readable and fact not in declared:
                        raise RuleBundleError("unknown_answer_referenced", f"{at}[{index}]")
                if not set(predicates.compared_keys(trigger)) <= numeric:
                    raise RuleBundleError("comparison_not_numeric", f"{at}[{index}]")
        programs[code] = ConversationProgram(code, rules, actions)
    return ConversationRules(facts, programs)


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


def parse_bundle(
    content: bytes,
    *,
    file_sha256: str,
    definition: WorkflowDefinition | None = None,
    spec: ProgressionSpec | None = None,
) -> RuleBundle:
    """Validate a bundle's bytes against the schema and this code's definitions.

    ``definition`` and ``spec`` replace the registered ones for the bundle's
    workflow (a workflow this code doesn't register, e.g. a test's fictional
    one); by default the current registered definition and spec are used.
    """
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
        frozenset({"serves_versions", "notice", "conversation"}),
    )
    if data["schema"] != SCHEMA:
        raise RuleBundleError("unsupported_schema", "$.schema")
    provenance = data["provenance"]
    if provenance not in ("synthetic", "private"):
        raise RuleBundleError("invalid_provenance", "$.provenance")
    workflow = data["workflow"]
    if not isinstance(workflow, str):
        raise RuleBundleError("unknown_workflow", "$.workflow")
    spec = (
        spec if spec is not None and spec.workflow_key == workflow else PROGRESSIONS.get(workflow)
    )
    definition = (
        definition
        if definition is not None and definition.key == workflow
        else _current_definition(workflow)
    )
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

    conversation = (
        None
        if data.get("conversation") is None
        else _conversation(data["conversation"], readable, sensitive)
    )
    if conversation is not None:
        for code, rules_program in conversation.jurisdictions.items():
            stage_rules = {
                r.key
                for p in programs.get(code, JurisdictionProgram(code, ())).pathways
                for rules in [p.select_rules, *(s.start_rules for s in p.stages),
                              *(s.complete_rules for s in p.stages)]
                for r in rules
            }  # fmt: skip
            own = {r.rule.key for r in rules_program.rules} | {
                r.rule.key for group in rules_program.actions.values() for r in group
            }
            if stage_rules & own:
                raise RuleBundleError("duplicate_rule", f"$.conversation.jurisdictions.{code}")

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
        conversation=conversation,
    )


def load_bundle(
    path: Path,
    expected_sha256: str,
    *,
    production: bool,
    definition: WorkflowDefinition | None = None,
    spec: ProgressionSpec | None = None,
) -> RuleBundle:
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
    bundle = parse_bundle(content, file_sha256=actual, definition=definition, spec=spec)
    if production and bundle.provenance == "synthetic":
        raise RuleBundleError("synthetic_in_production")
    return bundle
