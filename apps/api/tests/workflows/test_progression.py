"""Workflow progression (M2-03) without a database: predicates, bundles, engine.

The generic engine is tested independently with the fictional synthetic bundle
(tests/fixtures/rule_bundles) and small inline bundles. Proves that:

- predicates are typed three-valued data: an unanswered or "Not sure" answer is
  UNKNOWN, ``not`` keeps it unknown, and an unknown input always fires a rule
  (missing information never lets a transition through);
- a bundle is accepted only exactly as the schema says, pinned by its SHA-256,
  for the definition this code serves; anything else is refused with a fixed
  code and a structural location (never content); synthetic rules are refused
  in production and always announce themselves;
- decisions follow ESCALATE > BLOCK > WARN > ALLOW, and a warning never
  overrides a block or an escalation;
- engine gates come first: no installed rules, another bundle version, an
  intake hold, a closed intake gate (a disabled or incomplete screening is
  never "cleared"), an uncovered jurisdiction;
- only the next stages can start, only the stage in progress can complete, and
  everything else is refused as not available (no skipping);
- the employer's pathway choice is never made for them, an undetermined choice
  opens nothing, and changing it erases nothing;
- a DIFC Case only ever sees DIFC rules, and escalations are sticky.
"""

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.companies.jurisdiction import (
    JurisdictionAssessment,
    JurisdictionReadiness,
    ReadinessReason,
)
from app.workflows.conditions import Tri
from app.workflows.definition import (
    CASE_JURISDICTION_KEY,
    DISCIPLINARY_V2,
    NOT_SURE,
    SAFETY_SCREENING,
)
from app.workflows.intake import IntakeEvaluation, evaluate_intake
from app.workflows.progression import predicates
from app.workflows.progression.bundle import (
    RuleBundle,
    RuleBundleError,
    load_bundle,
    parse_bundle,
)
from app.workflows.progression.engine import (
    ProgressEvent,
    ProgressionEvaluation,
    derive_state,
    evaluate_progression,
    resolve_attempt,
)
from app.workflows.progression.spec import DISCIPLINARY_PROGRESSION
from tests.fixtures import synthetic_bundle_pin

SPEC = DISCIPLINARY_PROGRESSION
SYNTHETIC = (
    Path(__file__).resolve().parents[1] / "fixtures/rule_bundles/synthetic-disciplinary.json"
)
FEDERAL = JurisdictionAssessment(
    JurisdictionReadiness.SUPPORTED_CONFIRMED,
    ReadinessReason.CONFIRMED,
    jurisdiction="uae_federal",
    confirmed_at=datetime(2026, 10, 1, tzinfo=UTC),
)
INTAKE_ANSWERS: dict[str, object] = {
    "incident.narrative": "[SYNTHETIC] A team member missed a shift handover.",
    "incident.date": "2026-10-10",
    "incident.history": "new",
    "incident.discussed_with_employee": "yes",
    "incident.evidence_available": "yes",
    CASE_JURISDICTION_KEY: "uae_federal",
    "context.location": "at_work",
    "history.same_incident_sanction": "no",
    "context.policy_awareness": "yes",
    "evidence.witnesses": "yes",
    **{q.key: "no" for q in SAFETY_SCREENING.questions},
}


def raw_synthetic() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SYNTHETIC.read_bytes())
    return data


def bundle_from(data: Mapping[str, Any]) -> RuleBundle:
    return parse_bundle(json.dumps(data).encode(), file_sha256="0" * 64)


@pytest.fixture(scope="module")
def synthetic() -> RuleBundle:
    return load_bundle(SYNTHETIC, synthetic_bundle_pin(), production=False)


def intake(answers: Mapping[str, object], *, screening: bool = True) -> IntakeEvaluation:
    return evaluate_intake(DISCIPLINARY_V2, answers, FEDERAL, screening_enabled=screening)


def recorded(**extra: object) -> tuple[dict[str, object], IntakeEvaluation]:
    answers = {**INTAKE_ANSWERS, **extra}
    evaluation = intake(answers)
    assert evaluation.status == "intake_recorded"
    return answers, evaluation


def as_difc(evaluation: IntakeEvaluation) -> IntakeEvaluation:
    """A recorded intake resolved to DIFC (the engine is tested on its own here)."""
    return dataclasses.replace(
        evaluation,
        jurisdiction=dataclasses.replace(evaluation.jurisdiction, jurisdiction="difc"),
    )


class Events:
    """Applied progress events, numbered like instance revisions."""

    def __init__(self, version: str = "synthetic.1") -> None:
        self.items: list[ProgressEvent] = []
        self.version = version

    def _add(self, kind: Any, transition: str, pathway: str | None, stage: str | None) -> None:
        self.items.append(
            ProgressEvent(kind, transition, pathway, stage, "allow", len(self.items) + 10,
                          self.version)
        )  # fmt: skip

    def pathway(self, key: str) -> "Events":
        self._add("pathway_selected", f"pathway:{key}", key, None)
        return self

    def start(self, stage: str, pathway: str = "less_serious") -> "Events":
        self._add("stage_started", f"start:{stage}", pathway, stage)
        return self

    def complete(self, stage: str, pathway: str = "less_serious") -> "Events":
        self._add("stage_completed", f"complete:{stage}", pathway, stage)
        return self

    def escalated(self, transition: str) -> "Events":
        self.items.append(
            ProgressEvent("escalation_recorded", transition, None, None, "escalate",
                          len(self.items) + 10, self.version)
        )  # fmt: skip
        return self


def run(
    bundle: RuleBundle | None,
    evaluation: IntakeEvaluation,
    answers: Mapping[str, object],
    events: Events | None = None,
) -> ProgressionEvaluation:
    return evaluate_progression(
        SPEC, bundle, evaluation, answers, [] if events is None else events.items
    )


# --- predicates ------------------------------------------------------------------------


def test_unknown_inputs_are_never_false() -> None:
    answer = predicates.Answer("x", ("yes",))
    context = predicates.Context({}, frozenset())
    assert predicates.evaluate(answer, context) is Tri.UNKNOWN
    unsure = predicates.Context({"x": NOT_SURE}, frozenset())
    assert predicates.evaluate(answer, unsure) is Tri.UNKNOWN
    assert predicates.evaluate(predicates.Not(answer), unsure) is Tri.UNKNOWN
    assert predicates.evaluate(predicates.Not(answer), predicates.Context({"x": "no"}, frozenset()))
    assert (
        predicates.evaluate(predicates.AllOf((answer, predicates.StageCompleted("s"))), unsure)
        is Tri.FALSE
    )
    assert predicates.unknown_keys(predicates.Not(answer), unsure) == ("x",)


@pytest.mark.parametrize(
    "raw",
    [
        "__import__('os').system('true')",
        {"answer": "x"},
        {"answer": "x", "in": "yes"},
        {"answer": "x", "in": ["yes"], "unknown": ["yes"]},
        {"all": []},
        {"any": [{"answer": "x", "in": ["yes"]}], "all": []},
        {"eval": "1"},
        {"stage_completed": 3},
        {
            "not": {
                "not": {
                    "not": {
                        "not": {"not": {"not": {"not": {"not": {"not": {"stage_completed": "s"}}}}}}
                    }
                }
            }
        },
    ],
)
def test_predicates_are_parsed_strictly(raw: object) -> None:
    with pytest.raises(predicates.PredicateError):
        predicates.parse(raw, "$")


# --- bundles ---------------------------------------------------------------------------


def test_the_synthetic_bundle_loads_and_is_deterministic(synthetic: RuleBundle) -> None:
    again = load_bundle(SYNTHETIC, synthetic.file_sha256, production=False)
    assert again == synthetic
    assert synthetic.provenance == "synthetic"
    assert synthetic.notice is not None
    assert sorted(synthetic.jurisdictions) == ["difc", "uae_federal"]
    # Reformatting the file changes the pin, not the content digest.
    pretty = json.dumps(raw_synthetic(), indent=4).encode()
    assert bundle_from(json.loads(pretty)).digest == synthetic.digest


def test_a_missing_bundle_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RuleBundleError) as refused:
        load_bundle(tmp_path / "absent.json", "a" * 64, production=False)
    assert refused.value.code == "unreadable"


def test_a_bundle_that_does_not_match_its_pin_is_refused(
    tmp_path: Path, synthetic: RuleBundle
) -> None:
    changed = raw_synthetic()
    changed["version"] = "synthetic.2"
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(changed))
    # The pin of the bundle that was approved: the changed file doesn't match it.
    with pytest.raises(RuleBundleError) as refused:
        load_bundle(path, synthetic.file_sha256, production=False)
    assert refused.value.code == "checksum_mismatch"
    with pytest.raises(RuleBundleError) as invalid_pin:
        load_bundle(path, "NOT-A-PIN", production=False)
    assert invalid_pin.value.code == "invalid_pin"


def test_synthetic_rules_are_refused_in_production(synthetic: RuleBundle) -> None:
    with pytest.raises(RuleBundleError) as refused:
        load_bundle(SYNTHETIC, synthetic.file_sha256, production=True)
    assert refused.value.code == "synthetic_in_production"


def test_a_private_bundle_may_run_in_production(tmp_path: Path) -> None:
    data = raw_synthetic()
    data["provenance"] = "private"
    data["notice"] = None
    path = tmp_path / "private.json"
    path.write_bytes(json.dumps(data).encode())
    bundle = load_bundle(path, hashlib.sha256(path.read_bytes()).hexdigest(), production=True)
    assert bundle.provenance == "private"


def _mutate(path: str, value: Any) -> dict[str, Any]:
    data = raw_synthetic()
    target: Any = data
    parts = path.split("/")
    for part in parts[:-1]:
        target = target[int(part)] if part.isdigit() else target[part]
    last = parts[-1]
    if value is KeyError:
        del target[last]
    elif last.isdigit():
        target[int(last)] = value
    else:
        target[last] = value
    return data


FED = "jurisdictions/uae_federal/pathways/0"


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        ("schema", "heroos.rule-bundle/2", "unsupported_schema"),
        ("provenance", "official", "invalid_provenance"),
        ("workflow", "probation", "unknown_workflow"),
        ("definition_versions", [1], "definition_version_unsupported"),
        ("definition_versions", [True], "invalid_definition_versions"),
        ("version", "Synthetic 1", "invalid_key"),
        ("notice", None, "synthetic_without_notice"),
        ("extra", 1, "unknown_field"),
        ("jurisdictions/adgm", {"pathways": []}, "unsupported_jurisdiction"),
        (f"{FED}/pathway", "undetermined", "invalid_pathway"),
        (f"{FED}/pathway", "dismissal", "invalid_pathway"),
        (f"{FED}/entry", ["test_final_review"], "unreachable_stage"),
        (f"{FED}/entry", ["missing"], "invalid_entry"),
        (f"{FED}/stages/2/next", ["test_check_in"], "terminal_with_next"),
        (f"{FED}/stages/1/next", ["test_check_in"], "stage_cycle"),
        (f"{FED}/stages/0/title", " padded", "invalid_text"),
        (f"{FED}/stages/0/title", "line\nbreak", "invalid_text"),
        (f"{FED}/stages/0/optional", "no", "expected_boolean"),
        (f"{FED}/stages/0/complete_rules/0/action", "allow", "invalid_action"),
        (f"{FED}/stages/0/complete_rules/0/require", {"eval": "x"}, "invalid_condition"),
        (
            f"{FED}/stages/0/complete_rules/0/require",
            {"answer": "screening.sick_leave", "in": ["no"]},
            "sensitive_answer_referenced",
        ),
        (
            f"{FED}/stages/0/complete_rules/0/require",
            {"answer": "incident.unknown", "in": ["no"]},
            "unknown_answer_referenced",
        ),
        (
            f"{FED}/stages/0/complete_rules/0/require",
            {"stage_completed": "test_difc_review"},
            "unknown_stage_referenced",
        ),
        (
            f"{FED}/stages/1/start_rules/0/require",
            {"answer": "progress.test_written_note.note_shared", "in": ["yes"]},
            "unknown_answer_referenced",
        ),
        (f"{FED}/stages/1/complete_rules/1/key", "test_note_confirmed", "duplicate_rule"),
        (f"{FED}/stages/0/checklist/1/item", "conversation_held", "duplicate_key"),
    ],
)
def test_bundles_outside_the_schema_are_refused(path: str, value: Any, code: str) -> None:
    with pytest.raises(RuleBundleError) as refused:
        bundle_from(_mutate(path, value))
    assert refused.value.code == code
    # Fixed code and a structural location only: never any bundle wording.
    assert str(refused.value).startswith(f"rule bundle refused: {code}")
    assert "Test" not in str(refused.value)


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        b'{"schema": "heroos.rule-bundle/1", "schema": "heroos.rule-bundle/1"}',
        b'{"schema": NaN}',
        b"\xff\xfe",
        b" " * (1024 * 1024 + 1),
    ],
)
def test_malformed_files_are_refused(content: bytes) -> None:
    with pytest.raises(RuleBundleError):
        parse_bundle(content, file_sha256="0" * 64)


def test_a_stage_cannot_shadow_an_intake_step() -> None:
    data = raw_synthetic()
    data["jurisdictions"]["difc"]["pathways"][0] = {
        "pathway": "less_serious",
        "entry": ["jurisdiction"],
        "stages": [
            {
                "key": "jurisdiction",
                "title": "Test",
                "summary": "Test",
                "optional": False,
                "terminal": True,
                "next": [],
            }
        ],
    }
    with pytest.raises(RuleBundleError) as refused:
        bundle_from(data)
    assert refused.value.code == "stage_shadows_step"


def test_a_rule_needs_exactly_one_condition() -> None:
    both = _mutate(f"{FED}/stages/0/complete_rules/0/when", {"stage_completed": "test_check_in"})
    with pytest.raises(RuleBundleError) as refused:
        bundle_from(both)
    assert refused.value.code == "rule_needs_require_or_when"


# --- engine gates ----------------------------------------------------------------------


def test_without_installed_rules_nothing_is_offered(synthetic: RuleBundle) -> None:
    answers, evaluation = recorded()
    result = run(None, evaluation, answers)
    assert (result.status, result.gate) == ("unavailable", "rules_unavailable")
    assert result.transitions == ()
    assert resolve_attempt(result, SPEC, "pathway:less_serious") is not None
    assert resolve_attempt(result, SPEC, "start:test_check_in") is None


def test_a_disabled_or_incomplete_screening_never_opens_progression(
    synthetic: RuleBundle,
) -> None:
    answers = dict(INTAKE_ANSWERS)
    disabled = intake(answers, screening=False)
    assert disabled.status == "screening_unavailable"
    unsure = intake({**answers, "screening.sick_leave": NOT_SURE})
    incomplete = intake({k: v for k, v in answers.items() if k != "screening.sick_leave"})
    for evaluation in (disabled, unsure, incomplete):
        result = run(synthetic, evaluation, answers, Events().pathway("less_serious"))
        assert (result.status, result.gate) == ("intake_incomplete", "intake_incomplete")
        assert result.transitions
        assert all(t.decision == "block" and not t.allowed for t in result.transitions)
        assert result.checklist_step is None


def test_a_specialist_review_hold_escalates_every_transition(synthetic: RuleBundle) -> None:
    answers = {**INTAKE_ANSWERS, "screening.sick_leave": "yes"}
    held = intake(answers)
    assert held.hold is not None and held.hold.kind == "specialist_review"
    events = Events().pathway("less_serious").start("test_check_in")
    result = run(synthetic, held, answers, events)
    assert (result.status, result.gate) == ("held", "case_held")
    assert result.transitions
    assert all(t.decision == "escalate" and not t.allowed for t in result.transitions)
    # Nothing can be answered while held, and no bundle escalation is "new".
    assert result.checklist_step is None


def test_a_jurisdiction_the_bundle_does_not_cover_is_blocked(synthetic: RuleBundle) -> None:
    federal_only = raw_synthetic()
    del federal_only["jurisdictions"]["uae_federal"]
    answers, evaluation = recorded()
    result = run(bundle_from(federal_only), evaluation, answers)
    assert (result.status, result.gate) == ("not_covered", "jurisdiction_not_covered")
    assert result.stage_transitions == ()
    assert all(t.decision == "block" for t in result.pathway_transitions)


def test_another_bundle_version_never_continues_a_case(synthetic: RuleBundle) -> None:
    answers, evaluation = recorded()
    older = Events(version="synthetic.0").pathway("less_serious")
    result = run(synthetic, evaluation, answers, older)
    assert (result.status, result.gate) == ("incompatible", "rules_version_incompatible")
    assert result.transitions == ()
    # A bundle that declares the earlier version compatible continues it.
    serving = raw_synthetic()
    serving["serves_versions"] = ["synthetic.0"]
    resumed = run(bundle_from(serving), evaluation, answers, older)
    assert resumed.status == "ready"


# --- pathway ---------------------------------------------------------------------------


def test_no_pathway_is_chosen_for_the_employer(synthetic: RuleBundle) -> None:
    answers, evaluation = recorded()
    result = run(synthetic, evaluation, answers)
    assert result.status == "awaiting_pathway"
    assert result.state.pathway is None
    assert result.stage_transitions == ()
    assert [t.key for t in result.pathway_transitions] == [
        "pathway:less_serious",
        "pathway:serious",
        "pathway:undetermined",
    ]
    assert all(t.decision == "allow" for t in result.pathway_transitions)


def test_a_pathway_caution_needs_acknowledgment(synthetic: RuleBundle) -> None:
    answers, evaluation = recorded(
        **{"incident.history": "raised_before", "history.documented_action": "yes"}
    )
    less = run(synthetic, evaluation, answers).transition("pathway:less_serious")
    assert less is not None
    assert (less.decision, less.allowed, less.warnings) == (
        "warn",
        True,
        ("test_select_history_caution",),
    )


def test_an_undetermined_choice_opens_no_stage(synthetic: RuleBundle) -> None:
    answers, evaluation = recorded()
    result = run(synthetic, evaluation, answers, Events().pathway("undetermined"))
    assert result.status == "undetermined"
    assert result.stage_transitions == ()
    assert result.stages == ()
    attempt = resolve_attempt(result, SPEC, "start:test_check_in")
    assert attempt is not None and attempt.decision == "block"
    assert attempt.gates == ("stage_not_available",)


def test_the_current_pathway_cannot_be_chosen_again(synthetic: RuleBundle) -> None:
    answers, evaluation = recorded()
    result = run(synthetic, evaluation, answers, Events().pathway("serious"))
    again = resolve_attempt(result, SPEC, "pathway:serious")
    assert again is not None and again.gates == ("pathway_unchanged",)
    assert resolve_attempt(result, SPEC, "pathway:dismissal") is None


# --- stages ----------------------------------------------------------------------------


def test_only_the_next_stage_can_start(synthetic: RuleBundle) -> None:
    answers, evaluation = recorded()
    result = run(synthetic, evaluation, answers, Events().pathway("less_serious"))
    assert result.status == "ready"
    assert [t.key for t in result.stage_transitions] == ["start:test_check_in"]
    assert [(s.key, status) for s, status in result.stages] == [
        ("test_check_in", "next"),
        ("test_written_note", "later"),
        ("test_final_review", "later"),
    ]
    for skip in ("start:test_written_note", "start:test_final_review", "start:test_notice"):
        attempt = resolve_attempt(result, SPEC, skip)
        assert attempt is not None, skip
        assert (attempt.decision, attempt.gates) == ("block", ("stage_not_available",))
    complete = resolve_attempt(result, SPEC, "complete:test_check_in")
    assert complete is not None and complete.gates == ("stage_not_active",)
    assert resolve_attempt(result, SPEC, "start:no_such_stage") is None
    assert resolve_attempt(result, SPEC, "approve:test_check_in") is None


def test_a_stage_completes_only_with_its_requirements_met(synthetic: RuleBundle) -> None:
    events = Events().pathway("less_serious").start("test_check_in")
    answers, evaluation = recorded()
    result = run(synthetic, evaluation, answers, events)
    assert result.status == "in_stage"
    checklist = result.checklist_step
    assert checklist is not None and checklist.key == "test_check_in"
    assert [q.key for q in checklist.questions] == [
        "progress.test_check_in.conversation_held",
        "progress.test_check_in.employee_heard",
    ]
    missing = result.transition("complete:test_check_in")
    assert missing is not None and missing.decision == "block"
    assert "checklist_incomplete" in missing.gates
    assert missing.missing == (
        "progress.test_check_in.conversation_held",
        "progress.test_check_in.employee_heard",
    )
    # "Not sure" never satisfies a requirement.
    unsure = {
        **answers,
        "progress.test_check_in.conversation_held": "yes",
        "progress.test_check_in.employee_heard": NOT_SURE,
    }
    blocked = run(synthetic, evaluation, unsure, events).transition("complete:test_check_in")
    assert blocked is not None and blocked.decision == "block"
    assert [r.rule for r in blocked.fired] == ["test_check_in_confirmed"]
    assert blocked.fired[0].reason == "unknown_inputs"
    confirmed = {**unsure, "progress.test_check_in.employee_heard": "yes"}
    allowed = run(synthetic, evaluation, confirmed, events).transition("complete:test_check_in")
    assert allowed is not None and (allowed.decision, allowed.allowed) == ("allow", True)


def test_a_warning_never_overrides_a_block(synthetic: RuleBundle) -> None:
    events = (
        Events()
        .pathway("less_serious")
        .start("test_check_in")
        .complete("test_check_in")
        .start("test_written_note")
    )
    answers, evaluation = recorded(**{"incident.evidence_available": "no"})
    not_shared = {**answers, "progress.test_written_note.note_shared": "no"}
    key = "complete:test_written_note"
    blocked = run(synthetic, evaluation, not_shared, events).transition(key)
    assert blocked is not None
    assert {r.rule: r.action for r in blocked.fired} == {
        "test_note_confirmed": "block",
        "test_note_evidence_caution": "warn",
    }
    assert (blocked.decision, blocked.allowed, blocked.warnings) == ("block", False, ())
    shared = {**answers, "progress.test_written_note.note_shared": "yes"}
    warned = run(synthetic, evaluation, shared, events).transition(key)
    assert warned is not None
    assert (warned.decision, warned.allowed, warned.warnings) == (
        "warn",
        True,
        ("test_note_evidence_caution",),
    )


def _rules_bundle(actions: tuple[str, ...], condition: dict[str, Any]) -> RuleBundle:
    data = raw_synthetic()
    stage = data["jurisdictions"]["uae_federal"]["pathways"][0]["stages"][0]
    stage["checklist"] = []
    stage["complete_rules"] = [
        {
            "key": f"rule_{chr(97 + index)}",
            "action": action,
            "when": condition,
            "provisional": False,
            "message": {"title": "Test", "body": "Test"},
        }
        for index, action in enumerate(actions)
    ]
    return bundle_from(data)


WITNESSES_YES = {"answer": "evidence.witnesses", "in": ["yes"]}


@pytest.mark.parametrize(
    ("actions", "decision"),
    [
        ((), "allow"),
        (("warn",), "warn"),
        (("block",), "block"),
        (("escalate",), "escalate"),
        (("warn", "block"), "block"),
        (("block", "warn"), "block"),
        (("warn", "escalate"), "escalate"),
        (("escalate", "block", "warn"), "escalate"),
        (("block", "escalate"), "escalate"),
    ],
)
def test_decisions_follow_a_fixed_precedence(actions: tuple[str, ...], decision: str) -> None:
    events = Events().pathway("less_serious").start("test_check_in")
    answers, evaluation = recorded()
    key = "complete:test_check_in"
    # Every condition met: the strongest action decides.
    met = run(_rules_bundle(actions, WITNESSES_YES), evaluation, answers, events).transition(key)
    assert met is not None and met.decision == decision
    if decision != "warn":
        assert met.warnings == ()
    # Definitely not met: nothing fires.
    no = {**answers, "evidence.witnesses": "no"}
    quiet = run(_rules_bundle(actions, WITNESSES_YES), evaluation, no, events).transition(key)
    assert quiet is not None and quiet.decision == "allow"


@pytest.mark.parametrize(
    ("actions", "decision"),
    [
        (("warn",), "warn"),
        (("block",), "block"),
        # An escalation needs its condition met: unknown inputs block instead.
        (("escalate",), "block"),
        (("warn", "escalate"), "block"),
    ],
)
def test_unknown_inputs_always_fire(actions: tuple[str, ...], decision: str) -> None:
    events = Events().pathway("less_serious").start("test_check_in")
    answers, evaluation = recorded()
    for unknown in (
        {k: v for k, v in answers.items() if k != "evidence.witnesses"},
        {**answers, "evidence.witnesses": NOT_SURE},
    ):
        result = run(_rules_bundle(actions, WITNESSES_YES), evaluation, unknown, events)
        transition = result.transition("complete:test_check_in")
        assert transition is not None and transition.decision == decision
        assert not transition.new_escalation
        assert transition.missing == (() if decision == "warn" else ("evidence.witnesses",))


def test_escalations_are_sticky(synthetic: RuleBundle) -> None:
    events = Events().pathway("less_serious")
    for stage in ("test_check_in", "test_written_note"):
        events.start(stage).complete(stage)
    events.start("test_final_review")
    answers, evaluation = recorded()
    help_needed = {
        **answers,
        "progress.test_final_review.review_done": "yes",
        "progress.test_final_review.outside_help_needed": "yes",
    }
    first = run(synthetic, evaluation, help_needed, events).transition("complete:test_final_review")
    assert first is not None
    assert (first.decision, first.new_escalation) == ("escalate", True)
    # Once recorded, changed answers don't release it.
    events.escalated("complete:test_final_review")
    no_help = {**help_needed, "progress.test_final_review.outside_help_needed": "no"}
    later = run(synthetic, evaluation, no_help, events).transition("complete:test_final_review")
    assert later is not None
    assert (later.decision, later.new_escalation) == ("escalate", False)
    assert "earlier_escalation" in later.gates


def test_completing_a_terminal_stage_ends_the_workflow(synthetic: RuleBundle) -> None:
    events = Events().pathway("less_serious")
    for stage in ("test_check_in", "test_written_note", "test_final_review"):
        events.start(stage).complete(stage)
    answers, evaluation = recorded()
    result = run(synthetic, evaluation, answers, events)
    assert (result.status, result.gate) == ("closed", "workflow_closed")
    assert result.stage_transitions == ()
    assert all(t.decision == "block" for t in result.pathway_transitions)


def test_changing_the_pathway_erases_nothing(synthetic: RuleBundle) -> None:
    events = (
        Events()
        .pathway("less_serious")
        .start("test_check_in")
        .complete("test_check_in")
        .start("test_written_note")
        .pathway("serious")
    )
    answers, evaluation = recorded()
    serious = run(synthetic, evaluation, answers, events)
    assert serious.state.pathway == "serious"
    assert serious.state.completed == ("test_check_in",)
    # The stage in progress was left, not completed.
    assert serious.state.active is None
    assert [t.key for t in serious.stage_transitions] == ["start:test_notice"]
    back = run(synthetic, evaluation, answers, events.pathway("less_serious"))
    assert [t.key for t in back.stage_transitions] == ["start:test_written_note"]
    state = derive_state(events.items)
    assert state.completed == ("test_check_in",)


def test_an_optional_stage_can_be_passed_over(synthetic: RuleBundle) -> None:
    events = Events().pathway("serious").start("test_notice", "serious")
    events.complete("test_notice", "serious")
    answers, evaluation = recorded()
    result = run(synthetic, evaluation, answers, events)
    assert [t.key for t in result.stage_transitions] == ["start:test_pause", "start:test_meeting"]
    after = run(synthetic, evaluation, answers, events.start("test_meeting", "serious"))
    skipped = resolve_attempt(after, SPEC, "start:test_pause")
    assert skipped is not None and skipped.gates == ("stage_in_progress",)


def test_a_difc_case_only_sees_difc_rules(synthetic: RuleBundle) -> None:
    answers, federal = recorded()
    difc = as_difc(federal)
    result = run(synthetic, difc, answers, Events().pathway("less_serious"))
    assert result.program is not None and result.program.jurisdiction == "difc"
    assert [t.key for t in result.stage_transitions] == ["start:test_difc_review"]
    federal_keys = {
        r.key
        for p in synthetic.jurisdictions["uae_federal"].pathways
        for s in p.stages
        for r in (*s.start_rules, *s.complete_rules)
    } | {r.key for p in synthetic.jurisdictions["uae_federal"].pathways for r in p.select_rules}
    seen = {r.rule for t in result.transitions for r in t.results}
    assert not seen & federal_keys
    # No serious pathway is approved for DIFC in this bundle: blocked, never borrowed.
    serious = result.transition("pathway:serious")
    assert serious is not None and serious.gates == ("pathway_not_covered",)
    assert resolve_attempt(result, SPEC, "start:test_notice") is None


def test_the_evaluation_is_deterministic(synthetic: RuleBundle) -> None:
    answers, evaluation = recorded()
    events = Events().pathway("less_serious").start("test_check_in")
    assert run(synthetic, evaluation, answers, events) == run(
        synthetic, evaluation, answers, events
    )


def test_a_pathway_whose_stages_are_all_done_says_so(synthetic: RuleBundle) -> None:
    data = raw_synthetic()
    stages = data["jurisdictions"]["uae_federal"]["pathways"][0]["stages"]
    stages[2]["terminal"] = False  # the last stage, but the workflow isn't closed
    bundle = bundle_from(data)
    events = Events().pathway("less_serious")
    for stage in ("test_check_in", "test_written_note", "test_final_review"):
        events.start(stage).complete(stage)
    answers, evaluation = recorded()
    result = run(bundle, evaluation, answers, events)
    assert (result.status, result.gate) == ("no_further_stage", None)
    assert result.stage_transitions == ()
    # The employer can still change the pathway: nothing is closed.
    others = {t.key for t in result.pathway_transitions}
    assert others == {"pathway:serious", "pathway:undetermined"}
