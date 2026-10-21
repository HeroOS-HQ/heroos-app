"""One immutable, version-compatible set of execution artifacts, built once and used per turn.

``build_snapshot`` takes the installed artifacts (the approved knowledge, the
execution profile, the rule bundles and the workflow definitions) and checks,
per workflow, that the profile approves exactly them together: the knowledge
runtime digest, the definition version, the rule bundle's id, version and
content digest, every executor's identity and every explicit binding. Then it
builds immutable indexes (Conditions, options, facts, bound rules, coverage)
so a founder turn never scans the library.

Anything that doesn't match makes that workflow's deterministic evaluation
**unavailable** (``incompatible_versions``, ``rule_bundle_missing``,
``unsupported_executor``...), with fixed codes for the log. Nothing falls back
to stale rules, and nothing is guessed: a Condition is executable only through
an explicit binding the profile declares and this code verifies.

``ExecutionRuntime`` holds the current snapshot. A founder turn takes it once
(``current()``) and uses only it, so no turn ever mixes two versions even if a
new snapshot is installed meanwhile.

**Execution categories** (``Category``), exactly one per Condition:

- ``executable``: an explicit, compatible binding to an executor's rule;
- ``guard_only``: a server-owned rule already represents it whatever the
  facts: the jurisdiction gate (the global routing precondition), or the
  approved availability of every decision it is linked to (a Condition that
  escalates a decision HeroOS already routes to specialist review);
- ``question_only``: it names what matters, but nothing executable can say it
  fired: it shapes questions and keeps a step it guards from counting as clear;
- ``not_enforced``: the runtime says it never executes;
- ``quarantined``: the runtime withholds it.
"""

import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Final, Literal, Protocol

from app.evaluation.model import Availability, Category, Note, Provenance
from app.evaluation.profile import (
    Binding,
    CoveredAction,
    ExecutionProfile,
    ExecutorRef,
    WorkflowProfile,
)
from app.knowledge.bundle import Condition, Fact, KnowledgeBundle, Option
from app.workflows import conditions as intake_rules
from app.workflows.conditions import RULESETS, RuleSet, Tri
from app.workflows.definition import (
    NOT_SURE,
    WORKFLOWS,
    YES_NO_NOT_SURE,
    OptionsFrom,
    WorkflowDefinition,
)
from app.workflows.definition import Option as Choice
from app.workflows.progression import predicates
from app.workflows.progression.bundle import ConversationRule, RuleBundle

logger = logging.getLogger(__name__)

Answers = Mapping[str, object]
FactKind = Literal["yes_no", "choice", "count", "date", "blueprint"]
SEVERITY: Final[Mapping[str, int]] = {
    "none": 0, "warn": 1, "block": 2, "escalate": 3,
}  # fmt: skip
AVAILABILITY_STRENGTH: Final[Mapping[str, int]] = {
    "supported": 0, "not_available": 2, "review_required": 3,
}  # fmt: skip
# The Blueprint field the jurisdiction gate reads (app.knowledge.context).
JURISDICTION_FIELD: Final = "jurisdiction.employment_jurisdiction"
_YES_NO: Final = tuple(o.value for o in YES_NO_NOT_SURE)


@dataclass(frozen=True, slots=True)
class FactSchema:
    """How a knowledge fact may hold a canonical, engine-trusted value."""

    key: str
    label: str
    kind: FactKind
    # yes_no and choice: the definition's (or the rule bundle's) options.
    options: tuple[Choice, ...] = ()
    maximum: int | None = None
    # The definition question the value is also known by (a rule may read either key).
    question: str | None = None
    # blueprint: the CompanyBlueprintContext field.
    blueprint: str | None = None

    def valid(self, value: object) -> bool:
        """A canonical value of this schema (what a continuation may carry)."""
        if self.kind in ("yes_no", "choice"):
            return isinstance(value, str) and value in {o.value for o in self.options}
        if self.kind == "count":
            return (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 <= value <= (self.maximum if self.maximum is not None else 1_000_000)
            )
        if self.kind == "date":
            return isinstance(value, str) and (value == NOT_SURE or _iso_date(value))
        return False


def _iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return len(value) == 10


@dataclass(frozen=True, slots=True)
class BoundRule:
    """A rule an executor bound for one jurisdiction: what it reads and how it decides."""

    key: str
    executor: str
    action: str
    follow_up_action: str | None
    follow_up_when: str | None
    provisional: bool
    # The rule's own approved wording (rule bundle); None for an intake rule.
    note: Note | None
    # The knowledge fact keys it reads.
    reads: tuple[str, ...]
    truth: Callable[[Answers], Tri] = field(compare=False)
    unknown: Callable[[Answers], tuple[str, ...]] = field(compare=False)
    follow_up_truth: Callable[[Answers], Tri] | None = field(default=None, compare=False)


class RuleExecutor(Protocol):
    """Binds a profile's rule key to something that decides on canonical answers."""

    name: str

    def matches(self, ref: ExecutorRef, workflow: str, rule_bundle: RuleBundle | None) -> bool:
        """The installed executor is the one the profile was approved with."""
        ...

    def bind(
        self, rule: str, jurisdiction: str, workflow: str, rule_bundle: RuleBundle | None
    ) -> "BoundRule | None":
        """The rule for this jurisdiction (keys as the rule reads them), or None."""
        ...


def _intake_unknown(predicate: intake_rules.Predicate, answers: Answers) -> tuple[str, ...]:
    if isinstance(predicate, intake_rules.AnswerIn):
        value = answers.get(predicate.key)
        return (predicate.key,) if value is None or value in predicate.unknown else ()
    keys: list[str] = []
    for term in predicate.terms:
        keys += [k for k in _intake_unknown(term, answers) if k not in keys]
    return tuple(keys)


class IntakeExecutor:
    """The public M2-02 intake rules (``app.workflows.conditions``), pinned by version and digest.

    Only rules with a typed predicate can run on a conversation: the routing
    rule reads a Case's persisted confirmation, which a conversation doesn't
    have; the jurisdiction gate represents it instead.
    """

    name = "intake"

    def __init__(self, rulesets: Mapping[str, RuleSet]) -> None:
        self._rulesets = rulesets

    def matches(self, ref: ExecutorRef, workflow: str, rule_bundle: RuleBundle | None) -> bool:
        ruleset = self._rulesets.get(workflow)
        return ruleset is not None and (ref.version, ref.digest) == (
            ruleset.version,
            ruleset.digest,
        )

    def bind(
        self, rule: str, jurisdiction: str, workflow: str, rule_bundle: RuleBundle | None
    ) -> BoundRule | None:
        ruleset = self._rulesets.get(workflow)
        found = None if ruleset is None else next((r for r in ruleset.rules if r.key == rule), None)
        if found is None or found.predicate is None or not found.enforced:
            return None
        if not found.applies_to(jurisdiction):
            return None
        predicate = found.predicate
        return BoundRule(
            key=found.key,
            executor=self.name,
            action=found.action,
            follow_up_action=None,
            follow_up_when=None,
            provisional=found.provisional,
            note=None,
            reads=intake_rules.predicate_keys(predicate),
            truth=lambda answers: intake_rules.evaluate(predicate, answers),
            unknown=lambda answers: _intake_unknown(predicate, answers),
        )


def bound_conversation_rule(item: ConversationRule, executor: str) -> BoundRule:
    rule, follow_up = item.rule, item.follow_up
    trigger = rule.trigger
    follow_trigger = None if follow_up is None else follow_up.trigger

    def context(answers: Answers) -> predicates.Context:
        return predicates.Context(answers, frozenset())

    reads = list(predicates.fact_keys(trigger))
    if follow_trigger is not None:
        reads += [k for k in predicates.fact_keys(follow_trigger) if k not in reads]
    return BoundRule(
        key=rule.key,
        executor=executor,
        action=rule.action,
        follow_up_action=None if follow_up is None else follow_up.action,
        follow_up_when=None if follow_up is None else follow_up.when,
        provisional=rule.provisional,
        note=Note(rule.message.title, (rule.message.body,), rule.provisional),
        reads=tuple(reads),
        truth=lambda answers: predicates.evaluate(trigger, context(answers)),
        unknown=lambda answers: predicates.unknown_keys(trigger, context(answers)),
        follow_up_truth=None
        if follow_trigger is None
        else (lambda answers: predicates.evaluate(follow_trigger, context(answers))),
    )


class RuleBundleExecutor:
    """The conversation rules of the installed rule bundle (``heroos.rule-bundle/1``)."""

    name = "rule_bundle"

    def matches(self, ref: ExecutorRef, workflow: str, rule_bundle: RuleBundle | None) -> bool:
        return (
            rule_bundle is not None
            and rule_bundle.workflow_key == workflow
            and rule_bundle.conversation is not None
        )

    def bind(
        self, rule: str, jurisdiction: str, workflow: str, rule_bundle: RuleBundle | None
    ) -> BoundRule | None:
        if rule_bundle is None or rule_bundle.conversation is None:
            return None
        program = rule_bundle.conversation.jurisdictions.get(jurisdiction)
        item = None if program is None else program.rule(rule)
        return None if item is None else bound_conversation_rule(item, self.name)


class WorkflowExecutionRegistry:
    """Selects the execution implementation for a workflow.

    Every workflow uses the generic evaluator and the shared executors: a new
    workflow arrives as content (knowledge, a definition, a rule bundle and a
    profile), not as code. A workflow whose execution semantics genuinely
    differ may register its own executor here; none does today.
    """

    def __init__(self, executors: Mapping[str, RuleExecutor]) -> None:
        self._executors = MappingProxyType(dict(executors))

    def executor(self, name: str) -> RuleExecutor | None:
        return self._executors.get(name)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._executors))


DEFAULT_REGISTRY: Final = WorkflowExecutionRegistry(
    {"intake": IntakeExecutor(RULESETS), "rule_bundle": RuleBundleExecutor()}
)


@dataclass(frozen=True, slots=True)
class WorkflowExecution:
    """Everything one workflow's evaluation needs, validated and indexed once."""

    workflow: str
    profile: WorkflowProfile
    knowledge: KnowledgeBundle
    definition: WorkflowDefinition
    rule_bundle: RuleBundle | None
    provenance: Provenance
    jurisdictions: tuple[str, ...]
    conditions: Mapping[str, Condition]
    categories: Mapping[str, Category]
    # (condition id, jurisdiction) -> its bound rule.
    bound: Mapping[tuple[str, str], BoundRule]
    # Bound Conditions this conversation can never evaluate, and why
    # (privacy_capability_unavailable: a sensitive input; input_not_collectable).
    incapable: Mapping[str, str]
    options: Mapping[str, Option]
    # (option id, jurisdiction) -> its mandatory-prerequisite rules.
    action_rules: Mapping[tuple[str, str], tuple[BoundRule, ...]]
    covered: Mapping[str, CoveredAction]
    facts: Mapping[str, Fact]
    schemas: Mapping[str, FactSchema]
    # Definition question key -> knowledge fact key.
    question_facts: Mapping[str, str]
    quarantined: frozenset[tuple[str, str]]
    # (option id, jurisdiction) -> the Conditions the approved content links to it there.
    option_conditions: Mapping[tuple[str, str], tuple[str, ...]]
    # (condition id, jurisdiction) -> the options linking it there.
    condition_options: Mapping[tuple[str, str], tuple[str, ...]]

    def fact_key(self, read: str) -> str:
        """A rule's input key as a knowledge fact key."""
        return self.question_facts.get(read, read)


@dataclass(frozen=True, slots=True)
class ExecutionSnapshot:
    """One immutable set of compatible artifacts. A founder turn uses one, start to finish."""

    id: str
    knowledge: KnowledgeBundle | None
    profile: ExecutionProfile | None
    workflows: Mapping[str, WorkflowExecution]
    # Workflow -> why its evaluation is unavailable, with the fixed codes (for the log).
    unavailable: Mapping[str, tuple[Availability, tuple[str, ...]]]

    def execution(self, workflow: str) -> WorkflowExecution | None:
        return self.workflows.get(workflow)

    def availability(self, workflow: str) -> Availability:
        if workflow in self.workflows:
            return "ready"
        if workflow in self.unavailable:
            return self.unavailable[workflow][0]
        if self.knowledge is None:
            return "knowledge_bundle_missing"
        return "execution_profile_missing"


class ExecutionRuntime:
    """Holds the current snapshot. ``install`` swaps it atomically; ``current`` never mixes two."""

    def __init__(self, snapshot: ExecutionSnapshot) -> None:
        self._snapshot = snapshot

    def current(self) -> ExecutionSnapshot:
        return self._snapshot

    def install(self, snapshot: ExecutionSnapshot) -> None:
        self._snapshot = snapshot


# --- building ------------------------------------------------------------------------------


class _Incompatible(Exception):
    def __init__(self, availability: Availability, code: str) -> None:
        super().__init__(code)
        self.availability = availability
        self.code = code


def _schemas(
    knowledge: KnowledgeBundle, definition: WorkflowDefinition, rule_bundle: RuleBundle | None
) -> tuple[dict[str, FactSchema], dict[str, str]]:
    questions = {q.key: q for step in definition.steps for q in step.questions}
    declared = {} if rule_bundle is None or rule_bundle.conversation is None else {
        f.key: f for f in rule_bundle.conversation.facts
    }  # fmt: skip
    schemas: dict[str, FactSchema] = {}
    question_facts: dict[str, str] = {}
    for fact in knowledge.facts:
        question = None if fact.case_fact is None else questions.get(fact.case_fact)
        if question is not None:
            question_facts[question.key] = fact.key
        if fact.sensitive:
            continue  # never collected in a conversation, never trusted for execution
        if question is not None:
            if question.sensitive or question.options_from is OptionsFrom.COMPANY_JURISDICTION:
                continue  # the jurisdiction gate owns the jurisdiction
            if question.kind == "choice":
                values = tuple(o.value for o in question.options)
                kind: FactKind = "yes_no" if values == _YES_NO else "choice"
                schemas[fact.key] = FactSchema(
                    fact.key, fact.label, kind, question.options, question=question.key
                )
            elif question.kind == "date":
                schemas[fact.key] = FactSchema(fact.key, fact.label, "date", question=question.key)
            continue
        if fact.key in declared:
            item = declared[fact.key]
            schemas[fact.key] = FactSchema(
                fact.key, fact.label, item.kind, item.options, item.maximum
            )
        elif fact.blueprint is not None and fact.blueprint != JURISDICTION_FIELD:
            schemas[fact.key] = FactSchema(
                fact.key, fact.label, "blueprint", blueprint=fact.blueprint
            )
    unknown = set(declared) - {f.key for f in knowledge.facts if not f.sensitive}
    if unknown:
        # The rule bundle types a fact the approved knowledge doesn't have.
        raise _Incompatible("incompatible_versions", "declared_fact_not_in_knowledge")
    return schemas, question_facts


def _strength(option: Option, jurisdiction: str, quarantined: frozenset[tuple[str, str]]) -> int:
    if ("option", option.id) in quarantined:
        return AVAILABILITY_STRENGTH["review_required"]
    return AVAILABILITY_STRENGTH[option.jurisdictions[jurisdiction].availability]


def _scopes(condition: Condition, jurisdictions: tuple[str, ...]) -> tuple[str, ...]:
    if condition.scope in ("shared", "global"):
        return jurisdictions
    return tuple(j for j in jurisdictions if j == condition.scope)


def categorize(
    condition: Condition,
    *,
    bound: bool,
    quarantined: frozenset[tuple[str, str]],
    linked: Mapping[tuple[str, str], tuple[str, ...]],
    options: Mapping[str, Option],
    facts: Mapping[str, Fact],
    jurisdictions: tuple[str, ...],
) -> Category:
    """The Condition's one execution category (see the module docstring)."""
    if condition.enforcement_status != "active":
        return "not_enforced"
    if ("condition", condition.id) in quarantined:
        return "quarantined"
    if bound:
        return "executable"
    if (
        condition.scope == "global"
        and condition.required_facts
        and all(
            facts[k].blueprint == JURISDICTION_FIELD for k in condition.required_facts if k in facts
        )
    ):
        return "guard_only"  # the jurisdiction gate
    follow_up = condition.action_policy.follow_up
    needed = max(
        SEVERITY[condition.action_policy.initial],
        SEVERITY[follow_up.action] if follow_up is not None else 0,
    )
    pairs = [
        (option_id, j)
        for j in _scopes(condition, jurisdictions)
        for option_id in linked.get((condition.id, j), ())
    ]
    if pairs and all(_strength(options[o], j, quarantined) >= needed for o, j in pairs):
        return "guard_only"  # every decision it guards is already held at least as strongly
    return "question_only"


def _snapshot_id(parts: list[str]) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _build_workflow(
    wp: WorkflowProfile,
    profile: ExecutionProfile,
    knowledge: KnowledgeBundle,
    rule_bundles: Mapping[str, RuleBundle],
    definitions: Mapping[str, WorkflowDefinition],
    registry: WorkflowExecutionRegistry,
    snapshot: str,
) -> WorkflowExecution:
    w = wp.workflow
    if knowledge.workflow(w) is None:
        raise _Incompatible("incompatible_versions", "workflow_not_in_knowledge")
    if knowledge.runtime_digest != wp.knowledge_runtime_digest:
        raise _Incompatible("incompatible_versions", "knowledge_digest_mismatch")
    definition = definitions.get(w)
    if definition is None or definition.version != wp.definition_version:
        raise _Incompatible("incompatible_versions", "definition_version_mismatch")
    rule_bundle = None
    if wp.rule_bundle is not None:
        rule_bundle = rule_bundles.get(w)
        if rule_bundle is None:
            raise _Incompatible("rule_bundle_missing", "rule_bundle_missing")
        if (rule_bundle.bundle_id, rule_bundle.version, rule_bundle.digest) != (
            wp.rule_bundle.bundle,
            wp.rule_bundle.version,
            wp.rule_bundle.digest,
        ) or definition.version not in rule_bundle.definition_versions:
            raise _Incompatible("incompatible_versions", "rule_bundle_mismatch")
    for ref in wp.executors:
        executor = registry.executor(ref.executor)
        if executor is None:
            raise _Incompatible("unsupported_executor", "unsupported_executor")
        if not executor.matches(ref, w, rule_bundle):
            raise _Incompatible("incompatible_versions", "executor_version_mismatch")

    jurisdictions = tuple(knowledge.jurisdictions)
    quarantined = frozenset((q.kind, q.id) for q in knowledge.quarantine)
    conditions = {c.id: c for c in knowledge.conditions if c.workflow in (w, "global")}
    options = {o.id: o for o in knowledge.options if o.workflow == w}
    facts = {f.key: f for f in knowledge.facts}
    schemas, question_facts = _schemas(knowledge, definition, rule_bundle)
    option_conditions = {
        (o.id, j): tuple(c for c in o.jurisdictions[j].conditions if c in conditions)
        for o in options.values()
        for j in jurisdictions
    }
    condition_options: dict[tuple[str, str], list[str]] = {}
    for (option_id, j), linked in option_conditions.items():
        for condition_id in linked:
            condition_options.setdefault((condition_id, j), []).append(option_id)

    engine_links = {(link.rule, link.condition) for link in knowledge.engine_links}
    declared = {e.executor for e in wp.executors}
    bound: dict[tuple[str, str], BoundRule] = {}
    incapable: dict[str, str] = {}
    for binding in wp.bindings:
        condition = conditions.get(binding.condition)
        _check_binding(binding, condition, quarantined, declared, engine_links)
        assert condition is not None
        for j in _scopes(condition, jurisdictions):
            executor = registry.executor(binding.executor)
            assert executor is not None
            rule = executor.bind(binding.rule, j, w, rule_bundle)
            if rule is None:
                raise _Incompatible("incompatible_versions", "unknown_rule")
            _check_agreement(rule, condition)
            reads = tuple(question_facts.get(k, k) for k in rule.reads)
            bound[(condition.id, j)] = BoundRule(
                key=rule.key,
                executor=rule.executor,
                action=rule.action,
                follow_up_action=rule.follow_up_action,
                follow_up_when=rule.follow_up_when,
                provisional=rule.provisional,
                note=rule.note,
                reads=reads,
                truth=rule.truth,
                unknown=rule.unknown,
                follow_up_truth=rule.follow_up_truth,
            )
            for key in reads:
                fact = facts.get(key)
                if fact is not None and fact.sensitive:
                    incapable[condition.id] = "privacy_capability_unavailable"
                elif key not in schemas and condition.id not in incapable:
                    incapable[condition.id] = "input_not_collectable"

    action_rules: dict[tuple[str, str], tuple[BoundRule, ...]] = {}
    if rule_bundle is not None and rule_bundle.conversation is not None:
        for j, program in rule_bundle.conversation.jurisdictions.items():
            for option_id, items in program.actions.items():
                if option_id not in options:
                    raise _Incompatible("incompatible_versions", "unknown_action")
                action_rules[(option_id, j)] = tuple(
                    bound_conversation_rule(item, "rule_bundle") for item in items
                )

    categories = {
        c.id: categorize(
            c,
            bound=any((c.id, j) in bound for j in jurisdictions),
            quarantined=quarantined,
            linked={k: tuple(v) for k, v in condition_options.items()},
            options=options,
            facts=facts,
            jurisdictions=jurisdictions,
        )
        for c in conditions.values()
    }
    covered = {a.action: a for a in wp.covered_actions}
    for action in covered.values():
        _check_covered(action, options, option_conditions, categories, action_rules, quarantined,
                       jurisdictions)  # fmt: skip
    provenance = Provenance(
        snapshot=snapshot,
        workflow=w,
        knowledge_runtime_digest=knowledge.runtime_digest,
        profile=profile.profile,
        profile_version=profile.version,
        profile_digest=profile.digest,
        definition_version=definition.version,
        rule_bundle=None if rule_bundle is None else rule_bundle.bundle_id,
        rule_bundle_version=None if rule_bundle is None else rule_bundle.version,
        rule_bundle_digest=None if rule_bundle is None else rule_bundle.digest,
    )
    return WorkflowExecution(
        workflow=w,
        profile=wp,
        knowledge=knowledge,
        definition=definition,
        rule_bundle=rule_bundle,
        provenance=provenance,
        jurisdictions=jurisdictions,
        conditions=MappingProxyType(conditions),
        categories=MappingProxyType(categories),
        bound=MappingProxyType(bound),
        incapable=MappingProxyType(incapable),
        options=MappingProxyType(options),
        action_rules=MappingProxyType(action_rules),
        covered=MappingProxyType(covered),
        facts=MappingProxyType(facts),
        schemas=MappingProxyType(schemas),
        question_facts=MappingProxyType(question_facts),
        quarantined=quarantined,
        option_conditions=MappingProxyType(option_conditions),
        condition_options=MappingProxyType({k: tuple(v) for k, v in condition_options.items()}),
    )


def _check_binding(
    binding: Binding,
    condition: Condition | None,
    quarantined: frozenset[tuple[str, str]],
    declared: set[str],
    engine_links: set[tuple[str, str]],
) -> None:
    if condition is None:
        raise _Incompatible("incompatible_versions", "unknown_condition")
    if not condition.participates_in_execution:
        raise _Incompatible("incompatible_versions", "not_enforced_condition_bound")
    if ("condition", condition.id) in quarantined:
        raise _Incompatible("incompatible_versions", "quarantined_condition_bound")
    if binding.executor not in declared:
        raise _Incompatible("incompatible_versions", "executor_not_declared")
    if binding.executor == "intake" and (binding.rule, condition.id) not in engine_links:
        # An intake rule runs for a Condition only where the approved knowledge links them.
        raise _Incompatible("incompatible_versions", "not_an_engine_link")


def _check_agreement(rule: BoundRule, condition: Condition) -> None:
    policy = condition.action_policy
    if rule.action != policy.initial:
        raise _Incompatible("incompatible_versions", "action_mismatch")
    follow_up = policy.follow_up
    expected = None if follow_up is None else (follow_up.action, follow_up.when)
    if (rule.follow_up_action, rule.follow_up_when) != (expected or (None, None)):
        raise _Incompatible("incompatible_versions", "follow_up_mismatch")
    if rule.provisional == condition.legal_basis_confirmed:
        # A rule under review never presents a confirmed legal basis, and vice versa.
        raise _Incompatible("incompatible_versions", "review_status_mismatch")


def _check_covered(
    action: CoveredAction,
    options: Mapping[str, Option],
    option_conditions: Mapping[tuple[str, str], tuple[str, ...]],
    categories: Mapping[str, Category],
    action_rules: Mapping[tuple[str, str], tuple[BoundRule, ...]],
    quarantined: frozenset[tuple[str, str]],
    jurisdictions: tuple[str, ...],
) -> None:
    option = options.get(action.action)
    if option is None:
        raise _Incompatible("incompatible_versions", "unknown_action")
    flags = {
        "employee_response": option.requires_employee_response,
        "completed_investigation": option.requires_completed_investigation,
    }
    for j in jurisdictions:
        if _strength(option, j, quarantined) != AVAILABILITY_STRENGTH["supported"]:
            continue  # held for review or not available: a guard decides it
        for condition_id in option_conditions[(option.id, j)]:
            if categories[condition_id] not in ("executable", "guard_only", "not_enforced"):
                raise _Incompatible("incompatible_versions", "covered_action_not_executable")
        rules = {r.key for r in action_rules.get((option.id, j), ())}
        for name, required in flags.items():
            if required and action.prerequisites.get(name) not in rules:
                raise _Incompatible("incompatible_versions", "prerequisite_not_bound")


def build_snapshot(
    knowledge: KnowledgeBundle | None,
    profile: ExecutionProfile | None,
    rule_bundles: Mapping[str, RuleBundle],
    definitions: Mapping[str, WorkflowDefinition],
    *,
    registry: WorkflowExecutionRegistry = DEFAULT_REGISTRY,
) -> ExecutionSnapshot:
    """Validate the installed artifacts together; index what is compatible, refuse the rest."""
    parts = [
        "none" if knowledge is None else knowledge.runtime_digest,
        "none" if profile is None else profile.digest,
        *sorted(f"{w}:{b.digest}" for w, b in rule_bundles.items()),
        *sorted(f"{w}:{d.version}" for w, d in definitions.items()),
    ]
    snapshot = _snapshot_id(parts)
    workflows: dict[str, WorkflowExecution] = {}
    unavailable: dict[str, tuple[Availability, tuple[str, ...]]] = {}
    if knowledge is not None and profile is not None:
        for wp in profile.workflows:
            try:
                workflows[wp.workflow] = _build_workflow(
                    wp, profile, knowledge, rule_bundles, definitions, registry, snapshot
                )
            except _Incompatible as refused:
                unavailable[wp.workflow] = (refused.availability, (refused.code,))
                logger.warning(
                    "Conversation evaluation unavailable (workflow=%s, availability=%s, code=%s)",
                    wp.workflow,
                    refused.availability,
                    refused.code,
                )
    elif profile is not None:
        for wp in profile.workflows:
            unavailable[wp.workflow] = ("knowledge_bundle_missing", ("knowledge_bundle_missing",))
    return ExecutionSnapshot(
        id=snapshot,
        knowledge=knowledge,
        profile=profile,
        workflows=MappingProxyType(workflows),
        unavailable=MappingProxyType(unavailable),
    )


def knowledge_only_runtime(knowledge: KnowledgeBundle | None) -> ExecutionRuntime:
    """Knowledge without an execution profile: deterministic checks unavailable, and say so."""
    return ExecutionRuntime(build_snapshot(knowledge, None, {}, WORKFLOWS))


def coverage_matrix(execution: WorkflowExecution) -> list[dict[str, object]]:
    """The execution coverage audit: one row per Condition (ids stay server-side)."""
    rows: list[dict[str, object]] = []
    for condition in execution.conditions.values():
        bindings = [(j, rule) for (cid, j), rule in execution.bound.items() if cid == condition.id]
        follow_up = condition.action_policy.follow_up
        rows.append(
            {
                "condition": condition.id,
                "workflow": condition.workflow,
                "jurisdiction": condition.scope,
                "enforcement_status": condition.enforcement_status,
                "citation_status": condition.citation_status,
                "action_policy": condition.action_policy.initial
                + ("" if follow_up is None else f" -> {follow_up.action} ({follow_up.when})"),
                "category": execution.categories[condition.id],
                "executor": bindings[0][1].executor if bindings else None,
                "rule": bindings[0][1].key if bindings else None,
                "compatibility": "compatible" if bindings else None,
                "capability": execution.incapable.get(condition.id),
                "linked_actions": sorted(
                    {
                        o
                        for j in execution.jurisdictions
                        for o in execution.condition_options.get((condition.id, j), ())
                    }
                ),  # fmt: skip
            }
        )
    return rows


def describe(snapshot: ExecutionSnapshot) -> str:
    """The snapshot's identity for a log line: ids, versions, short digests (no content)."""
    profile = snapshot.profile
    return json.dumps(
        {
            "snapshot": snapshot.id,
            "profile": None if profile is None else f"{profile.profile}@{profile.version}",
            "ready": sorted(snapshot.workflows),
            "unavailable": {w: a for w, (a, _) in sorted(snapshot.unavailable.items())},
        },
        separators=(",", ":"),
    )
