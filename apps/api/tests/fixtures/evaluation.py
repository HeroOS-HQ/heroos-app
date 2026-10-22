"""Fictional execution content for the deterministic conversation evaluation (M2-NEW-06).

Nothing here is HeroOS content. It extends the fictional knowledge package
(``tests.fixtures.knowledge.synthetic``) at test time with:

- conversation rules for its Disciplinary workflow (a fictional suspension
  cap of 9 days that warns first and blocks once the employer insists, a
  caution about the employee's chance to explain, and mandatory
  prerequisites for a suspension and a warning), added to the synthetic rule
  bundle in memory. M2-NEW-08: the fictional penalty notice's prerequisites
  read the Case's formal record instead (a completed meeting or check-in
  stage, and that stage's checklist answer that the employee was heard), so
  only the employer's own Case steps can satisfy them;
- a second, invented workflow, ``synthetic_probation`` ("Trial period
  review"), structurally unlike Disciplinary: no pathways, its own facts,
  definition and rule bundle, a number-against-a-number rule, a
  number-against-another-number rule, a two-state caution, an escalation
  and a condition-specific follow-up. It proves the evaluator core knows no
  workflow by name;
- an execution profile pairing all of it, by digest.
"""

import hashlib
import json
from copy import deepcopy
from typing import Any, Final

from app.evaluation.continuation import ContinuationCodec
from app.evaluation.evaluator import ConversationEvaluationService
from app.evaluation.profile import ExecutionProfile, parse_execution_profile
from app.evaluation.snapshot import ExecutionRuntime, ExecutionSnapshot, build_snapshot
from app.knowledge.bundle import KnowledgeBundle, parse_knowledge_bundle, runtime_bundle_digest
from app.workflows.conditions import DISCIPLINARY_INTAKE
from app.workflows.definition import WORKFLOWS, Question, Step, WorkflowDefinition
from app.workflows.progression.bundle import RuleBundle, parse_bundle
from app.workflows.progression.spec import ProgressionSpec
from tests.fixtures import SYNTHETIC_BUNDLE

PROBATION: Final = "synthetic_probation"
KEY: Final = b"k" * 32
FICTIONAL_CAP: Final = 9

PROBATION_DEFINITION: Final = WorkflowDefinition(
    key=PROBATION,
    version=1,
    title="Trial period review (synthetic)",
    case_type=PROBATION,
    welcome_title="[SYNTHETIC] Trial period review",
    welcome="[SYNTHETIC] A fictional workflow for tests.",
    steps=(
        Step(
            key="trial_notes",
            title="Notes",
            intro="[SYNTHETIC]",
            questions=(Question(key="trial.notes", kind="text", prompt="Notes?", label="Notes"),),
        ),
    ),
    not_available=(),
)
PROBATION_SPEC: Final = ProgressionSpec(PROBATION, (), ())
DEFINITIONS: Final = {**WORKFLOWS, PROBATION: PROBATION_DEFINITION}


def _message(title: str) -> dict[str, str]:
    return {"title": title, "body": f"[SYNTHETIC] {title}: a fictional rule for tests."}


def _rule(
    key: str,
    action: str,
    form: str,
    predicate: dict[str, Any],
    *,
    provisional: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "key": key,
        "action": action,
        form: predicate,
        "provisional": provisional,
        "message": _message(key.replace("_", " ").capitalize()),
        **extra,
    }


def _yes(fact: str) -> dict[str, Any]:
    return {"answer": fact, "in": ["yes"]}


# --- Disciplinary: conversation rules on the synthetic rule bundle ---------------------------

# The synthetic progression's own stages and checklists (tests/fixtures/rule_bundles).
CASE_INVESTIGATION: Final[dict[str, Any]] = {
    "any": [{"stage_completed": "test_meeting"}, {"stage_completed": "test_check_in"}]
}
CASE_RESPONSE: Final[dict[str, Any]] = {
    "any": [
        _yes("progress.test_meeting.meeting_held"),
        _yes("progress.test_check_in.employee_heard"),
    ]
}

DISCIPLINARY_CONVERSATION: Final[dict[str, Any]] = {
    "facts": [
        {"key": "proposed_suspension_days", "kind": "count", "max": 365},
        {"key": "given_opportunity_to_explain", "kind": "yes_no"},
        {"key": "investigation_completed", "kind": "yes_no"},
    ],
    "jurisdictions": {
        "uae_federal": {
            "rules": [
                _rule(
                    "fictional_cap",
                    "warn",
                    "when",
                    {"compare": "proposed_suspension_days", "op": "gt", "value": FICTIONAL_CAP},
                    follow_up={"action": "block", "when": "employer_insists"},
                ),
                _rule(
                    "heard_before_warning", "warn", "require", _yes("given_opportunity_to_explain")
                ),
            ],
            "actions": [
                {
                    "action": "opt-suspension",
                    "rules": [
                        _rule(
                            "suspension_response",
                            "block",
                            "require",
                            _yes("given_opportunity_to_explain"),
                        ),
                        _rule(
                            "suspension_investigation",
                            "block",
                            "require",
                            _yes("investigation_completed"),
                        ),
                    ],
                },
                {
                    "action": "opt-warning",
                    "rules": [
                        _rule(
                            "warning_response",
                            "block",
                            "require",
                            _yes("given_opportunity_to_explain"),
                        ),
                    ],
                },
                {
                    # M2-NEW-08: prerequisites only the Case's own record establishes.
                    "action": "opt-outcome",
                    "rules": [
                        _rule("outcome_investigation", "block", "require", CASE_INVESTIGATION),
                        _rule("outcome_response", "block", "require", CASE_RESPONSE),
                    ],
                },
            ],
        },
        "difc": {
            "rules": [],
            "actions": [
                {
                    "action": "opt-warning",
                    "rules": [
                        _rule(
                            "warning_response",
                            "block",
                            "require",
                            _yes("given_opportunity_to_explain"),
                        ),
                    ],
                },
            ],
        },
    },
}


def disciplinary_rule_bundle(conversation: dict[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SYNTHETIC_BUNDLE.read_bytes())
    data["conversation"] = deepcopy(
        DISCIPLINARY_CONVERSATION if conversation is None else conversation
    )
    return data


# --- the second, fictional workflow --------------------------------------------------------

PROBATION_FACTS: Final = [
    ("trial_days_completed", "Trial days completed"),
    ("trial_days_allowed", "Trial days allowed"),
    ("extension_days_requested", "Extension days requested"),
    ("review_meeting_held", "Review meeting held"),
    ("concerns_documented", "Concerns documented"),
]


def _ref(source: str) -> dict[str, str]:
    return {"source_id": source, "location": "fictional", "content_sha256": "0" * 64}


def _condition(
    cid: str,
    scope: str,
    kind: str,
    action: str,
    *,
    topics: list[str],
    facts: list[str],
    citation: str = "confirmed",
    enforcement: str = "active",
    follow_up: dict[str, str] | None = None,
    source: str,
) -> dict[str, Any]:
    return {
        "id": cid,
        "workflow": PROBATION,
        "scope": scope,
        "type": kind,
        "title": f"Example trial condition {cid}",
        "segments": [{"scope": "shared", "text": f"[SYNTHETIC] Guidance for {cid}."}],
        "guidance_status": "available",
        "trigger": f"fictional trigger for {cid}",
        "enforcement_status": enforcement,
        "citation_status": citation,
        "action_policy": {"initial": action, "follow_up": follow_up},
        "required_facts": facts,
        "topics": topics,
        "stages": [],
        "shared_across": "",
        "limitations": [],
        "source_ref": _ref(source),
        "raw": {},
    }


def _option(
    oid: str,
    kind: str,
    title: str,
    *,
    conditions: list[str],
    facts: list[str],
    penalty: bool = False,
) -> dict[str, Any]:
    entry = {
        "availability": "supported",
        "reason": "fictional",
        "documents": [],
        "conditions": conditions,
        "guards": [],
        "required_facts": facts,
    }
    return {
        "id": oid,
        "kind": kind,
        "workflow": PROBATION,
        "pathway": None,
        "title": title,
        "is_penalty": penalty,
        "requires_completed_investigation": False,
        "requires_employee_response": penalty,
        "decided_by": "employer",
        "jurisdictions": {"uae_federal": entry, "difc": deepcopy(entry)},
        "units": [],
        "source_refs": [],
    }


def with_probation(data: dict[str, Any]) -> dict[str, Any]:
    """The fictional knowledge package plus the fictional second workflow (digest recomputed)."""
    data = deepcopy(data)
    runtime = data["runtime"]
    source = next(
        m["source_id"]
        for m in data["manifest"]
        if m["runtime_role"] == "operational" and m["source_type"] == "playbook"
    )
    runtime["workflows"].append(
        {
            "key": PROBATION,
            "title": "Trial period review",
            "pathways": [],
            "limitations": {"uae_federal": [], "difc": []},
        }
    )
    runtime["topics"] += [
        {
            "key": "trial_review",
            "title": "Trial review",
            "workflow": PROBATION,
            "pathways": [],
            "options": ["sp-confirm"],
        },
        {
            "key": "trial_extension",
            "title": "Extending a trial",
            "workflow": PROBATION,
            "pathways": [],
            "options": ["sp-extend"],
        },
        {
            "key": "trial_end",
            "title": "Ending a trial",
            "workflow": PROBATION,
            "pathways": [],
            "options": ["sp-end"],
        },
    ]
    runtime["facts"] += [
        {
            "key": key,
            "label": label,
            "blueprint": None,
            "case_fact": None,
            "needs_confirmation": False,
            "sensitive": False,
        }
        for key, label in PROBATION_FACTS
    ]
    runtime["units"] += [
        {
            "id": f"SP-U{index}",
            "workflow": PROBATION,
            "pathway": None,
            "stage": None,
            "topics": topics,
            "scope": "shared",
            "kind": "methodology" if topics else "orientation",
            "title": f"Example trial guidance {index}",
            "segments": [{"scope": "shared", "text": f"[SYNTHETIC] Trial methodology {index}."}],
            "required_facts": facts,
            "guards": [],
            "conditions": [],
            "documents": [],
            "options": options,
            "without_jurisdiction": not topics,
            "status": "operational",
            "limitations": [],
            "source_ref": _ref(source),
        }
        for index, topics, facts, options in (
            (1, [], [], []),
            (2, ["trial_review"], ["trial_days_completed"], ["sp-confirm"]),
            (3, ["trial_extension"], ["extension_days_requested"], ["sp-extend"]),
            (4, ["trial_end"], ["review_meeting_held"], ["sp-end"]),
        )
    ]
    runtime["conditions"] += [
        _condition(
            "SP-EXTENSION-CAP",
            "shared",
            "step_caution",
            "warn",
            topics=["trial_extension"],
            facts=["extension_days_requested"],
            follow_up={
                "action": "block",
                "when": "employer_insists",
                "clause": "fictional: block if the employer insists",
            },
            source=source,
        ),
        _condition(
            "SP-TRIAL-OVERRUN",
            "shared",
            "blocking",
            "block",
            topics=["trial_extension", "trial_end"],
            facts=["trial_days_completed", "trial_days_allowed"],
            source=source,
        ),
        _condition(
            "SP-CONCERNS",
            "shared",
            "blocking",
            "escalate",
            topics=["trial_end"],
            facts=["concerns_documented"],
            citation="needs_legal_review",
            source=source,
        ),
        _condition(
            "SP-MEETING",
            "shared",
            "step_caution",
            "warn",
            topics=["trial_end"],
            facts=["review_meeting_held", "concerns_documented"],
            follow_up={
                "action": "escalate",
                "when": "condition_specific",
                "clause": "fictional: escalate if concerns aren't documented",
            },
            source=source,
        ),
        _condition(
            "SP-OLD",
            "shared",
            "step_caution",
            "warn",
            topics=["trial_end"],
            facts=["review_meeting_held"],
            enforcement="not_enforced",
            source=source,
        ),
    ]
    runtime["options"] += [
        _option("sp-confirm", "no_action", "Confirming the employment", conditions=[], facts=[]),
        _option(
            "sp-extend",
            "informal_resolution",
            "Extending the trial",
            conditions=["SP-EXTENSION-CAP", "SP-TRIAL-OVERRUN"],
            facts=["extension_days_requested"],
        ),
        _option(
            "sp-end",
            "ordinary_termination",
            "Ending the employment during the trial",
            conditions=["SP-TRIAL-OVERRUN", "SP-CONCERNS", "SP-MEETING", "SP-OLD"],
            facts=["review_meeting_held", "concerns_documented"],
            penalty=True,
        ),
    ]
    data["runtime_bundle_digest"] = runtime_bundle_digest(runtime)
    return data


def _probation_rules() -> list[dict[str, Any]]:
    return [
        _rule(
            "extension_within_limit",
            "warn",
            "when",
            {"compare": "extension_days_requested", "op": "gt", "value": 45},
            follow_up={"action": "block", "when": "employer_insists"},
        ),
        _rule(
            "trial_not_overrun",
            "block",
            "when",
            {"compare": "trial_days_completed", "op": "gt", "field": "trial_days_allowed"},
        ),
        _rule(
            "concerns_on_record",
            "escalate",
            "when",
            {"answer": "concerns_documented", "in": ["no"]},
            provisional=True,
        ),
        _rule(
            "review_meeting",
            "warn",
            "require",
            _yes("review_meeting_held"),
            follow_up={
                "action": "escalate",
                "when": "condition_specific",
                "if": {"answer": "concerns_documented", "in": ["no"]},
            },
        ),
    ]


def probation_rule_bundle() -> dict[str, Any]:
    program = {
        "rules": _probation_rules(),
        "actions": [
            {
                "action": "sp-end",
                "rules": [
                    _rule("end_needs_meeting", "block", "require", _yes("review_meeting_held"))
                ],
            },
        ],
    }
    return {
        "schema": "heroos.rule-bundle/1",
        "bundle": "synthetic-trial",
        "version": "synthetic.1",
        "provenance": "synthetic",
        "workflow": PROBATION,
        "definition_versions": [1],
        "notice": _message("Synthetic trial rules"),
        "jurisdictions": {"uae_federal": {"pathways": []}, "difc": {"pathways": []}},
        "conversation": {
            "facts": [
                {"key": "trial_days_completed", "kind": "count", "max": 2000},
                {"key": "trial_days_allowed", "kind": "count", "max": 2000},
                {"key": "extension_days_requested", "kind": "count", "max": 2000},
                {"key": "review_meeting_held", "kind": "yes_no"},
                {"key": "concerns_documented", "kind": "yes_no"},
            ],
            "jurisdictions": {"uae_federal": deepcopy(program), "difc": deepcopy(program)},
        },
    }


# --- the profile ---------------------------------------------------------------------------


def _digest(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def profile_data(
    knowledge_digest: str, disciplinary: dict[str, Any], probation: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema": "heroos.execution-profile/1",
        "profile": "synthetic-execution",
        "version": "synthetic.1",
        "provenance": "synthetic",
        "approval": "development",
        "workflows": [
            {
                "workflow": "disciplinary",
                "knowledge_runtime_digest": knowledge_digest,
                "definition_version": WORKFLOWS["disciplinary"].version,
                "rule_bundle": {
                    "bundle": disciplinary["bundle"],
                    "version": disciplinary["version"],
                    "digest": _digest(disciplinary),
                },
                "executors": [
                    {
                        "executor": "intake",
                        "version": DISCIPLINARY_INTAKE.version,
                        "digest": DISCIPLINARY_INTAKE.digest,
                    },
                    {"executor": "rule_bundle"},
                ],
                "pathway_ownership": "employer_confirmation_required",
                "bindings": [
                    {
                        "condition": "EX-FED-POLICY",
                        "executor": "intake",
                        "rule": "policy_awareness",
                    },
                    {"condition": "EX-FED-CAP", "executor": "rule_bundle", "rule": "fictional_cap"},
                    {
                        "condition": "EX-FED-WARNING-LABEL",
                        "executor": "rule_bundle",
                        "rule": "heard_before_warning",
                    },
                ],
                "covered_actions": [
                    {"action": "opt-none", "prerequisites": {}},
                    {"action": "opt-investigative", "prerequisites": {}},
                    {
                        "action": "opt-warning",
                        "prerequisites": {"employee_response": "warning_response"},
                    },
                    {
                        "action": "opt-suspension",
                        "prerequisites": {
                            "employee_response": "suspension_response",
                            "completed_investigation": "suspension_investigation",
                        },
                    },
                    {
                        "action": "opt-outcome",
                        "prerequisites": {
                            "employee_response": "outcome_response",
                            "completed_investigation": "outcome_investigation",
                        },
                    },
                ],
            },
            {
                "workflow": PROBATION,
                "knowledge_runtime_digest": knowledge_digest,
                "definition_version": 1,
                "rule_bundle": {
                    "bundle": probation["bundle"],
                    "version": probation["version"],
                    "digest": _digest(probation),
                },
                "executors": [{"executor": "rule_bundle"}],
                "pathway_ownership": "none",
                "bindings": [
                    {
                        "condition": "SP-EXTENSION-CAP",
                        "executor": "rule_bundle",
                        "rule": "extension_within_limit",
                    },
                    {
                        "condition": "SP-TRIAL-OVERRUN",
                        "executor": "rule_bundle",
                        "rule": "trial_not_overrun",
                    },
                    {
                        "condition": "SP-CONCERNS",
                        "executor": "rule_bundle",
                        "rule": "concerns_on_record",
                    },
                    {
                        "condition": "SP-MEETING",
                        "executor": "rule_bundle",
                        "rule": "review_meeting",
                    },
                ],
                "covered_actions": [
                    {"action": "sp-confirm", "prerequisites": {}},
                    {"action": "sp-extend", "prerequisites": {}},
                    {
                        "action": "sp-end",
                        "prerequisites": {"employee_response": "end_needs_meeting"},
                    },
                ],
            },
        ],
    }


def to_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, indent=2).encode()


def knowledge(data: dict[str, Any]) -> KnowledgeBundle:
    content = to_bytes(data)
    return parse_knowledge_bundle(content, file_sha256=hashlib.sha256(content).hexdigest())


def rule_bundle(data: dict[str, Any]) -> RuleBundle:
    content = to_bytes(data)
    sha = hashlib.sha256(content).hexdigest()
    if data["workflow"] == PROBATION:
        return parse_bundle(
            content, file_sha256=sha, definition=PROBATION_DEFINITION, spec=PROBATION_SPEC
        )
    return parse_bundle(content, file_sha256=sha)


def profile(data: dict[str, Any]) -> ExecutionProfile:
    content = to_bytes(data)
    return parse_execution_profile(content, file_sha256=hashlib.sha256(content).hexdigest())


class Artifacts:
    """The fictional artifacts as data, so a test can change one and rebuild."""

    def __init__(self, bundle_data: dict[str, Any]) -> None:
        self.knowledge = with_probation(bundle_data)
        self.disciplinary = disciplinary_rule_bundle()
        self.probation = probation_rule_bundle()
        self.profile = profile_data(
            self.knowledge["runtime_bundle_digest"], self.disciplinary, self.probation
        )

    def repin(self) -> None:
        """Re-pin the profile to the artifacts as they are now (after a deliberate change)."""
        self.knowledge["runtime_bundle_digest"] = runtime_bundle_digest(self.knowledge["runtime"])
        for entry in self.profile["workflows"]:
            entry["knowledge_runtime_digest"] = self.knowledge["runtime_bundle_digest"]
            rules = self.disciplinary if entry["workflow"] == "disciplinary" else self.probation
            entry["rule_bundle"]["digest"] = _digest(rules)

    def snapshot(self) -> ExecutionSnapshot:
        return build_snapshot(
            knowledge(self.knowledge),
            profile(self.profile),
            {
                "disciplinary": rule_bundle(self.disciplinary),
                PROBATION: rule_bundle(self.probation),
            },
            DEFINITIONS,
        )

    def service(self) -> ConversationEvaluationService:
        return ConversationEvaluationService(ExecutionRuntime(self.snapshot()))


def codec(**kwargs: Any) -> ContinuationCodec:
    return ContinuationCodec(KEY, **kwargs)
