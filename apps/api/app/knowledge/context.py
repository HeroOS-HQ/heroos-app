"""The knowledge query service (M2-NEW-04): focused, deterministic, fail-closed.

``get_knowledge_context(bundle, query)`` answers one question: *what do
HeroOS's approved sources say that is relevant to this workflow, jurisdiction,
pathway, stage, topic, Condition or document?* It returns structured data for
the future AI gateway (M2-NEW-05) and never a fixed questionnaire, a prompt
or an answer:

- methodology units, Condition metadata, guards, documents, options and
  reference data, in the bundle's own order (same bundle and query, same
  result);
- the facts the methodology needs, and for each whether the Company
  Blueprint, the Case or nobody holds it yet (``missing_facts``);
- the behaviors every consumer must keep and must never adopt;
- limitations, and the source references behind every item.

**The status is about knowledge, not about the Case.** ``supported`` means the
approved sources cover the request; it never means a Condition passed, a
transition is allowed or an option is recommended. Those stay with the
deterministic engine (``app.workflows``) and the employer.

Statuses, the first that applies:

1. ``bundle_unavailable``: no knowledge bundle is installed.
2. ``unsupported``: the workflow, pathway, stage, topic, Condition or
   document isn't in the approved sources (nothing is returned: no general
   knowledge fills the gap).
3. ``jurisdiction_unresolved``: no jurisdiction, an unsupported one, or one
   that conflicts with the Company Blueprint. Only orientation explicitly
   marked safe without a jurisdiction is returned; never another
   jurisdiction's content.
4. ``source_conflict``: the request targets a route quarantined because its
   sources disagree or its mapping is broken.
5. ``review_required``: the approved sources route the request to specialist
   review (or it is quarantined pending review).
6. ``needs_more_context``: covered, but facts the methodology needs are not
   established yet.
7. ``supported``.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Literal

from app.companies.blueprint import CompanyBlueprintContext
from app.knowledge.bundle import (
    Condition,
    Document,
    DocumentReference,
    Fact,
    Guard,
    KnowledgeBundle,
    Option,
    QuarantineEntry,
    SourceRef,
    Unit,
)


class KnowledgeStatus(StrEnum):
    SUPPORTED = "supported"
    NEEDS_MORE_CONTEXT = "needs_more_context"
    REVIEW_REQUIRED = "review_required"
    UNSUPPORTED = "unsupported"
    JURISDICTION_UNRESOLVED = "jurisdiction_unresolved"
    SOURCE_CONFLICT = "source_conflict"
    BUNDLE_UNAVAILABLE = "bundle_unavailable"


# HeroOS has no staffed Expert Review yet (M2-NEW-09): a review is advised,
# never promised (an approved-source rule, and the product's actual state).
EXPERT_REVIEW_OPERATIONAL: Final = False

# Never done by anything built on this runtime, whatever a bundle says.
ALWAYS_PROHIBITED: Final = (
    "select_or_approve_employment_decision",
    "decide_misconduct_proven",
    "choose_sanction",
    "use_open_web_or_general_model_knowledge",
    "invent_legal_requirement",
    "blend_jurisdictions",
    "promise_expert_response",
    "offer_document_upload",
    "promise_document_deletion",
)
ALWAYS_REQUIRED: Final = ("employer_makes_final_decision", "use_approved_sources_only")
# Guards that are safe and needed even before the jurisdiction is known.
UNRESOLVED_GUARD_KINDS: Final = frozenset(
    {"jurisdiction_isolation", "approved_content_only", "employer_decision_authority",
     "contextual_collection"}
)  # fmt: skip
# Guards that apply to every request in their scope.
CROSS_CUTTING_GUARD_KINDS: Final = UNRESOLVED_GUARD_KINDS | frozenset(
    {"employer_owned_deadlines", "presentation"}
)
CONFLICT_REASONS: Final = ("source_conflict", "broken_mapping", "source_mismatch")
# The Blueprint field of the employment jurisdiction (resolved by the routing).
JURISDICTION_FIELD: Final = "jurisdiction.employment_jurisdiction"

FactAvailability = Literal["from_blueprint", "from_case", "needs_confirmation", "missing"]


@dataclass(frozen=True, slots=True)
class KnowledgeQuery:
    workflow: str
    # The Case's resolved employment jurisdiction (app.workflows routing), or None.
    jurisdiction: str | None
    pathway: str | None = None
    stage: str | None = None
    topics: tuple[str, ...] = ()
    condition_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    # Fact keys (knowledge facts or case question keys) already established.
    known_facts: frozenset[str] = frozenset()
    # The canonical company context (M2-NEW-03), when the caller has it.
    company: CompanyBlueprintContext | None = None


@dataclass(frozen=True, slots=True)
class GuidanceItem:
    id: str
    kind: str
    title: str
    pathway: str | None
    stage: str | None
    topics: tuple[str, ...]
    scope: str
    # Only the text that may be shown in this jurisdiction.
    text: tuple[str, ...]
    # Playbook statements are approved development content, not confirmed law.
    legal_status: Literal["not_applicable", "playbook_statement"]
    status: str
    limitations: tuple[str, ...]
    source_ref: SourceRef


@dataclass(frozen=True, slots=True)
class ConditionInfo:
    id: str
    scope: str
    type: str
    title: str
    # Empty when withheld (superseded in part).
    guidance: tuple[str, ...]
    action: str
    follow_up_action: str | None
    follow_up_when: str | None
    enforcement_status: str
    citation_status: str
    legal_basis_confirmed: bool
    # How a consumer may present it: never as confirmed law unless confirmed.
    presentation: Literal["confirmed_legal_basis", "provisional_not_legal_advice"]
    required_facts: tuple[str, ...]
    limitations: tuple[str, ...]
    source_ref: SourceRef


@dataclass(frozen=True, slots=True)
class GuardInfo:
    id: str
    rule: str
    kind: str
    title: str
    status: str
    required: tuple[str, ...]
    prohibited: tuple[str, ...]
    escalation: str
    text: tuple[str, ...]
    source_ref: SourceRef


@dataclass(frozen=True, slots=True)
class DocumentInfo:
    id: str
    title: str
    kind: str
    pathway: str | None
    stages: tuple[str, ...]
    # In this jurisdiction. "eligible_with_gates" still needs every gate.
    status: str
    expert_review_required: bool
    gates: tuple[str, ...]
    conditions: tuple[str, ...]
    requires_employer_decision: bool
    requires_completed_investigation: bool
    requires_employee_response: bool
    prohibited_when: tuple[str, ...]
    purpose: tuple[str, ...]
    limitations: tuple[str, ...]
    # Every other source's reference to this document, kept for traceability.
    references: tuple[DocumentReference, ...]
    source_ref: SourceRef


@dataclass(frozen=True, slots=True)
class NextStep:
    """A possible employer decision the approved content covers. Never a recommendation."""

    option_id: str
    kind: str
    title: str
    availability: str
    reason: str
    is_penalty: bool
    requires_completed_investigation: bool
    requires_employee_response: bool
    decided_by: Literal["employer"]
    documents: tuple[str, ...]
    conditions: tuple[str, ...]
    guards: tuple[str, ...]
    required_facts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FactRequirement:
    key: str
    label: str
    availability: FactAvailability
    source: str
    sensitive: bool


@dataclass(frozen=True, slots=True)
class ReferenceInfo:
    id: str
    title: str
    items: tuple[str, ...]
    citation_status: str
    legal_basis_confirmed: bool
    source_ref: SourceRef


@dataclass(frozen=True, slots=True)
class Safeguard:
    kind: Literal["condition", "guard"]
    id: str
    title: str
    action: str


@dataclass(frozen=True, slots=True)
class Limitation:
    code: str
    subject: str


@dataclass(frozen=True, slots=True)
class KnowledgeContext:
    status: KnowledgeStatus
    source_package_digest: str | None
    runtime_bundle_digest: str | None
    bundle_version: str | None
    provenance: str | None
    workflow: str
    jurisdiction: str | None
    pathway: str | None
    stage: str | None
    topics: tuple[str, ...]
    playbook_units: tuple[GuidanceItem, ...] = ()
    condition_metadata: tuple[ConditionInfo, ...] = ()
    implementation_guards: tuple[GuardInfo, ...] = ()
    document_metadata: tuple[DocumentInfo, ...] = ()
    reference_data: tuple[ReferenceInfo, ...] = ()
    required_facts: tuple[FactRequirement, ...] = ()
    missing_facts: tuple[str, ...] = ()
    safeguards: tuple[Safeguard, ...] = ()
    supported_next_steps: tuple[NextStep, ...] = ()
    required_behaviors: tuple[str, ...] = ALWAYS_REQUIRED
    prohibited_behaviors: tuple[str, ...] = ALWAYS_PROHIBITED
    limitations: tuple[Limitation, ...] = ()
    source_refs: tuple[SourceRef, ...] = ()
    # The employer makes every employment decision; nothing here selects one.
    decided_by: Literal["employer"] = field(default="employer")


def _ordered(values: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return tuple(seen)


def _text(segments: Iterable[object], scopes: frozenset[str]) -> tuple[str, ...]:
    return tuple(s.text for s in segments if s.scope in scopes)  # type: ignore[attr-defined]  # Segment


def resolve_jurisdiction(
    bundle: KnowledgeBundle, query: KnowledgeQuery
) -> tuple[str | None, str | None]:
    """(jurisdiction, None) or (None, reason). Never a default, never another regime."""
    requested = query.jurisdiction
    if query.company is not None:
        company = query.company.jurisdiction
        if not company.guidance_allowed:
            return None, f"company_jurisdiction_{company.readiness}"
        if requested is not None and requested != company.employment_jurisdiction:
            return None, "jurisdiction_conflict"
    if requested is None:
        return None, "jurisdiction_missing"
    if requested not in bundle.jurisdictions:
        return None, "jurisdiction_not_supported"
    return requested, None


def _empty(
    bundle: KnowledgeBundle | None, query: KnowledgeQuery, status: KnowledgeStatus,
    limitations: Sequence[Limitation],
) -> KnowledgeContext:  # fmt: skip
    return KnowledgeContext(
        status=status,
        source_package_digest=None if bundle is None else bundle.source_package_digest,
        runtime_bundle_digest=None if bundle is None else bundle.runtime_digest,
        bundle_version=None if bundle is None else bundle.version,
        provenance=None if bundle is None else bundle.provenance,
        workflow=query.workflow,
        jurisdiction=query.jurisdiction,
        pathway=query.pathway,
        stage=query.stage,
        topics=query.topics,
        limitations=tuple(limitations),
    )


def _unknown_selectors(bundle: KnowledgeBundle, query: KnowledgeQuery) -> list[Limitation]:
    workflow = bundle.workflow(query.workflow)
    assert workflow is not None
    unknown: list[Limitation] = []
    pathway = None if query.pathway is None else workflow.pathway(query.pathway)
    if query.pathway is not None and pathway is None:
        unknown.append(Limitation("pathway_not_covered", query.pathway))
    if query.stage is not None:
        stages = [s.key for p in workflow.pathways if pathway in (None, p) for s in p.stages]
        if query.stage not in stages:
            unknown.append(Limitation("stage_not_covered", query.stage))
    topics = {t.key for t in bundle.topics if t.workflow == workflow.key}
    unknown += [Limitation("topic_not_covered", t) for t in query.topics if t not in topics]
    conditions = {c.id for c in bundle.conditions}
    unknown += [
        Limitation("condition_not_in_runtime", c)
        for c in query.condition_ids
        if c not in conditions
    ]
    documents = {d.id for d in bundle.documents}
    unknown += [
        Limitation("document_not_in_runtime", d) for d in query.document_ids if d not in documents
    ]
    return unknown


def _guard_info(guard: Guard, scopes: frozenset[str]) -> GuardInfo:
    return GuardInfo(
        id=guard.id,
        rule=guard.rule,
        kind=guard.kind,
        title=guard.title,
        status=guard.status,
        required=guard.required,
        prohibited=guard.prohibited,
        escalation=guard.escalation,
        text=_text(guard.segments, scopes),
        source_ref=guard.source_ref,
    )


def _unit_info(unit: Unit, scopes: frozenset[str]) -> GuidanceItem:
    return GuidanceItem(
        id=unit.id,
        kind=unit.kind,
        title=unit.title,
        pathway=unit.pathway,
        stage=unit.stage,
        topics=unit.topics,
        scope=unit.scope,
        text=_text(unit.segments, scopes),
        legal_status="playbook_statement" if unit.kind == "legal_reference" else "not_applicable",
        status=unit.status,
        limitations=unit.limitations,
        source_ref=unit.source_ref,
    )


def _condition_info(condition: Condition, scopes: frozenset[str]) -> ConditionInfo:
    follow_up = condition.action_policy.follow_up
    limitations = list(condition.limitations)
    if not condition.legal_basis_confirmed:
        limitations.append("legal_basis_not_confirmed")
    if condition.guidance_status == "withheld":
        limitations.append("guidance_withheld")
    return ConditionInfo(
        id=condition.id,
        scope=condition.scope,
        type=condition.type,
        title=condition.title,
        guidance=()
        if condition.guidance_status == "withheld"
        else _text(condition.segments, scopes),
        action=condition.action_policy.initial,
        follow_up_action=None if follow_up is None else follow_up.action,
        follow_up_when=None if follow_up is None else follow_up.when,
        enforcement_status=condition.enforcement_status,
        citation_status=condition.citation_status,
        legal_basis_confirmed=condition.legal_basis_confirmed,
        presentation=(
            "confirmed_legal_basis"
            if condition.legal_basis_confirmed
            else "provisional_not_legal_advice"
        ),
        required_facts=condition.required_facts,
        limitations=_ordered(limitations),
        source_ref=condition.source_ref,
    )


def _fact_requirement(
    fact: Fact, query: KnowledgeQuery, jurisdiction: str | None = None
) -> FactRequirement:
    if jurisdiction is not None and fact.blueprint == JURISDICTION_FIELD:
        # The deterministic routing resolved it for this Case (never inferred here).
        return FactRequirement(
            fact.key, fact.label, "from_case", "routing:jurisdiction", fact.sensitive
        )
    if fact.key in query.known_facts or (
        fact.case_fact is not None and fact.case_fact in query.known_facts
    ):
        availability: FactAvailability = "from_case"
        source = f"case:{fact.case_fact or fact.key}"
    elif (
        fact.blueprint is not None
        and query.company is not None
        and _blueprint_value(query.company, fact.blueprint) not in (None, "")
    ):
        availability = "needs_confirmation" if fact.needs_confirmation else "from_blueprint"
        source = f"blueprint:{fact.blueprint}"
    else:
        availability = "missing"
        source = (
            f"case:{fact.case_fact}" if fact.case_fact is not None
            else f"blueprint:{fact.blueprint}" if fact.blueprint is not None
            else "conversation"
        )  # fmt: skip
    return FactRequirement(fact.key, fact.label, availability, source, fact.sensitive)


def _blueprint_value(company: CompanyBlueprintContext, path: str) -> object:
    value: object = company
    for part in path.split("."):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def get_knowledge_context(
    bundle: KnowledgeBundle | None, query: KnowledgeQuery
) -> KnowledgeContext:
    """The approved knowledge relevant to ``query``, or an explicit reason there is none."""
    if bundle is None:
        return _empty(
            None, query, KnowledgeStatus.BUNDLE_UNAVAILABLE,
            [Limitation("knowledge_not_installed", query.workflow)],
        )  # fmt: skip
    workflow = bundle.workflow(query.workflow)
    if workflow is None:
        return _empty(
            bundle, query, KnowledgeStatus.UNSUPPORTED,
            [Limitation("workflow_not_in_approved_sources", query.workflow)],
        )  # fmt: skip
    unknown = _unknown_selectors(bundle, query)
    if unknown:
        return _empty(bundle, query, KnowledgeStatus.UNSUPPORTED, unknown)

    jurisdiction, unresolved = resolve_jurisdiction(bundle, query)
    quarantined = {(q.kind, q.id): q for q in bundle.quarantine}
    limitations: list[Limitation] = []
    if bundle.provenance == "synthetic":
        limitations.append(Limitation("synthetic_content", bundle.bundle_id))
    if bundle.approval == "development":
        limitations.append(
            Limitation("development_content_not_production_approved", bundle.bundle_id)
        )

    if unresolved is not None:
        return _unresolved(bundle, query, unresolved, limitations)
    assert jurisdiction is not None
    scopes = frozenset({"shared", "global", jurisdiction})
    limitations += [
        Limitation(code, jurisdiction)
        for code in workflow_limitations(bundle, query.workflow, jurisdiction)
    ]

    # --- units: narrow, by stage, pathway, topics; general orientation otherwise ---------
    def relevant(unit: Unit) -> bool:
        if unit.workflow != workflow.key or unit.scope not in scopes:
            return False
        topical = bool(query.topics) and bool(set(unit.topics) & set(query.topics))
        if query.stage is not None:
            return unit.stage == query.stage and (not query.topics or topical)
        if query.pathway is not None:
            return unit.pathway == query.pathway and (
                topical if query.topics else unit.stage is None
            )
        if query.topics:
            return topical
        if query.condition_ids or query.document_ids:
            return False
        return unit.pathway is None and unit.stage is None

    units: list[Unit] = []
    for unit in bundle.units:
        if not relevant(unit):
            continue
        if unit.status == "quarantined" or ("unit", unit.id) in quarantined:
            limitations.append(Limitation("unit_quarantined", unit.id))
            continue
        units.append(unit)

    # --- options and documents reached from the units, or asked for ---------------------
    option_ids = {o for u in units for o in u.options}
    options = [
        o for o in bundle.options
        if o.id in option_ids and o.workflow == workflow.key
        and (query.pathway is None or o.pathway in (None, query.pathway))
    ]  # fmt: skip
    document_ids = (
        set(query.document_ids)
        | {d for u in units for d in u.documents}
        | {d for o in options for d in o.jurisdictions[jurisdiction].documents}
    )
    documents = [d for d in bundle.documents if d.id in document_ids]

    # --- Conditions: asked for, referenced, topical or global; active only -----------
    referenced = (
        set(query.condition_ids)
        | {c for u in units for c in u.conditions}
        | {c for o in options for c in o.jurisdictions[jurisdiction].conditions}
        | {c for d in documents for c in d.jurisdictions[jurisdiction].conditions}
    )
    conditions: list[Condition] = []
    for condition in bundle.conditions:
        if condition.scope not in scopes:
            continue
        wanted = (
            condition.id in referenced
            or condition.workflow == "global"
            or bool(query.topics and set(condition.topics) & set(query.topics))
            or (query.stage is not None and query.stage in condition.stages)
        )
        if not wanted:
            continue
        if not condition.participates_in_execution:
            if condition.id in query.condition_ids:
                limitations.append(Limitation("condition_not_enforced", condition.id))
            continue
        if ("condition", condition.id) in quarantined:
            limitations.append(Limitation("condition_quarantined", condition.id))
            continue
        conditions.append(condition)
    for asked in query.condition_ids:
        found = bundle.condition(asked)
        if found is not None and found.scope not in scopes:
            limitations.append(Limitation("condition_other_jurisdiction", asked))

    # --- guards: cross-cutting, referenced, or triggered by a topic ------------------
    topics = set(query.topics) | {t for u in units for t in u.topics}
    guard_ids = (
        {g for u in units for g in u.guards}
        | {g for o in options for g in o.jurisdictions[jurisdiction].guards}
        | {g for d in documents for g in d.jurisdictions[jurisdiction].guards}
    )
    guards: list[Guard] = []
    deferred: list[Guard] = []
    for guard in bundle.guards:
        if guard.workflow not in (workflow.key, "all") or guard.scope not in scopes:
            continue
        wanted = (
            guard.kind in CROSS_CUTTING_GUARD_KINDS
            or guard.id in guard_ids
            or bool(set(guard.topics) & topics)
            or bool(set(guard.options) & {o.id for o in options})
        )
        if not wanted:
            continue
        if guard.status == "operational":
            guards.append(guard)
        elif guard.status == "deferred":
            deferred.append(guard)
    for guard in deferred:
        limitations.append(Limitation("deferred_capability", guard.id))

    # --- facts --------------------------------------------------------------------
    fact_keys = _ordered(
        [k for u in units for k in u.required_facts]
        + [k for c in conditions for k in c.required_facts]
        + [k for o in options for k in o.jurisdictions[jurisdiction].required_facts]
        + [k for d in documents for k in d.jurisdictions[jurisdiction].gates]
    )
    facts = [_fact_requirement(f, query, jurisdiction) for f in bundle.facts if f.key in fact_keys]
    missing = tuple(f.key for f in facts if f.availability in ("missing", "needs_confirmation"))

    # --- presentation -------------------------------------------------------------
    next_steps = []
    for option in options:
        entry = option.jurisdictions[jurisdiction]
        availability = entry.availability
        reason = entry.reason
        if ("option", option.id) in quarantined:
            availability, reason = "review_required", quarantined[("option", option.id)].reason
        next_steps.append(
            NextStep(
                option_id=option.id,
                kind=option.kind,
                title=option.title,
                availability=availability,
                reason=reason,
                is_penalty=option.is_penalty,
                requires_completed_investigation=option.requires_completed_investigation,
                requires_employee_response=option.requires_employee_response,
                decided_by="employer",
                documents=entry.documents,
                conditions=entry.conditions,
                guards=entry.guards,
                required_facts=entry.required_facts,
            )
        )
    document_infos = [_document_info(d, jurisdiction, scopes, quarantined) for d in documents]
    reference = [
        ReferenceInfo(
            r.id,
            r.title,
            r.items,
            r.citation_status,
            r.citation_status == "confirmed",
            r.source_ref,
        )
        for r in bundle.reference_data
        if r.scope in scopes and set(r.used_by) & {c.id for c in conditions}
    ]
    for condition in conditions:
        if not condition.legal_basis_confirmed:
            limitations.append(Limitation("legal_basis_not_confirmed", condition.id))
        if condition.guidance_status == "withheld":
            limitations.append(Limitation("guidance_withheld", condition.id))
    review = [s for s in next_steps if s.availability == "review_required"]
    if review and not EXPERT_REVIEW_OPERATIONAL:
        limitations.append(Limitation("expert_review_not_operational", query.workflow))

    status = _status(
        query, units, conditions, options, documents, guards, jurisdiction, quarantined,
        bundle.options, {t.key: t.options for t in bundle.topics},
    )  # fmt: skip
    if status is KnowledgeStatus.UNSUPPORTED:
        limitations.append(Limitation("no_approved_content", query.workflow))
    elif status is KnowledgeStatus.SUPPORTED and missing:
        status = KnowledgeStatus.NEEDS_MORE_CONTEXT
    if status is KnowledgeStatus.REVIEW_REQUIRED and not EXPERT_REVIEW_OPERATIONAL:
        limitations.append(Limitation("expert_review_not_operational", query.workflow))

    required = _ordered([*ALWAYS_REQUIRED, *(b for g in guards for b in g.required)])
    prohibited = _ordered(
        [
            *ALWAYS_PROHIBITED,
            *(b for g in guards for b in g.prohibited),
            *(b for g in deferred for b in g.prohibited),
        ]
    )
    refs: list[SourceRef] = []
    for ref in (
        [u.source_ref for u in units]
        + [c.source_ref for c in conditions]
        + [g.source_ref for g in guards]
        + [d.source_ref for d in documents]
        + [r for o in options for r in o.source_refs]
    ):
        if ref not in refs:
            refs.append(ref)
    safeguards = [Safeguard("guard", g.id, g.title, g.escalation) for g in guards] + [
        Safeguard("condition", c.id, c.title, c.action_policy.initial) for c in conditions
    ]
    return KnowledgeContext(
        status=status,
        source_package_digest=bundle.source_package_digest,
        runtime_bundle_digest=bundle.runtime_digest,
        bundle_version=bundle.version,
        provenance=bundle.provenance,
        workflow=query.workflow,
        jurisdiction=jurisdiction,
        pathway=query.pathway,
        stage=query.stage,
        topics=query.topics,
        playbook_units=tuple(_unit_info(u, scopes) for u in units),
        condition_metadata=tuple(_condition_info(c, scopes) for c in conditions),
        implementation_guards=tuple(_guard_info(g, scopes) for g in guards),
        document_metadata=tuple(document_infos),
        reference_data=tuple(reference),
        required_facts=tuple(facts),
        missing_facts=missing,
        safeguards=tuple(safeguards),
        supported_next_steps=tuple(next_steps),
        required_behaviors=required,
        prohibited_behaviors=prohibited,
        limitations=tuple(dict.fromkeys(limitations)),
        source_refs=tuple(refs),
    )


def workflow_limitations(
    bundle: KnowledgeBundle, workflow: str, jurisdiction: str
) -> tuple[str, ...]:
    """Coverage limits the sources themselves record for a jurisdiction."""
    found = bundle.workflow(workflow)
    return () if found is None else found.limitations.get(jurisdiction, ())


def _document_info(
    document: Document, jurisdiction: str, scopes: frozenset[str],
    quarantined: Mapping[tuple[str, str], QuarantineEntry],
) -> DocumentInfo:  # fmt: skip
    entry = document.jurisdictions[jurisdiction]
    status = entry.status
    limitations = list(entry.limitations)
    if ("document", document.id) in quarantined:
        status = "quarantined"
        limitations.append(quarantined[("document", document.id)].reason)
    return DocumentInfo(
        id=document.id,
        title=document.title,
        kind=document.kind,
        pathway=document.pathway,
        stages=document.stages,
        status=status,
        expert_review_required=status == "expert_review_required",
        gates=entry.gates,
        conditions=entry.conditions,
        requires_employer_decision=document.requires_employer_decision,
        requires_completed_investigation=document.requires_completed_investigation,
        requires_employee_response=document.requires_employee_response,
        prohibited_when=document.prohibited_when,
        purpose=_text(document.segments, scopes),
        limitations=_ordered(limitations),
        references=document.references,
        source_ref=document.source_ref,
    )


def _status(
    query: KnowledgeQuery, units: Sequence[Unit], conditions: Sequence[Condition],
    options: Sequence[Option], documents: Sequence[Document], guards: Sequence[Guard],
    jurisdiction: str, quarantined: Mapping[tuple[str, str], QuarantineEntry],
    all_options: Sequence[Option], topic_options: Mapping[str, tuple[str, ...]],
) -> KnowledgeStatus:  # fmt: skip
    asked: list[tuple[str, str]] = [("document", d) for d in query.document_ids]
    asked += [("route", t) for t in query.topics] + [("condition", c) for c in query.condition_ids]
    for key in asked:
        entry = quarantined.get(key)
        if entry is not None:
            reason = entry.reason
            if reason.startswith(CONFLICT_REASONS):
                return KnowledgeStatus.SOURCE_CONFLICT
            return KnowledgeStatus.REVIEW_REQUIRED
    substantive = units or options or documents or [c for c in conditions if c.workflow != "global"]
    if not substantive and not query.condition_ids:
        return KnowledgeStatus.UNSUPPORTED
    for document in documents:
        if document.id in query.document_ids and document.jurisdictions[jurisdiction].status in (
            "review_required", "expert_review_required", "not_available",
        ):  # fmt: skip
            return KnowledgeStatus.REVIEW_REQUIRED
    if query.topics:
        # A decision topic whose every decision needs review, or a topic an
        # operational expert-review guard is triggered by, is routed to review.
        for topic in query.topics:
            decided = [o for o in all_options if o.id in topic_options.get(topic, ())]
            if decided and all(
                o.jurisdictions[jurisdiction].availability != "supported" for o in decided
            ):
                return KnowledgeStatus.REVIEW_REQUIRED
        expert = [
            g for g in guards
            if g.escalation == "human_expert_review" and set(g.topics) & set(query.topics)
        ]  # fmt: skip
        if expert:
            return KnowledgeStatus.REVIEW_REQUIRED
    return KnowledgeStatus.SUPPORTED


def _unresolved(
    bundle: KnowledgeBundle, query: KnowledgeQuery, reason: str, limitations: list[Limitation]
) -> KnowledgeContext:
    """Orientation explicitly safe without a jurisdiction, and the routing prerequisite."""
    scopes = frozenset({"shared", "global"})
    units = [
        u for u in bundle.units
        if u.workflow == query.workflow and u.without_jurisdiction and u.status == "operational"
        and (query.pathway is None or u.pathway in (None, query.pathway))
    ]  # fmt: skip
    conditions = [
        c for c in bundle.conditions
        if c.workflow == "global" and c.scope == "global" and c.participates_in_execution
    ]  # fmt: skip
    guards = [
        g for g in bundle.guards
        if g.status == "operational" and g.scope in scopes and g.kind in UNRESOLVED_GUARD_KINDS
        and g.workflow in (query.workflow, "all")
    ]  # fmt: skip
    limitations = [Limitation("jurisdiction_unresolved", reason), *limitations]
    return KnowledgeContext(
        status=KnowledgeStatus.JURISDICTION_UNRESOLVED,
        source_package_digest=bundle.source_package_digest,
        runtime_bundle_digest=bundle.runtime_digest,
        bundle_version=bundle.version,
        provenance=bundle.provenance,
        workflow=query.workflow,
        jurisdiction=None,
        pathway=query.pathway,
        stage=query.stage,
        topics=query.topics,
        playbook_units=tuple(_unit_info(u, scopes) for u in units),
        condition_metadata=tuple(_condition_info(c, scopes) for c in conditions),
        implementation_guards=tuple(_guard_info(g, scopes) for g in guards),
        safeguards=tuple(
            [Safeguard("guard", g.id, g.title, g.escalation) for g in guards]
            + [Safeguard("condition", c.id, c.title, c.action_policy.initial) for c in conditions]
        ),
        required_behaviors=_ordered(
            [
                *ALWAYS_REQUIRED,
                "confirm_jurisdiction_first",
                *(b for g in guards for b in g.required),
            ]
        ),
        prohibited_behaviors=_ordered(
            [
                *ALWAYS_PROHIBITED,
                "apply_other_jurisdiction_law",
                *(b for g in guards for b in g.prohibited),
            ]
        ),
        limitations=tuple(dict.fromkeys(limitations)),
        source_refs=tuple(
            dict.fromkeys(
                [u.source_ref for u in units]
                + [c.source_ref for c in conditions]
                + [g.source_ref for g in guards]
            )
        ),
    )
