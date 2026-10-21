"""Private knowledge bundles: schema, strict validation, digests and loading (M2-NEW-04).

A knowledge bundle is the compiled, normalized form of HeroOS's approved
sources for one workflow (Disciplinary first). It is written offline by
``scripts.knowledge`` from the authoritative source package and is
proprietary: the real (``private``) bundle never lives in this repository; a
fictional ``synthetic`` one tests the runtime.

Loading contract (``load_knowledge_bundle``), all fail-closed:

- the backend reads one file from server-side storage, once, at startup; no
  route serves the bundle, and the browser never receives it;
- the file's SHA-256 must equal the configured pin;
- the JSON must match this schema exactly (unknown or missing fields, unknown
  codes, duplicate keys or ids, dangling references and bounds are refused);
- both digests must verify: ``source_package_digest`` is recomputed from the
  manifest, ``runtime_bundle_digest`` from the ``runtime`` section;
- every **safety invariant** below must hold, whatever the content says;
- the links to the deterministic intake rules (``engine_links``) must agree
  with ``app.workflows.conditions`` on action, review status, enforcement and
  jurisdiction, and every fact must name a real Blueprint field or a real
  question of the current workflow definition;
- production refuses a synthetic bundle and a bundle that is still
  ``development`` content.

Errors carry a fixed code and a structural location (ids and indexes, never
wording). Nothing here evaluates a Condition: ``trigger`` is a description,
never an expression, and there is no ``eval``.

Schema ``heroos.knowledge-bundle/1``::

    {"schema", "bundle", "version", "provenance": "synthetic" | "private",
     "approval": "development" | "approved", "notice": {"title", "body"} | null,
     "compiler", "source_package_digest", "runtime_bundle_digest",
     "manifest": [source], "compiler_inputs": [{"name", "sha256"}],
     "runtime": {"workflows", "jurisdictions", "topics", "facts", "units",
                 "conditions", "guards", "documents", "options",
                 "reference_data", "quarantine", "engine_links"},
     "validation": {"findings": [finding], "counts": {...}}}

The runtime digest covers ``runtime`` only: a change in an audit-only sheet
or a reworded diagnostic changes the source package digest, not the runtime
digest; any change to operational knowledge changes both.

**Safety invariants** (``_check_invariants``), checked on every bundle:

1. A dismissal without notice is never ``supported`` in any jurisdiction, and
   requires a completed investigation and the employee's response.
2. A salary deduction is ``review_required`` in every jurisdiction, behind an
   operational expert-review guard; no document serves it.
3. In DIFC, a dismissal without notice and an unpaid disciplinary suspension
   are ``review_required`` behind an operational expert-review guard, and no
   document for them is eligible there.
4. Investigative suspension is not a penalty, unpaid disciplinary suspension
   is, and no document serves both.
5. Every option is the employer's decision; every penalty option needs the
   employee's response first; a document is never more available in a
   jurisdiction than every option it serves.
6. Jurisdiction isolation: customer-facing text scoped ``shared`` or ``difc``
   states no UAE Federal legal authority, and text scoped ``uae_federal``
   states no DIFC legal authority, except to say that it doesn't apply.
7. Only ``active`` Conditions can be linked to a deterministic rule.
8. The guards every disciplinary runtime needs are present and operational.
"""

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Final, Literal

from app.companies.blueprint import CompanyBlueprintContext
from app.workflows.conditions import JURISDICTIONS, RULESETS
from app.workflows.definition import current_definition

SCHEMA: Final = "heroos.knowledge-bundle/1"
MAX_BUNDLE_BYTES: Final = 4 * 1024 * 1024

Provenance = Literal["synthetic", "private"]
Approval = Literal["development", "approved"]
# Source scopes. ``shared``: practical methodology usable in every supported
# jurisdiction; ``global``: a cross-cutting prerequisite (routing).
Scope = Literal["shared", "uae_federal", "difc", "global"]
SCOPES: Final = ("shared", "uae_federal", "difc", "global")
ItemStatus = Literal["operational", "review_required", "quarantined"]
ITEM_STATUSES: Final = ("operational", "review_required", "quarantined")

SOURCE_TYPES: Final = ("playbook", "implementation_rules", "conditions_workbook", "template")
RUNTIME_ROLES: Final = (
    "operational", "validation", "audit_only", "test_only", "deferred", "quarantined",
)  # fmt: skip
UNIT_KINDS: Final = ("orientation", "methodology", "legal_reference", "safeguard")
STAGE_KINDS: Final = ("assessment", "process", "investigation", "outcome", "review")
CONDITION_TYPES: Final = ("precondition", "step_caution", "blocking")
ACTIONS: Final = ("warn", "block", "escalate")
FOLLOW_UP_WHEN: Final = ("employer_insists", "condition_specific")
ENFORCEMENT: Final = ("active", "not_enforced")
CITATION: Final = ("confirmed", "needs_legal_review")
GUIDANCE_STATUSES: Final = ("available", "withheld")

GUARD_KINDS: Final = (
    "jurisdiction_isolation", "investigation_first", "employer_decision_authority",
    "contextual_collection", "approved_content_only", "employer_owned_deadlines",
    "suspension_distinction", "expert_review_mandatory", "fair_process", "grievance_evidence",
    "discretionary_benefit_distinction", "presentation", "deferred_capability", "status_note",
    "authoring",
)  # fmt: skip
GUARD_STATUSES: Final = ("operational", "superseded", "deferred", "audit_only")
ESCALATIONS: Final = ("none", "human_expert_review", "pause_until_jurisdiction_confirmed")

# What a guard requires of, or forbids to, everything built on this runtime
# (the AI gateway included). A closed vocabulary: content can't invent one.
REQUIRED_BEHAVIORS: Final = frozenset({
    "confirm_jurisdiction_first", "suppress_other_jurisdiction_law",
    "use_shared_practice_when_same", "guide_investigation_first", "establish_required_facts",
    "reuse_known_information", "ask_only_material_questions", "explain_supported_options",
    "explain_risks", "explain_limitation", "refer_to_specialist_review",
    "gather_facts_for_review", "employer_makes_final_decision", "record_employer_decision",
    "distinguish_suspension_types", "require_expert_clearance", "use_traceable_delivery",
    "record_signature_refusal", "keep_records_confidential",
    "distinguish_discretionary_from_contractual", "use_approved_sources_only",
    "explain_deadlines_employer_tracks", "hold_unsupported_for_review",
})  # fmt: skip
PROHIBITED_BEHAVIORS: Final = frozenset({
    "apply_other_jurisdiction_law", "cite_federal_law_for_difc", "blend_jurisdictions",
    "dismiss_on_classification", "treat_stage_completion_as_lawful_dismissal",
    "present_dismissal_without_notice_automatically", "select_or_approve_employment_decision",
    "decide_misconduct_proven", "choose_sanction", "determine_deduction_legality",
    "recommend_deduction_amount", "calculate_deduction", "generate_deduction_notice",
    "instruct_payroll", "recommend_dismissal_without_notice",
    "generate_dismissal_without_notice_letter_before_clearance", "recommend_unpaid_suspension",
    "generate_unpaid_suspension_notice", "apply_federal_suspension_limits_to_difc",
    "treat_suspension_as_finding", "conflate_suspension_types",
    "use_open_web_or_general_model_knowledge", "invent_legal_requirement",
    "rigid_questionnaire", "repeat_answered_questions", "promise_deadline_monitoring",
    "promise_document_deletion", "offer_document_upload", "promise_expert_response",
    "invent_universal_deadline", "assert_universal_consent_rule",
    "assume_signature_makes_deduction_lawful", "present_benefit_decision_as_statutory_penalty",
    "withhold_contractual_entitlement", "show_internal_labels",
})  # fmt: skip

OptionKind = Literal[
    "no_action", "informal_resolution", "workplace_reminder", "written_warning",
    "final_written_warning", "disciplinary_suspension_unpaid", "salary_deduction",
    "delay_increase_or_promotion", "ordinary_termination", "investigative_suspension",
    "disciplinary_penalty_notice", "dismissal_without_notice",
]  # fmt: skip
OPTION_KINDS: Final = (
    "no_action", "informal_resolution", "workplace_reminder", "written_warning",
    "final_written_warning", "disciplinary_suspension_unpaid", "salary_deduction",
    "delay_increase_or_promotion", "ordinary_termination", "investigative_suspension",
    "disciplinary_penalty_notice", "dismissal_without_notice",
)  # fmt: skip
Availability = Literal["supported", "review_required", "not_available"]
AVAILABILITIES: Final = ("supported", "review_required", "not_available")
DocumentStatus = Literal[
    "eligible_with_gates", "review_required", "expert_review_required", "not_available",
    "quarantined",
]  # fmt: skip
DOCUMENT_STATUSES: Final = (
    "eligible_with_gates", "review_required", "expert_review_required", "not_available",
    "quarantined",
)  # fmt: skip
DOCUMENT_KINDS: Final = ("letter", "email", "minutes", "notice")
REFERENCE_RESOLUTIONS: Final = (
    "consistent", "title_variant", "source_mismatch_resolved", "source_mismatch", "stale",
)  # fmt: skip
QUARANTINE_KINDS: Final = ("unit", "condition", "document", "option", "route", "reference_data")
FINDING_CODES: Final = (
    "SOURCE_MISMATCH", "STALE_METADATA", "BROKEN_MAPPING", "REVIEW_REQUIRED", "QUARANTINED",
    "SOURCE_CONFLICT", "SUPERSEDED", "MALFORMED_ACTION", "INVALID_ROW", "DUPLICATE_ID",
    "MISSING_SOURCE", "UNEXPECTED_SOURCE", "JURISDICTION_LEAKAGE", "UNMAPPED_FACT",
    "DEFERRED_CAPABILITY", "COVERAGE", "OWNER_DECISION", "SOURCE_CHANGED",
)  # fmt: skip
SEVERITIES: Final = ("INFO", "WARNING", "REVIEW_REQUIRED", "QUARANTINED", "FATAL")

# The option kinds whose availability the invariants fix, whatever the content.
NEVER_SUPPORTED: Final = frozenset({"dismissal_without_notice", "salary_deduction"})
DIFC_EXPERT_REVIEW: Final = frozenset(
    {"dismissal_without_notice", "disciplinary_suspension_unpaid"}
)
PENALTY_KINDS: Final = frozenset({
    "written_warning", "final_written_warning", "disciplinary_suspension_unpaid",
    "salary_deduction", "delay_increase_or_promotion", "ordinary_termination",
    "disciplinary_penalty_notice", "dismissal_without_notice",
})  # fmt: skip
INVESTIGATION_FIRST_KINDS: Final = frozenset({
    "dismissal_without_notice", "disciplinary_penalty_notice", "disciplinary_suspension_unpaid",
})  # fmt: skip
# Guard kinds every disciplinary runtime must carry, operational.
REQUIRED_GUARD_KINDS: Final = frozenset({
    "jurisdiction_isolation", "investigation_first", "employer_decision_authority",
    "approved_content_only", "expert_review_mandatory", "suspension_distinction",
    "contextual_collection",
})  # fmt: skip

ID: Final = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,79}$")
KEY: Final = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
FACT_KEY: Final = re.compile(r"^[a-z][a-z0-9_.]{0,99}$")
VERSION: Final = re.compile(r"^[a-z0-9][a-z0-9.-]{0,49}$")
BUNDLE_ID: Final = re.compile(r"^[a-z][a-z0-9-]{0,49}$")
SHA256_HEX: Final = re.compile(r"^[0-9a-f]{64}$")
LIMITATION: Final = re.compile(r"^[a-z][a-z0-9_:.-]{0,99}$")

MAX_ITEMS: Final = 400
MAX_TEXT: Final = 6000
MAX_SHORT: Final = 300


class KnowledgeBundleError(ValueError):
    """The bundle is refused. ``code`` is fixed; ``location`` is structural only."""

    def __init__(self, code: str, location: str = "") -> None:
        self.code = code
        self.location = location
        suffix = f" at {location}" if location else ""
        super().__init__(f"knowledge bundle refused: {code}{suffix}")


# --- the model ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Message:
    title: str
    body: str


@dataclass(frozen=True, slots=True)
class SourceRef:
    source_id: str
    # Structural: a rule number, a sheet and row, a paragraph range, a file.
    location: str
    # SHA-256 of the exact source text the item was compiled from.
    content_sha256: str


@dataclass(frozen=True, slots=True)
class Segment:
    """Source text with the jurisdictions it may be shown in."""

    scope: Scope
    text: str


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    source_id: str
    source_type: str
    title: str
    filename: str
    sha256: str
    size: int
    source_version: str
    workflow: str
    jurisdiction_scope: str
    runtime_role: str


@dataclass(frozen=True, slots=True)
class StageDef:
    key: str
    title: str
    kind: str


@dataclass(frozen=True, slots=True)
class PathwayDef:
    key: str
    title: str
    stages: tuple[StageDef, ...]


@dataclass(frozen=True, slots=True)
class WorkflowDef:
    key: str
    title: str
    pathways: tuple[PathwayDef, ...]
    # Coverage limits the sources record per jurisdiction (e.g. partial coverage).
    limitations: Mapping[str, tuple[str, ...]]

    def pathway(self, key: str) -> PathwayDef | None:
        return next((p for p in self.pathways if p.key == key), None)


@dataclass(frozen=True, slots=True)
class Topic:
    key: str
    title: str
    workflow: str
    pathways: tuple[str, ...]
    # The employer decisions this topic is about (none for an orientation topic).
    options: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Fact:
    """A fact the methodology needs, and where HeroOS may already hold it."""

    key: str
    label: str
    # A CompanyBlueprintContext field (dotted for nested), or None.
    blueprint: str | None
    # A question key of the current workflow definition, or None.
    case_fact: str | None
    # Even when known, it must be confirmed for this Case before it is relied on.
    needs_confirmation: bool
    sensitive: bool


@dataclass(frozen=True, slots=True)
class Unit:
    """One small, traceable piece of Playbook methodology."""

    id: str
    workflow: str
    pathway: str | None
    stage: str | None
    topics: tuple[str, ...]
    scope: Scope
    kind: str
    title: str
    segments: tuple[Segment, ...]
    required_facts: tuple[str, ...]
    guards: tuple[str, ...]
    conditions: tuple[str, ...]
    documents: tuple[str, ...]
    options: tuple[str, ...]
    # Safe to return while the jurisdiction is unresolved (orientation only).
    without_jurisdiction: bool
    status: ItemStatus
    limitations: tuple[str, ...]
    source_ref: SourceRef


@dataclass(frozen=True, slots=True)
class FollowUp:
    action: str
    when: str
    # The source's own wording of when it applies (descriptive, never executed).
    clause: str


@dataclass(frozen=True, slots=True)
class ActionPolicy:
    initial: str
    follow_up: FollowUp | None


@dataclass(frozen=True, slots=True)
class Condition:
    """A Conditions Library row's metadata. The engine evaluates; this describes."""

    id: str
    workflow: str
    scope: Scope
    type: str
    title: str
    segments: tuple[Segment, ...]
    # "withheld": the guidance is superseded in part, so it is never shown.
    guidance_status: str
    trigger: str
    enforcement_status: str
    citation_status: str
    action_policy: ActionPolicy
    required_facts: tuple[str, ...]
    topics: tuple[str, ...]
    stages: tuple[str, ...]
    shared_across: str
    limitations: tuple[str, ...]
    source_ref: SourceRef
    # Every source cell, verbatim (audit only: never returned by a query).
    raw: Mapping[str, str]

    @property
    def participates_in_execution(self) -> bool:
        """Only an active Condition can ever be enforced by the deterministic engine."""
        return self.enforcement_status == "active"

    @property
    def legal_basis_confirmed(self) -> bool:
        """``needs_legal_review`` keeps its action, never its authority."""
        return self.citation_status == "confirmed"


@dataclass(frozen=True, slots=True)
class ItemRef:
    kind: str
    id: str


@dataclass(frozen=True, slots=True)
class Guard:
    """A cross-cutting Implementation Rule, as structured behavior."""

    id: str
    rule: str
    title: str
    kind: str
    workflow: str
    scope: Scope
    topics: tuple[str, ...]
    options: tuple[str, ...]
    required: tuple[str, ...]
    prohibited: tuple[str, ...]
    escalation: str
    supersedes: tuple[ItemRef, ...]
    status: str
    segments: tuple[Segment, ...]
    source_ref: SourceRef


@dataclass(frozen=True, slots=True)
class DocumentJurisdiction:
    status: str
    gates: tuple[str, ...]
    conditions: tuple[str, ...]
    guards: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DocumentReference:
    """What another source says about this document, kept whatever it says."""

    source_id: str
    location: str
    cited_id: str
    cited_title: str
    resolution: str


@dataclass(frozen=True, slots=True)
class Document:
    id: str
    title: str
    kind: str
    workflow: str
    pathway: str | None
    stages: tuple[str, ...]
    options: tuple[str, ...]
    # The jurisdiction the template's own wording is written for.
    body_scope: Scope
    jurisdictions: Mapping[str, DocumentJurisdiction]
    requires_employer_decision: bool
    requires_completed_investigation: bool
    requires_employee_response: bool
    prohibited_when: tuple[str, ...]
    related_conditions: tuple[str, ...]
    segments: tuple[Segment, ...]
    references: tuple[DocumentReference, ...]
    status: ItemStatus
    source_ref: SourceRef


@dataclass(frozen=True, slots=True)
class OptionJurisdiction:
    availability: str
    reason: str
    documents: tuple[str, ...]
    conditions: tuple[str, ...]
    guards: tuple[str, ...]
    required_facts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Option:
    """A possible employer decision the approved content covers (never a recommendation)."""

    id: str
    kind: str
    workflow: str
    pathway: str | None
    title: str
    is_penalty: bool
    requires_completed_investigation: bool
    requires_employee_response: bool
    # Always the employer: the schema has no other value.
    decided_by: Literal["employer"]
    jurisdictions: Mapping[str, OptionJurisdiction]
    units: tuple[str, ...]
    source_refs: tuple[SourceRef, ...]


@dataclass(frozen=True, slots=True)
class ReferenceDataset:
    id: str
    scope: Scope
    title: str
    items: tuple[str, ...]
    citation_status: str
    used_by: tuple[str, ...]
    source_ref: SourceRef


@dataclass(frozen=True, slots=True)
class QuarantineEntry:
    kind: str
    id: str
    reason: str
    finding: str


@dataclass(frozen=True, slots=True)
class EngineLink:
    engine: Literal["intake"]
    rule: str
    condition: str


@dataclass(frozen=True, slots=True)
class Finding:
    id: str
    code: str
    severity: str
    subject: ItemRef
    detail: str
    refs: tuple[SourceRef, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeBundle:
    bundle_id: str
    version: str
    provenance: Provenance
    approval: Approval
    notice: Message | None
    compiler: str
    source_package_digest: str
    runtime_digest: str
    file_sha256: str
    manifest: tuple[ManifestEntry, ...]
    workflows: tuple[WorkflowDef, ...]
    jurisdictions: tuple[str, ...]
    topics: tuple[Topic, ...]
    facts: tuple[Fact, ...]
    units: tuple[Unit, ...]
    conditions: tuple[Condition, ...]
    guards: tuple[Guard, ...]
    documents: tuple[Document, ...]
    options: tuple[Option, ...]
    reference_data: tuple[ReferenceDataset, ...]
    quarantine: tuple[QuarantineEntry, ...]
    engine_links: tuple[EngineLink, ...]
    findings: tuple[Finding, ...]

    def workflow(self, key: str) -> WorkflowDef | None:
        return next((w for w in self.workflows if w.key == key), None)

    def condition(self, condition_id: str) -> Condition | None:
        return next((c for c in self.conditions if c.id == condition_id), None)

    def document(self, document_id: str) -> Document | None:
        return next((d for d in self.documents if d.id == document_id), None)

    def guard(self, guard_id: str) -> Guard | None:
        return next((g for g in self.guards if g.id == guard_id), None)

    def option(self, option_id: str) -> Option | None:
        return next((o for o in self.options if o.id == option_id), None)

    def fact(self, key: str) -> Fact | None:
        return next((f for f in self.facts if f.key == key), None)

    def executable_conditions(self) -> tuple[Condition, ...]:
        """The Conditions the deterministic engine may enforce (active only)."""
        return tuple(c for c in self.conditions if c.participates_in_execution)


# --- jurisdiction leakage --------------------------------------------------------------

# Legal authority of the UAE Federal / MOHRE regime, by name.
_FEDERAL_AUTHORITY: Final = re.compile(
    r"\b(?:Federal\s+Decree-Law|Federal\s+Labou?r\s+Law|UAE\s+Labou?r\s+Law|"
    r"UAE\s+Federal(?:\s+(?:Labou?r|Employment))?\s+(?:Law|law|framework)|Federal\s+law|"
    r"UAE\s+law|Cabinet\s+Resolution|Executive\s+Regulations|implementing\s+regulations|MOHRE)\b",
    re.IGNORECASE,
)
_DIFC_AUTHORITY: Final = re.compile(
    r"\bDIFC\s+(?:Employment\s+Law|law|Courts?|Court\s+decisions?)\b", re.IGNORECASE
)
_ARTICLE: Final = re.compile(r"\bArticles?\s+\d+", re.IGNORECASE)
_DIFC_NAME: Final = re.compile(r"\bDIFC\b")
_FEDERAL_NAME: Final = re.compile(r"\b(?:UAE\s+)?Federal\b|\bMOHRE\b", re.IGNORECASE)
_NEGATION: Final = re.compile(
    r"\b(?:not|never|no|cannot|unlike|instead\s+of|rather\s+than)\b|n't\b", re.IGNORECASE
)
_SENTENCE: Final = re.compile(r"(?<=[.!?])\s+")


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE.split(text) if s.strip()]


def jurisdiction_leaks(scope: str, text: str, *, comparative_allowed: bool = False) -> list[int]:
    """Indexes of the sentences of ``text`` that state another jurisdiction's legal authority.

    - ``shared`` (and ``global``) text is shown in every jurisdiction, so it
      states no regime's legal authority: any article number is a leak, and
      so is a named authority of either regime unless the sentence only says
      it doesn't apply (a negation).
    - ``difc`` text states no UAE Federal authority, ``uae_federal`` text no
      DIFC authority, except to say that it doesn't apply.
    - ``comparative_allowed`` (system rules only, never customer-facing
      text): a sentence naming both regimes ("Article 900 for UAE Federal,
      Article 901 for DIFC") is not a leak.
    """
    leaks: list[int] = []
    for index, sentence in enumerate(sentences(text)):
        negated = _NEGATION.search(sentence) is not None
        both = _DIFC_NAME.search(sentence) is not None and (
            _FEDERAL_NAME.search(sentence) is not None
        )
        if comparative_allowed and both:
            continue
        federal = _FEDERAL_AUTHORITY.search(sentence) is not None
        difc = _DIFC_AUTHORITY.search(sentence) is not None
        if scope in ("shared", "global"):
            leak = _ARTICLE.search(sentence) is not None or ((federal or difc) and not negated)
        elif scope == "difc":
            leak = federal and not negated
        else:
            leak = difc and not negated
        if leak:
            leaks.append(index)
    return leaks


# --- parsing helpers -------------------------------------------------------------------


def _object(
    raw: object, where: str, required: Iterable[str], optional: Iterable[str] = ()
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise KnowledgeBundleError("expected_object", where)
    keys, need, allowed = set(raw), set(required), set(required) | set(optional)
    if not need <= keys:
        raise KnowledgeBundleError("missing_field", where)
    if not keys <= allowed:
        raise KnowledgeBundleError("unknown_field", where)
    return raw


def _str(raw: object, where: str, limit: int = MAX_SHORT, *, allow_empty: bool = False) -> str:
    if (
        not isinstance(raw, str)
        or (not raw.strip() and not allow_empty)
        or len(raw) > limit
        # Source text keeps its no-break spaces; control and format characters are refused.
        or any(not (c.isprintable() or c in "\n\t\u00a0\u202f") for c in raw)
    ):
        raise KnowledgeBundleError("invalid_text", where)
    return raw


def _opt_str(raw: object, where: str, pattern: re.Pattern[str]) -> str | None:
    return None if raw is None else _match(raw, pattern, where)


def _match(raw: object, pattern: re.Pattern[str], where: str) -> str:
    if not isinstance(raw, str) or not pattern.fullmatch(raw):
        raise KnowledgeBundleError("invalid_key", where)
    return raw


def _code(raw: object, allowed: Iterable[str], where: str) -> str:
    if not isinstance(raw, str) or raw not in tuple(allowed):
        raise KnowledgeBundleError("invalid_code", where)
    return raw


def _bool(raw: object, where: str) -> bool:
    if not isinstance(raw, bool):
        raise KnowledgeBundleError("expected_boolean", where)
    return raw


def _int(raw: object, where: str) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise KnowledgeBundleError("expected_integer", where)
    return raw


def _list(raw: object, where: str, limit: int = MAX_ITEMS) -> list[object]:
    if not isinstance(raw, list) or len(raw) > limit:
        raise KnowledgeBundleError("invalid_list", where)
    return raw


def _items[T](raw: object, where: str, parse: Callable[[object, str], T]) -> tuple[T, ...]:
    return tuple(parse(item, f"{where}[{i}]") for i, item in enumerate(_list(raw, where)))


def _ids(raw: object, pattern: re.Pattern[str], where: str) -> tuple[str, ...]:
    values = tuple(
        _match(item, pattern, f"{where}[{i}]") for i, item in enumerate(_list(raw, where))
    )
    if len(set(values)) != len(values):
        raise KnowledgeBundleError("duplicate_reference", where)
    return values


def _codes(raw: object, allowed: Iterable[str], where: str) -> tuple[str, ...]:
    allowed = tuple(allowed)
    values = tuple(
        _code(item, allowed, f"{where}[{i}]") for i, item in enumerate(_list(raw, where))
    )
    if len(set(values)) != len(values):
        raise KnowledgeBundleError("duplicate_reference", where)
    return values


def _scope(raw: object, where: str) -> Scope:
    return _code(raw, SCOPES, where)  # type: ignore[return-value]  # one of SCOPES


def _status(raw: object, where: str) -> ItemStatus:
    return _code(raw, ITEM_STATUSES, where)  # type: ignore[return-value]  # one of ITEM_STATUSES


def _ref(raw: object, where: str) -> SourceRef:
    data = _object(raw, where, ("source_id", "location", "content_sha256"))
    return SourceRef(
        _match(data["source_id"], ID, f"{where}.source_id"),
        _str(data["location"], f"{where}.location"),
        _match(data["content_sha256"], SHA256_HEX, f"{where}.content_sha256"),
    )


def _segment(raw: object, where: str) -> Segment:
    data = _object(raw, where, ("scope", "text"))
    return Segment(_scope(data["scope"], f"{where}.scope"), _str(data["text"], where, MAX_TEXT))


def _segments(raw: object, where: str) -> tuple[Segment, ...]:
    return _items(raw, where, _segment)


def _item_ref(raw: object, where: str) -> ItemRef:
    data = _object(raw, where, ("kind", "id"))
    return ItemRef(_str(data["kind"], f"{where}.kind"), _match(data["id"], ID, f"{where}.id"))


def _message(raw: object, where: str) -> Message:
    data = _object(raw, where, ("title", "body"))
    return Message(_str(data["title"], f"{where}.title"), _str(data["body"], f"{where}.body", 2000))


def _limitations(raw: object, where: str) -> tuple[str, ...]:
    return _ids(raw, LIMITATION, where)


# --- item parsers ----------------------------------------------------------------------


def _manifest(raw: object, where: str) -> ManifestEntry:
    data = _object(
        raw,
        where,
        (
            "source_id", "source_type", "title", "filename", "sha256", "size", "source_version",
            "workflow", "jurisdiction_scope", "runtime_role",
        ),
    )  # fmt: skip
    return ManifestEntry(
        source_id=_match(data["source_id"], ID, f"{where}.source_id"),
        source_type=_code(data["source_type"], SOURCE_TYPES, f"{where}.source_type"),
        title=_str(data["title"], f"{where}.title"),
        filename=_str(data["filename"], f"{where}.filename"),
        sha256=_match(data["sha256"], SHA256_HEX, f"{where}.sha256"),
        size=_int(data["size"], f"{where}.size"),
        source_version=_str(data["source_version"], f"{where}.source_version"),
        workflow=_str(data["workflow"], f"{where}.workflow"),
        jurisdiction_scope=_str(data["jurisdiction_scope"], f"{where}.jurisdiction_scope"),
        runtime_role=_code(data["runtime_role"], RUNTIME_ROLES, f"{where}.runtime_role"),
    )


def _stage(raw: object, where: str) -> StageDef:
    data = _object(raw, where, ("key", "title", "kind"))
    return StageDef(
        _match(data["key"], KEY, f"{where}.key"),
        _str(data["title"], f"{where}.title"),
        _code(data["kind"], STAGE_KINDS, f"{where}.kind"),
    )


def _pathway(raw: object, where: str) -> PathwayDef:
    data = _object(raw, where, ("key", "title", "stages"))
    return PathwayDef(
        _match(data["key"], KEY, f"{where}.key"),
        _str(data["title"], f"{where}.title"),
        _items(data["stages"], f"{where}.stages", _stage),
    )


def _workflow(raw: object, where: str) -> WorkflowDef:
    data = _object(raw, where, ("key", "title", "pathways", "limitations"))
    return WorkflowDef(
        _match(data["key"], KEY, f"{where}.key"),
        _str(data["title"], f"{where}.title"),
        _items(data["pathways"], f"{where}.pathways", _pathway),
        _per_jurisdiction(data["limitations"], f"{where}.limitations", _limitations),
    )


def _topic(raw: object, where: str) -> Topic:
    data = _object(raw, where, ("key", "title", "workflow", "pathways", "options"))
    return Topic(
        _match(data["key"], KEY, f"{where}.key"),
        _str(data["title"], f"{where}.title"),
        _match(data["workflow"], KEY, f"{where}.workflow"),
        _ids(data["pathways"], KEY, f"{where}.pathways"),
        _ids(data["options"], ID, f"{where}.options"),
    )


def _fact(raw: object, where: str) -> Fact:
    data = _object(
        raw, where, ("key", "label", "blueprint", "case_fact", "needs_confirmation", "sensitive")
    )
    return Fact(
        key=_match(data["key"], FACT_KEY, f"{where}.key"),
        label=_str(data["label"], f"{where}.label"),
        blueprint=_opt_str(data["blueprint"], f"{where}.blueprint", FACT_KEY),
        case_fact=_opt_str(data["case_fact"], f"{where}.case_fact", FACT_KEY),
        needs_confirmation=_bool(data["needs_confirmation"], f"{where}.needs_confirmation"),
        sensitive=_bool(data["sensitive"], f"{where}.sensitive"),
    )


def _unit(raw: object, where: str) -> Unit:
    data = _object(
        raw,
        where,
        (
            "id", "workflow", "pathway", "stage", "topics", "scope", "kind", "title", "segments",
            "required_facts", "guards", "conditions", "documents", "options",
            "without_jurisdiction", "status", "limitations", "source_ref",
        ),
    )  # fmt: skip
    return Unit(
        id=_match(data["id"], ID, f"{where}.id"),
        workflow=_match(data["workflow"], KEY, f"{where}.workflow"),
        pathway=_opt_str(data["pathway"], f"{where}.pathway", KEY),
        stage=_opt_str(data["stage"], f"{where}.stage", KEY),
        topics=_ids(data["topics"], KEY, f"{where}.topics"),
        scope=_scope(data["scope"], f"{where}.scope"),
        kind=_code(data["kind"], UNIT_KINDS, f"{where}.kind"),
        title=_str(data["title"], f"{where}.title"),
        segments=_segments(data["segments"], f"{where}.segments"),
        required_facts=_ids(data["required_facts"], FACT_KEY, f"{where}.required_facts"),
        guards=_ids(data["guards"], ID, f"{where}.guards"),
        conditions=_ids(data["conditions"], ID, f"{where}.conditions"),
        documents=_ids(data["documents"], ID, f"{where}.documents"),
        options=_ids(data["options"], ID, f"{where}.options"),
        without_jurisdiction=_bool(data["without_jurisdiction"], f"{where}.without_jurisdiction"),
        status=_status(data["status"], f"{where}.status"),
        limitations=_limitations(data["limitations"], f"{where}.limitations"),
        source_ref=_ref(data["source_ref"], f"{where}.source_ref"),
    )


def _action_policy(raw: object, where: str) -> ActionPolicy:
    data = _object(raw, where, ("initial", "follow_up"))
    follow_up = None
    if data["follow_up"] is not None:
        f = _object(data["follow_up"], f"{where}.follow_up", ("action", "when", "clause"))
        follow_up = FollowUp(
            _code(f["action"], ACTIONS, f"{where}.follow_up.action"),
            _code(f["when"], FOLLOW_UP_WHEN, f"{where}.follow_up.when"),
            _str(f["clause"], f"{where}.follow_up.clause", MAX_TEXT),
        )
    return ActionPolicy(_code(data["initial"], ACTIONS, f"{where}.initial"), follow_up)


def _raw_cells(raw: object, where: str) -> Mapping[str, str]:
    if not isinstance(raw, dict) or len(raw) > 64:
        raise KnowledgeBundleError("expected_object", where)
    return {
        _match(k, KEY, f"{where}.key"): _str(v, f"{where}.{k}", MAX_TEXT, allow_empty=True)
        for k, v in raw.items()
    }


def _condition(raw: object, where: str) -> Condition:
    data = _object(
        raw,
        where,
        (
            "id", "workflow", "scope", "type", "title", "segments", "guidance_status", "trigger",
            "enforcement_status", "citation_status", "action_policy", "required_facts", "topics",
            "stages", "shared_across", "limitations", "source_ref", "raw",
        ),
    )  # fmt: skip
    return Condition(
        id=_match(data["id"], ID, f"{where}.id"),
        workflow=_match(data["workflow"], KEY, f"{where}.workflow"),
        scope=_scope(data["scope"], f"{where}.scope"),
        type=_code(data["type"], CONDITION_TYPES, f"{where}.type"),
        title=_str(data["title"], f"{where}.title"),
        segments=_segments(data["segments"], f"{where}.segments"),
        guidance_status=_code(data["guidance_status"], GUIDANCE_STATUSES, f"{where}.guidance"),
        trigger=_str(data["trigger"], f"{where}.trigger", MAX_TEXT),
        enforcement_status=_code(data["enforcement_status"], ENFORCEMENT, f"{where}.enforcement"),
        citation_status=_code(data["citation_status"], CITATION, f"{where}.citation_status"),
        action_policy=_action_policy(data["action_policy"], f"{where}.action_policy"),
        required_facts=_ids(data["required_facts"], FACT_KEY, f"{where}.required_facts"),
        topics=_ids(data["topics"], KEY, f"{where}.topics"),
        stages=_ids(data["stages"], KEY, f"{where}.stages"),
        shared_across=_str(
            data["shared_across"], f"{where}.shared_across", MAX_TEXT, allow_empty=True
        ),
        limitations=_limitations(data["limitations"], f"{where}.limitations"),
        source_ref=_ref(data["source_ref"], f"{where}.source_ref"),
        raw=_raw_cells(data["raw"], f"{where}.raw"),
    )


def _guard(raw: object, where: str) -> Guard:
    data = _object(
        raw,
        where,
        (
            "id", "rule", "title", "kind", "workflow", "scope", "topics", "options", "required",
            "prohibited", "escalation", "supersedes", "status", "segments", "source_ref",
        ),
    )  # fmt: skip
    return Guard(
        id=_match(data["id"], ID, f"{where}.id"),
        rule=_str(data["rule"], f"{where}.rule", 20),
        title=_str(data["title"], f"{where}.title"),
        kind=_code(data["kind"], GUARD_KINDS, f"{where}.kind"),
        workflow=_match(data["workflow"], KEY, f"{where}.workflow"),
        scope=_scope(data["scope"], f"{where}.scope"),
        topics=_ids(data["topics"], KEY, f"{where}.topics"),
        options=_ids(data["options"], ID, f"{where}.options"),
        required=_codes(data["required"], sorted(REQUIRED_BEHAVIORS), f"{where}.required"),
        prohibited=_codes(data["prohibited"], sorted(PROHIBITED_BEHAVIORS), f"{where}.prohibited"),
        escalation=_code(data["escalation"], ESCALATIONS, f"{where}.escalation"),
        supersedes=_items(data["supersedes"], f"{where}.supersedes", _item_ref),
        status=_code(data["status"], GUARD_STATUSES, f"{where}.status"),
        segments=_segments(data["segments"], f"{where}.segments"),
        source_ref=_ref(data["source_ref"], f"{where}.source_ref"),
    )


def _document_jurisdiction(raw: object, where: str) -> DocumentJurisdiction:
    data = _object(raw, where, ("status", "gates", "conditions", "guards", "limitations"))
    return DocumentJurisdiction(
        status=_code(data["status"], DOCUMENT_STATUSES, f"{where}.status"),
        gates=_ids(data["gates"], FACT_KEY, f"{where}.gates"),
        conditions=_ids(data["conditions"], ID, f"{where}.conditions"),
        guards=_ids(data["guards"], ID, f"{where}.guards"),
        limitations=_limitations(data["limitations"], f"{where}.limitations"),
    )


def _per_jurisdiction[T](
    raw: object, where: str, parse: Callable[[object, str], T]
) -> Mapping[str, T]:
    if not isinstance(raw, dict) or set(raw) != set(JURISDICTIONS):
        # Every supported jurisdiction is stated explicitly: no default applies.
        raise KnowledgeBundleError("jurisdictions_incomplete", where)
    return {code: parse(raw[code], f"{where}.{code}") for code in JURISDICTIONS}


def _document_reference(raw: object, where: str) -> DocumentReference:
    data = _object(raw, where, ("source_id", "location", "cited_id", "cited_title", "resolution"))
    return DocumentReference(
        _match(data["source_id"], ID, f"{where}.source_id"),
        _str(data["location"], f"{where}.location"),
        _str(data["cited_id"], f"{where}.cited_id", 40),
        _str(data["cited_title"], f"{where}.cited_title", allow_empty=True),
        _code(data["resolution"], REFERENCE_RESOLUTIONS, f"{where}.resolution"),
    )


def _document(raw: object, where: str) -> Document:
    data = _object(
        raw,
        where,
        (
            "id", "title", "kind", "workflow", "pathway", "stages", "options", "body_scope",
            "jurisdictions", "requires_employer_decision", "requires_completed_investigation",
            "requires_employee_response", "prohibited_when", "related_conditions", "segments",
            "references", "status", "source_ref",
        ),
    )  # fmt: skip
    return Document(
        id=_match(data["id"], ID, f"{where}.id"),
        title=_str(data["title"], f"{where}.title"),
        kind=_code(data["kind"], DOCUMENT_KINDS, f"{where}.kind"),
        workflow=_match(data["workflow"], KEY, f"{where}.workflow"),
        pathway=_opt_str(data["pathway"], f"{where}.pathway", KEY),
        stages=_ids(data["stages"], KEY, f"{where}.stages"),
        options=_ids(data["options"], ID, f"{where}.options"),
        body_scope=_scope(data["body_scope"], f"{where}.body_scope"),
        jurisdictions=_per_jurisdiction(
            data["jurisdictions"], f"{where}.jurisdictions", _document_jurisdiction
        ),
        requires_employer_decision=_bool(data["requires_employer_decision"], f"{where}.decision"),
        requires_completed_investigation=_bool(
            data["requires_completed_investigation"], f"{where}.investigation"
        ),
        requires_employee_response=_bool(data["requires_employee_response"], f"{where}.response"),
        prohibited_when=_limitations(data["prohibited_when"], f"{where}.prohibited_when"),
        related_conditions=_ids(data["related_conditions"], ID, f"{where}.related_conditions"),
        segments=_segments(data["segments"], f"{where}.segments"),
        references=_items(data["references"], f"{where}.references", _document_reference),
        status=_status(data["status"], f"{where}.status"),
        source_ref=_ref(data["source_ref"], f"{where}.source_ref"),
    )


def _option_jurisdiction(raw: object, where: str) -> OptionJurisdiction:
    data = _object(
        raw,
        where,
        ("availability", "reason", "documents", "conditions", "guards", "required_facts"),
    )
    return OptionJurisdiction(
        availability=_code(data["availability"], AVAILABILITIES, f"{where}.availability"),
        reason=_match(data["reason"], LIMITATION, f"{where}.reason"),
        documents=_ids(data["documents"], ID, f"{where}.documents"),
        conditions=_ids(data["conditions"], ID, f"{where}.conditions"),
        guards=_ids(data["guards"], ID, f"{where}.guards"),
        required_facts=_ids(data["required_facts"], FACT_KEY, f"{where}.required_facts"),
    )


def _option(raw: object, where: str) -> Option:
    data = _object(
        raw,
        where,
        (
            "id", "kind", "workflow", "pathway", "title", "is_penalty",
            "requires_completed_investigation", "requires_employee_response", "decided_by",
            "jurisdictions", "units", "source_refs",
        ),
    )  # fmt: skip
    if data["decided_by"] != "employer":
        raise KnowledgeBundleError("decision_not_employer", f"{where}.decided_by")
    return Option(
        id=_match(data["id"], ID, f"{where}.id"),
        kind=_code(data["kind"], OPTION_KINDS, f"{where}.kind"),
        workflow=_match(data["workflow"], KEY, f"{where}.workflow"),
        pathway=_opt_str(data["pathway"], f"{where}.pathway", KEY),
        title=_str(data["title"], f"{where}.title"),
        is_penalty=_bool(data["is_penalty"], f"{where}.is_penalty"),
        requires_completed_investigation=_bool(
            data["requires_completed_investigation"], f"{where}.investigation"
        ),
        requires_employee_response=_bool(data["requires_employee_response"], f"{where}.response"),
        decided_by="employer",
        jurisdictions=_per_jurisdiction(
            data["jurisdictions"], f"{where}.jurisdictions", _option_jurisdiction
        ),
        units=_ids(data["units"], ID, f"{where}.units"),
        source_refs=_items(data["source_refs"], f"{where}.source_refs", _ref),
    )


def _reference_dataset(raw: object, where: str) -> ReferenceDataset:
    data = _object(
        raw, where, ("id", "scope", "title", "items", "citation_status", "used_by", "source_ref")
    )
    return ReferenceDataset(
        id=_match(data["id"], ID, f"{where}.id"),
        scope=_scope(data["scope"], f"{where}.scope"),
        title=_str(data["title"], f"{where}.title"),
        items=tuple(
            _str(item, f"{where}.items[{i}]", MAX_TEXT)
            for i, item in enumerate(_list(data["items"], f"{where}.items", 100))
        ),
        citation_status=_code(data["citation_status"], CITATION, f"{where}.citation_status"),
        used_by=_ids(data["used_by"], ID, f"{where}.used_by"),
        source_ref=_ref(data["source_ref"], f"{where}.source_ref"),
    )


def _quarantine(raw: object, where: str) -> QuarantineEntry:
    data = _object(raw, where, ("kind", "id", "reason", "finding"))
    return QuarantineEntry(
        _code(data["kind"], QUARANTINE_KINDS, f"{where}.kind"),
        _match(data["id"], ID, f"{where}.id"),
        _match(data["reason"], LIMITATION, f"{where}.reason"),
        _match(data["finding"], ID, f"{where}.finding"),
    )


def _engine_link(raw: object, where: str) -> EngineLink:
    data = _object(raw, where, ("engine", "rule", "condition"))
    if data["engine"] != "intake":
        raise KnowledgeBundleError("unknown_engine", f"{where}.engine")
    return EngineLink(
        "intake",
        _match(data["rule"], KEY, f"{where}.rule"),
        _match(data["condition"], ID, f"{where}.condition"),
    )


def _finding(raw: object, where: str) -> Finding:
    data = _object(raw, where, ("id", "code", "severity", "subject", "detail", "refs"))
    return Finding(
        id=_match(data["id"], ID, f"{where}.id"),
        code=_code(data["code"], FINDING_CODES, f"{where}.code"),
        severity=_code(data["severity"], SEVERITIES, f"{where}.severity"),
        subject=_item_ref(data["subject"], f"{where}.subject"),
        detail=_str(data["detail"], f"{where}.detail", 600),
        refs=_items(data["refs"], f"{where}.refs", _ref),
    )


# --- digests ---------------------------------------------------------------------------


def canonical_json(value: object) -> bytes:
    """The one serialization both digests hash: sorted keys, no whitespace, UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def source_package_digest(manifest: Iterable[Mapping[str, object]]) -> str:
    """SHA-256 identity of the exact source files (id, name, bytes), in id order."""
    entries = sorted(
        ({k: entry[k] for k in ("source_id", "filename", "sha256", "size")} for entry in manifest),
        key=lambda e: str(e["source_id"]),
    )
    return hashlib.sha256(canonical_json(entries)).hexdigest()


def runtime_bundle_digest(runtime: Mapping[str, object]) -> str:
    """SHA-256 identity of the normalized operational knowledge."""
    return hashlib.sha256(canonical_json(runtime)).hexdigest()


# --- references and invariants ---------------------------------------------------------


def _unique(values: Iterable[str], where: str) -> set[str]:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise KnowledgeBundleError("duplicate_id", where)
        seen.add(value)
    return seen


def _known(values: Iterable[str], known: set[str], where: str) -> None:
    if not set(values) <= known:
        raise KnowledgeBundleError("unknown_reference", where)


_BLUEPRINT_FIELDS: Final = frozenset(f.name for f in fields(CompanyBlueprintContext)) | frozenset(
    {"jurisdiction.employment_jurisdiction", "jurisdiction.guidance_allowed"}
)


def _check_references(bundle: KnowledgeBundle) -> None:
    workflows = _unique((w.key for w in bundle.workflows), "runtime.workflows")
    topics = _unique((t.key for t in bundle.topics), "runtime.topics")
    facts = _unique((f.key for f in bundle.facts), "runtime.facts")
    units = _unique((u.id for u in bundle.units), "runtime.units")
    conditions = _unique((c.id for c in bundle.conditions), "runtime.conditions")
    guards = _unique((g.id for g in bundle.guards), "runtime.guards")
    documents = _unique((d.id for d in bundle.documents), "runtime.documents")
    options = _unique((o.id for o in bundle.options), "runtime.options")
    references = _unique((r.id for r in bundle.reference_data), "runtime.reference_data")
    sources = _unique((m.source_id for m in bundle.manifest), "manifest")
    _unique((f.id for f in bundle.findings), "validation.findings")
    if set(bundle.jurisdictions) != set(JURISDICTIONS):
        raise KnowledgeBundleError("jurisdictions_incomplete", "runtime.jurisdictions")
    pathways = {p.key for w in bundle.workflows for p in w.pathways}
    stages = [s.key for w in bundle.workflows for p in w.pathways for s in p.stages]
    _unique(stages, "runtime.workflows.stages")
    stage_set = set(stages)
    operational_sources = {m.source_id for m in bundle.manifest if m.runtime_role == "operational"}

    def ref(r: SourceRef, where: str) -> None:
        # Operational knowledge comes from operational sources only.
        if r.source_id not in operational_sources:
            raise KnowledgeBundleError("source_not_operational", where)

    for t in bundle.topics:
        _known([t.workflow], workflows, f"topic {t.key}")
        _known(t.pathways, pathways, f"topic {t.key}")
        _known(t.options, options, f"topic {t.key}")
    for f in bundle.facts:
        if f.blueprint is not None and f.blueprint not in _BLUEPRINT_FIELDS:
            raise KnowledgeBundleError("unknown_blueprint_field", f"fact {f.key}")
    for u in bundle.units:
        at = f"unit {u.id}"
        _known([u.workflow], workflows, at)
        if u.pathway is not None:
            _known([u.pathway], pathways, at)
        if u.stage is not None:
            _known([u.stage], stage_set, at)
        _known(u.topics, topics, at)
        _known(u.required_facts, facts, at)
        _known(u.guards, guards, at)
        _known(u.conditions, conditions, at)
        _known(u.documents, documents, at)
        _known(u.options, options, at)
        ref(u.source_ref, at)
    for c in bundle.conditions:
        at = f"condition {c.id}"
        _known(c.required_facts, facts, at)
        _known(c.topics, topics, at)
        _known(c.stages, stage_set, at)
        ref(c.source_ref, at)
    for g in bundle.guards:
        at = f"guard {g.id}"
        _known(g.topics, topics, at)
        _known(g.options, options, at)
        for target in g.supersedes:
            if target.kind == "guard":
                _known([target.id], guards, at)
            elif target.kind == "condition":
                _known([target.id], conditions, at)
        ref(g.source_ref, at)
    for d in bundle.documents:
        at = f"document {d.id}"
        _known([d.workflow], workflows, at)
        _known(d.stages, stage_set, at)
        _known(d.options, options, at)
        _known(d.related_conditions, conditions, at)
        for doc_entry in d.jurisdictions.values():
            _known(doc_entry.gates, facts, at)
            _known(doc_entry.conditions, conditions, at)
            _known(doc_entry.guards, guards, at)
        _known((r.source_id for r in d.references), sources, at)
        ref(d.source_ref, at)
    for o in bundle.options:
        at = f"option {o.id}"
        _known([o.workflow], workflows, at)
        if o.pathway is not None:
            _known([o.pathway], pathways, at)
        _known(o.units, units, at)
        for entry in o.jurisdictions.values():
            _known(entry.documents, documents, at)
            _known(entry.conditions, conditions, at)
            _known(entry.guards, guards, at)
            _known(entry.required_facts, facts, at)
        for option_ref in o.source_refs:
            ref(option_ref, at)
    for dataset in bundle.reference_data:
        at = f"reference_data {dataset.id}"
        _known(dataset.used_by, conditions, at)
        ref(dataset.source_ref, at)
    kinds = {
        "unit": units,
        "condition": conditions,
        "document": documents,
        "option": options,
        "reference_data": references,
        "route": topics | options | documents,
    }
    finding_ids = {f.id for f in bundle.findings}
    for q in bundle.quarantine:
        _known([q.id], kinds[q.kind], f"quarantine {q.kind} {q.id}")
        _known([q.finding], finding_ids, f"quarantine {q.kind} {q.id}")


def _check_leakage(bundle: KnowledgeBundle) -> None:
    def text(segments: Iterable[Segment], where: str, *, system: bool = False) -> None:
        for index, segment in enumerate(segments):
            if jurisdiction_leaks(segment.scope, segment.text, comparative_allowed=system):
                raise KnowledgeBundleError("jurisdiction_leakage", f"{where}.segments[{index}]")

    for u in bundle.units:
        text(u.segments, f"unit {u.id}")
        if u.without_jurisdiction and (
            u.scope not in ("shared", "global") or u.kind == "legal_reference"
        ):
            raise KnowledgeBundleError("unsafe_without_jurisdiction", f"unit {u.id}")
        # Shared methodology may carry jurisdiction-labelled passages (each shown
        # only in its jurisdiction); a jurisdiction's own unit carries no other's.
        if u.scope not in ("shared", "global") and any(
            s.scope not in ("shared", "global", u.scope) for s in u.segments
        ):
            raise KnowledgeBundleError("segment_outside_scope", f"unit {u.id}")
    for c in bundle.conditions:
        text(c.segments, f"condition {c.id}")
    for g in bundle.guards:
        text(g.segments, f"guard {g.id}", system=True)
    for d in bundle.documents:
        text(d.segments, f"document {d.id}")
    for r in bundle.reference_data:
        for index, item in enumerate(r.items):
            if jurisdiction_leaks(r.scope, item):
                raise KnowledgeBundleError(
                    "jurisdiction_leakage", f"reference_data {r.id}[{index}]"
                )


def _check_invariants(bundle: KnowledgeBundle) -> None:
    guards = {g.id: g for g in bundle.guards}
    documents = {d.id: d for d in bundle.documents}
    rank = {"supported": 2, "review_required": 1, "not_available": 0}
    doc_rank = {
        "eligible_with_gates": 2, "review_required": 1, "expert_review_required": 1,
        "not_available": 0, "quarantined": 0,
    }  # fmt: skip

    def expert_guarded(entry: OptionJurisdiction) -> bool:
        return any(
            guards[g].kind == "expert_review_mandatory"
            and guards[g].status == "operational"
            and guards[g].escalation == "human_expert_review"
            for g in entry.guards
        )

    kinds: dict[str, list[Option]] = {}
    for option in bundle.options:
        at = f"option {option.id}"
        kinds.setdefault(option.kind, []).append(option)
        if option.kind in PENALTY_KINDS and not option.requires_employee_response:
            raise KnowledgeBundleError("penalty_without_employee_response", at)
        if option.kind in INVESTIGATION_FIRST_KINDS and not option.requires_completed_investigation:
            raise KnowledgeBundleError("outcome_without_investigation", at)
        if option.kind in NEVER_SUPPORTED and any(
            e.availability == "supported" for e in option.jurisdictions.values()
        ):
            raise KnowledgeBundleError("option_must_not_be_supported", at)
        if option.kind == "salary_deduction":
            for code, entry in option.jurisdictions.items():
                if entry.availability != "review_required" or not expert_guarded(entry):
                    raise KnowledgeBundleError("deduction_without_expert_review", f"{at}.{code}")
                if entry.documents:
                    raise KnowledgeBundleError("deduction_with_document", f"{at}.{code}")
        if option.kind in DIFC_EXPERT_REVIEW:
            difc = option.jurisdictions["difc"]
            if difc.availability != "review_required" or not expert_guarded(difc):
                raise KnowledgeBundleError("difc_expert_review_missing", at)
        if option.kind == "investigative_suspension" and option.is_penalty:
            raise KnowledgeBundleError("investigative_suspension_is_not_a_penalty", at)
        if option.kind == "disciplinary_suspension_unpaid" and not option.is_penalty:
            raise KnowledgeBundleError("disciplinary_suspension_is_a_penalty", at)
        if option.kind == "dismissal_without_notice":
            first = [
                g for g in bundle.guards
                if option.id in g.options and g.kind == "investigation_first"
                and g.status == "operational"
            ]  # fmt: skip
            if not first:
                raise KnowledgeBundleError("dismissal_without_investigation_guard", at)
        for code, entry in option.jurisdictions.items():
            for doc_id in entry.documents:
                doc = documents[doc_id].jurisdictions[code]
                if doc_rank[doc.status] > rank[entry.availability]:
                    raise KnowledgeBundleError("document_more_available_than_option", at)
    for document in bundle.documents:
        served = [o for o in bundle.options if o.id in document.options]
        for code, doc_entry in document.jurisdictions.items():
            for option in served:
                if doc_rank[doc_entry.status] > rank[option.jurisdictions[code].availability]:
                    raise KnowledgeBundleError(
                        "document_more_available_than_option", f"document {document.id}.{code}"
                    )
            if document.body_scope not in ("shared", "global", code) and doc_entry.status not in (
                "not_available", "expert_review_required", "quarantined",
            ):  # fmt: skip
                # A template written for another regime is never offered here.
                raise KnowledgeBundleError(
                    "document_body_other_jurisdiction", f"document {document.id}"
                )
    inv_docs = {
        d for o in kinds.get("investigative_suspension", []) for e in o.jurisdictions.values()
        for d in e.documents
    }  # fmt: skip
    dis_docs = {
        d for o in kinds.get("disciplinary_suspension_unpaid", []) for e in o.jurisdictions.values()
        for d in e.documents
    }  # fmt: skip
    if inv_docs & dis_docs:
        raise KnowledgeBundleError("suspension_documents_shared", "options")
    operational = {g.kind for g in bundle.guards if g.status == "operational"}
    if bundle.workflow("disciplinary") is not None and not operational >= REQUIRED_GUARD_KINDS:
        raise KnowledgeBundleError("required_guard_missing", "runtime.guards")
    for option_kind in (
        "salary_deduction",
        "dismissal_without_notice",
        "disciplinary_suspension_unpaid",
    ):
        if bundle.workflow("disciplinary") is not None and option_kind not in kinds:
            raise KnowledgeBundleError("required_option_missing", option_kind)


def _check_engine_links(bundle: KnowledgeBundle) -> None:
    """The knowledge describes the deterministic rules; it must agree with them."""
    conditions = {c.id: c for c in bundle.conditions}
    linked: set[str] = set()
    for link in bundle.engine_links:
        at = f"engine_links {link.rule}"
        ruleset = RULESETS.get("disciplinary")
        rule = (
            None
            if ruleset is None
            else next((r for r in ruleset.rules if r.key == link.rule), None)
        )
        condition = conditions.get(link.condition)
        if rule is None or condition is None:
            raise KnowledgeBundleError("unknown_engine_rule", at)
        if link.rule in linked:
            raise KnowledgeBundleError("duplicate_engine_rule", at)
        linked.add(link.rule)
        if not condition.participates_in_execution:
            raise KnowledgeBundleError("not_enforced_condition_linked", at)
        if rule.action != condition.action_policy.initial or not rule.enforced:
            raise KnowledgeBundleError("engine_action_mismatch", at)
        if rule.provisional == condition.legal_basis_confirmed:
            raise KnowledgeBundleError("engine_review_status_mismatch", at)
        scope = (
            "global"
            if not rule.applies_in
            else (rule.applies_in[0] if len(rule.applies_in) == 1 else "shared")
        )
        if scope != condition.scope:
            raise KnowledgeBundleError("engine_jurisdiction_mismatch", at)


def _check_facts(bundle: KnowledgeBundle) -> None:
    definition = current_definition("disciplinary")
    questions = {} if definition is None else {
        q.key: q for step in definition.steps for q in step.questions
    }  # fmt: skip
    for fact in bundle.facts:
        if fact.case_fact is None:
            continue
        question = questions.get(fact.case_fact)
        if question is None:
            raise KnowledgeBundleError("unknown_case_fact", f"fact {fact.key}")
        if question.sensitive != fact.sensitive:
            raise KnowledgeBundleError("sensitivity_mismatch", f"fact {fact.key}")


# --- loading ---------------------------------------------------------------------------


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise KnowledgeBundleError("duplicate_json_key")
        data[key] = value
    return data


def _no_constants(name: str) -> object:
    raise KnowledgeBundleError("invalid_json_number")


RUNTIME_FIELDS: Final = (
    "workflows", "jurisdictions", "topics", "facts", "units", "conditions", "guards",
    "documents", "options", "reference_data", "quarantine", "engine_links",
)  # fmt: skip


def parse_knowledge_bundle(content: bytes, *, file_sha256: str) -> KnowledgeBundle:
    """Validate a bundle's bytes: schema, digests, references, invariants and engine links."""
    if len(content) > MAX_BUNDLE_BYTES:
        raise KnowledgeBundleError("too_large")
    try:
        raw = json.loads(
            content.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constants
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise KnowledgeBundleError("invalid_json") from error
    data = _object(
        raw,
        "$",
        (
            "schema", "bundle", "version", "provenance", "approval", "notice", "compiler",
            "source_package_digest", "runtime_bundle_digest", "manifest", "compiler_inputs",
            "runtime", "validation",
        ),
    )  # fmt: skip
    if data["schema"] != SCHEMA:
        raise KnowledgeBundleError("unsupported_schema", "$.schema")
    provenance = _code(data["provenance"], ("synthetic", "private"), "$.provenance")
    approval = _code(data["approval"], ("development", "approved"), "$.approval")
    notice = None if data["notice"] is None else _message(data["notice"], "$.notice")
    if provenance == "synthetic" and notice is None:
        raise KnowledgeBundleError("synthetic_without_notice", "$.notice")
    manifest_raw = _list(data["manifest"], "$.manifest", 64)
    manifest = _items(manifest_raw, "$.manifest", _manifest)
    for i, entry in enumerate(_list(data["compiler_inputs"], "$.compiler_inputs", 8)):
        e = _object(entry, f"$.compiler_inputs[{i}]", ("name", "sha256"))
        _match(e["name"], KEY, f"$.compiler_inputs[{i}].name")
        _match(e["sha256"], SHA256_HEX, f"$.compiler_inputs[{i}].sha256")
    source_digest = _match(data["source_package_digest"], SHA256_HEX, "$.source_package_digest")
    if not hmac.compare_digest(source_package_digest(manifest_raw), source_digest):  # type: ignore[arg-type]  # checked objects
        raise KnowledgeBundleError("source_package_digest_mismatch", "$.source_package_digest")
    runtime = _object(data["runtime"], "$.runtime", RUNTIME_FIELDS)
    runtime_digest = _match(data["runtime_bundle_digest"], SHA256_HEX, "$.runtime_bundle_digest")
    if not hmac.compare_digest(runtime_bundle_digest(runtime), runtime_digest):
        raise KnowledgeBundleError("runtime_bundle_digest_mismatch", "$.runtime_bundle_digest")
    validation = _object(data["validation"], "$.validation", ("findings", "counts"))
    if not isinstance(validation["counts"], dict):
        raise KnowledgeBundleError("expected_object", "$.validation.counts")
    jurisdictions = _list(runtime["jurisdictions"], "$.runtime.jurisdictions", 8)
    bundle = KnowledgeBundle(
        bundle_id=_match(data["bundle"], BUNDLE_ID, "$.bundle"),
        version=_match(data["version"], VERSION, "$.version"),
        provenance=provenance,  # type: ignore[arg-type]  # checked above
        approval=approval,  # type: ignore[arg-type]  # checked above
        notice=notice,
        compiler=_str(data["compiler"], "$.compiler", 40),
        source_package_digest=source_digest,
        runtime_digest=runtime_digest,
        file_sha256=file_sha256,
        manifest=manifest,
        workflows=_items(runtime["workflows"], "$.runtime.workflows", _workflow),
        jurisdictions=tuple(
            _code(j, JURISDICTIONS, f"$.runtime.jurisdictions[{i}]")
            for i, j in enumerate(jurisdictions)
        ),
        topics=_items(runtime["topics"], "$.runtime.topics", _topic),
        facts=_items(runtime["facts"], "$.runtime.facts", _fact),
        units=_items(runtime["units"], "$.runtime.units", _unit),
        conditions=_items(runtime["conditions"], "$.runtime.conditions", _condition),
        guards=_items(runtime["guards"], "$.runtime.guards", _guard),
        documents=_items(runtime["documents"], "$.runtime.documents", _document),
        options=_items(runtime["options"], "$.runtime.options", _option),
        reference_data=_items(
            runtime["reference_data"], "$.runtime.reference_data", _reference_dataset
        ),
        quarantine=_items(runtime["quarantine"], "$.runtime.quarantine", _quarantine),
        engine_links=_items(runtime["engine_links"], "$.runtime.engine_links", _engine_link),
        findings=_items(validation["findings"], "$.validation.findings", _finding),
    )
    _check_references(bundle)
    _check_leakage(bundle)
    _check_invariants(bundle)
    _check_engine_links(bundle)
    _check_facts(bundle)
    return bundle


def load_knowledge_bundle(path: Path, expected_sha256: str, *, production: bool) -> KnowledgeBundle:
    """Read, verify against the pin, validate. Raises ``KnowledgeBundleError``; never falls back."""
    if not SHA256_HEX.fullmatch(expected_sha256):
        raise KnowledgeBundleError("invalid_pin")
    try:
        with path.open("rb") as handle:
            content = handle.read(MAX_BUNDLE_BYTES + 1)
    except OSError as error:
        raise KnowledgeBundleError("unreadable") from error
    if len(content) > MAX_BUNDLE_BYTES:
        raise KnowledgeBundleError("too_large")
    actual = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(actual, expected_sha256):
        raise KnowledgeBundleError("checksum_mismatch")
    bundle = parse_knowledge_bundle(content, file_sha256=actual)
    if production and bundle.provenance == "synthetic":
        raise KnowledgeBundleError("synthetic_in_production")
    if production and bundle.approval != "approved":
        raise KnowledgeBundleError("unapproved_in_production")
    return bundle
