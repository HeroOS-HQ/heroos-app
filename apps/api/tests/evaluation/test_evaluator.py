"""The generic deterministic evaluator (M2-NEW-06), on the fictional content.

Pure: the same snapshot, trusted facts, requested steps and two-state answers
always give the same evaluation. These tests fix the trusted inputs directly;
tests/evaluation/test_golden.py drives the same evaluator through the gateway.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from app.evaluation.evaluator import EvaluationRequest, evaluate_conversation
from app.evaluation.model import (
    PRESENTATIONS,
    ConversationEvaluation,
    TrustedFactState,
    TwoState,
)
from app.evaluation.snapshot import ExecutionSnapshot, knowledge_only_runtime
from app.workflows.conditions import Tri
from tests.fixtures.evaluation import PROBATION, Artifacts, knowledge

FED, DIFC = "uae_federal", "difc"


@pytest.fixture
def snapshot(artifacts: Artifacts) -> ExecutionSnapshot:
    return artifacts.snapshot()


def run(
    snapshot: ExecutionSnapshot,
    *,
    facts: dict[str, Any] | None = None,
    requested: tuple[str, ...] = (),
    workflow: str = "disciplinary",
    jurisdiction: str | None = FED,
    **extra: Any,
) -> ConversationEvaluation:
    request = EvaluationRequest(
        matter="supported",
        workflow=workflow,
        company_jurisdiction=jurisdiction,
        facts=TrustedFactState(engine=facts or {}),
        requested=requested,
        **extra,
    )
    return evaluate_conversation(snapshot, request)


def action(evaluation: ConversationEvaluation, key: str):  # type: ignore[no-untyped-def]
    return next(a for a in evaluation.actions if a.action == key)


def condition(evaluation: ConversationEvaluation, key: str):  # type: ignore[no-untyped-def]
    return next(c for c in evaluation.conditions if c.condition == key)


READY = {"given_opportunity_to_explain": "yes", "investigation_completed": "yes"}


# --- ordinary conversation ------------------------------------------------------------------


def test_missing_context_with_nothing_requested_is_guidance(snapshot: ExecutionSnapshot) -> None:
    """Needs more context is Guidance and a question, never a Block."""
    evaluation = run(snapshot, topics=("workplace_reminder",))
    assert evaluation.presentation == "guidance"
    assert evaluation.actions == () and evaluation.reviews == ()
    assert condition(evaluation, "EX-FED-POLICY").status == "unknown"
    assert evaluation.next_step == "answer_question"
    assert [m.key for m in evaluation.missing] == ["employee_aware_of_relevant_policy"]


def test_a_bound_condition_fires_with_its_own_configured_severity(
    snapshot: ExecutionSnapshot,
) -> None:
    """The binding decides; the severity is the Condition's, not a demo's."""
    evaluation = run(
        snapshot, topics=("formal_warning",), facts={"given_opportunity_to_explain": "no"}
    )
    fired = condition(evaluation, "EX-FED-WARNING-LABEL")
    configured = snapshot.workflows["disciplinary"].conditions["EX-FED-WARNING-LABEL"]
    assert fired.status == "fired" and fired.action == configured.action_policy.initial
    assert evaluation.presentation == PRESENTATIONS[configured.action_policy.initial]  # type: ignore[index]
    # Satisfied: nothing fires.
    clear = run(snapshot, topics=("formal_warning",), facts={"given_opportunity_to_explain": "yes"})
    assert condition(clear, "EX-FED-WARNING-LABEL").status == "not_fired"
    assert clear.presentation == "guidance"


# --- Condition and action stay separate ------------------------------------------------------


def test_a_condition_warns_while_the_requested_step_is_blocked(snapshot: ExecutionSnapshot) -> None:
    """The cap warns; the suspension is blocked by its missing prerequisite."""
    evaluation = run(
        snapshot,
        requested=("opt-suspension",),
        facts={"proposed_suspension_days": 20, "investigation_completed": "yes"},
    )
    cap = condition(evaluation, "EX-FED-CAP")
    assert cap.status == "fired" and cap.action == "warn"
    suspension = action(evaluation, "opt-suspension")
    assert suspension.disposition == "block"
    assert "rule:suspension_response" in suspension.reasons
    assert "condition:EX-FED-CAP" in suspension.reasons
    assert suspension.missing == ("given_opportunity_to_explain",)
    assert evaluation.presentation == "block"
    assert [c.source for c in evaluation.cautions] == ["EX-FED-CAP"]


def test_methodology_continues_while_one_step_needs_review(snapshot: ExecutionSnapshot) -> None:
    """Investigation guidance and a held dismissal, side by side."""
    evaluation = run(
        snapshot,
        topics=("serious_investigation",),
        requested=("opt-dismissal", "opt-investigative"),
        facts=READY,
    )
    assert action(evaluation, "opt-dismissal").disposition == "escalate"
    assert action(evaluation, "opt-investigative").disposition == "allow"
    assert evaluation.presentation == "expert_review"
    (review,) = evaluation.reviews
    assert review.scope == "action" and review.action == "opt-dismissal"
    assert not review.service_available


def test_allow_means_only_that_no_rule_prevents_it(snapshot: ExecutionSnapshot) -> None:
    evaluation = run(snapshot, requested=("opt-warning",), facts=READY)
    warning = action(evaluation, "opt-warning")
    assert warning.disposition == "allow" and warning.reasons == ()
    assert evaluation.presentation == "guidance" and evaluation.reviews == ()


# --- two-state Conditions -----------------------------------------------------------------------


def test_a_two_state_caution_warns_first(snapshot: ExecutionSnapshot) -> None:
    facts = {"proposed_suspension_days": 20, **READY}
    first = run(snapshot, requested=("opt-suspension",), facts=facts)
    assert action(first, "opt-suspension").disposition == "warn"
    cap = condition(first, "EX-FED-CAP")
    assert cap.follow_up == "pending"
    assert [m.kind for m in first.missing] == ["insistence"]
    assert first.two_state == (TwoState("fictional_cap", True, False, Tri.FALSE),)
    assert first.next_step == "consider_caution"


def test_acknowledging_is_not_insisting(snapshot: ExecutionSnapshot) -> None:
    facts = {"proposed_suspension_days": 20, **READY}
    acknowledged = {"fictional_cap": TwoState("fictional_cap", True, True, Tri.FALSE)}
    evaluation = run(snapshot, requested=("opt-suspension",), facts=facts, two_state=acknowledged)
    assert action(evaluation, "opt-suspension").disposition == "warn"
    assert evaluation.presentation == "warning"


def test_explicit_insistence_takes_the_follow_up(snapshot: ExecutionSnapshot) -> None:
    facts = {"proposed_suspension_days": 20, **READY}
    insisted = {"fictional_cap": TwoState("fictional_cap", True, True, Tri.TRUE)}
    evaluation = run(snapshot, requested=("opt-suspension",), facts=facts, two_state=insisted)
    assert condition(evaluation, "EX-FED-CAP").follow_up == "applied"
    assert action(evaluation, "opt-suspension").disposition == "block"
    assert evaluation.presentation == "block"
    # Within the cap, the caution doesn't apply at all.
    within = run(
        snapshot,
        requested=("opt-suspension",),
        two_state=insisted,
        facts={"proposed_suspension_days": 5, **READY},
    )
    assert action(within, "opt-suspension").disposition == "allow"


def test_lost_state_reconfirms_never_loosens(snapshot: ExecutionSnapshot) -> None:
    """After trusted state was lost the stronger action holds until confirmed again."""
    facts = {"proposed_suspension_days": 20, **READY}
    evaluation = run(snapshot, requested=("opt-suspension",), facts=facts, reconfirm=True)
    assert condition(evaluation, "EX-FED-CAP").follow_up == "reconfirm"
    assert action(evaluation, "opt-suspension").disposition == "block"
    declined = {"fictional_cap": TwoState("fictional_cap", True, True, Tri.FALSE)}
    answered = run(
        snapshot, requested=("opt-suspension",), facts=facts, reconfirm=True, two_state=declined
    )
    assert action(answered, "opt-suspension").disposition == "warn"


# --- three-valued logic and precedence ---------------------------------------------------------


def test_unknown_never_becomes_false(snapshot: ExecutionSnapshot) -> None:
    evaluation = run(snapshot, requested=("opt-suspension",))
    suspension = action(evaluation, "opt-suspension")
    # Unknown prerequisites block; the unknown cap still warns (no false negative).
    assert suspension.disposition == "block"
    assert set(suspension.missing) == {
        "given_opportunity_to_explain",
        "investigation_completed",
        "proposed_suspension_days",
    }
    not_sure = run(
        snapshot,
        requested=("opt-suspension",),
        facts={**READY, "proposed_suspension_days": 20, "given_opportunity_to_explain": "not_sure"},
    )
    assert action(not_sure, "opt-suspension").disposition == "block"


def test_an_escalation_with_unknown_inputs_holds_for_information(artifacts: Artifacts) -> None:
    snapshot = artifacts.snapshot()
    evaluation = run(
        snapshot, workflow=PROBATION, requested=("sp-end",), facts={"review_meeting_held": "yes"}
    )
    concerns = condition(evaluation, "SP-CONCERNS")
    assert concerns.status == "unknown" and concerns.action == "block"
    assert action(evaluation, "sp-end").disposition == "block"
    assert action(evaluation, "sp-end").review is None


def test_precedence_escalate_block_unknown_warn_allow(snapshot: ExecutionSnapshot) -> None:
    steps = ("opt-dismissal", "opt-warning", "opt-reminder", "opt-suspension", "opt-investigative")
    facts = {"investigation_completed": "yes", "given_opportunity_to_explain": "no"}
    evaluation = run(snapshot, requested=steps, facts=facts)
    assert {a.action: a.disposition for a in evaluation.actions} == {
        "opt-dismissal": "escalate",
        "opt-warning": "block",
        "opt-reminder": "unknown",
        "opt-suspension": "block",
        "opt-investigative": "allow",
    }
    expected = ("expert_review", "block", "warning", "warning", "guidance")
    for index, presentation in enumerate(expected):
        rest = run(snapshot, requested=steps[index:], facts=READY if index > 1 else facts)
        assert rest.presentation == presentation, steps[index:]
    # Each step keeps its own result whatever the others are.
    assert action(evaluation, "opt-investigative").disposition == "allow"


# --- coverage --------------------------------------------------------------------------------


def test_a_step_with_no_executable_coverage_is_never_clear(snapshot: ExecutionSnapshot) -> None:
    """A missing binding doesn't silently become Guidance."""
    evaluation = run(snapshot, requested=("opt-reminder",), facts=READY)
    reminder = action(evaluation, "opt-reminder")
    assert reminder.disposition == "unknown" and "action_not_covered" in reminder.reasons
    assert evaluation.presentation == "warning"


def test_question_only_and_not_enforced_never_fire(snapshot: ExecutionSnapshot) -> None:
    evaluation = run(
        snapshot, topics=("investigative_suspension", "salary_deduction", "deadlines"), facts=READY
    )
    statuses = {c.condition: (c.category, c.status) for c in evaluation.conditions}
    assert statuses["EX-FED-PAY-CAUTION"] == ("question_only", "not_evaluated")
    assert statuses["EX-FED-OLD-DEDUCTION"] == ("not_enforced", "not_evaluated")
    assert evaluation.cautions == () and evaluation.presentation == "guidance"


def test_a_safeguard_that_cant_be_collected_is_unavailable_never_a_result(
    artifacts: Artifacts,
) -> None:
    """A binding reading a sensitive input is a privacy capability gap, not a finding."""
    artifacts.knowledge["runtime"]["engine_links"].append(
        {"engine": "intake", "rule": "high_risk_screening", "condition": "EX-FED-ESCALATE"}
    )
    profile = artifacts.profile["workflows"][0]
    profile["bindings"].append(
        {"condition": "EX-FED-ESCALATE", "executor": "intake", "rule": "high_risk_screening"}
    )
    artifacts.repin()
    snapshot = artifacts.snapshot()
    assert snapshot.workflows["disciplinary"].incapable == {
        "EX-FED-ESCALATE": "privacy_capability_unavailable"
    }
    evaluation = run(snapshot, topics=("dismissal_without_notice",), requested=("opt-dismissal",))
    escalate = condition(evaluation, "EX-FED-ESCALATE")
    assert escalate.status == "unavailable" and escalate.action is None
    assert escalate.reasons == ("privacy_capability_unavailable",)
    # The dismissal is held for review by its approved availability anyway.
    assert action(evaluation, "opt-dismissal").disposition == "escalate"


# --- jurisdiction ----------------------------------------------------------------------------


def test_no_jurisdiction_specific_result_while_unresolved(snapshot: ExecutionSnapshot) -> None:
    """Shared orientation continues; a requested step gets no jurisdiction-specific result."""
    unconfirmed = run(snapshot, jurisdiction=None, requested=("opt-warning",), facts=READY)
    assert unconfirmed.jurisdiction_state == "company_unconfirmed"
    assert action(unconfirmed, "opt-warning").disposition == "block"
    assert unconfirmed.missing[0].kind == "jurisdiction"
    conflict = run(snapshot, requested=("opt-warning",), facts=READY, jurisdiction_conflict=True)
    assert conflict.jurisdiction_state == "conversation_conflict"
    assert action(conflict, "opt-warning").disposition == "block"
    assert all(
        c.status == "not_evaluated" for c in conflict.conditions if c.category == "executable"
    )
    # The founder's trusted answer resolves it, or holds it for review.
    confirmed = run(
        snapshot,
        requested=("opt-warning",),
        facts=READY,
        jurisdiction_conflict=True,
        clarification="confirmed",
    )
    assert action(confirmed, "opt-warning").disposition == "allow"
    different = run(snapshot, requested=("opt-warning",), facts=READY, clarification="different")
    assert action(different, "opt-warning").disposition == "escalate"
    unsure = run(snapshot, requested=("opt-warning",), facts=READY, clarification="not_sure")
    assert action(unsure, "opt-warning").disposition == "block"
    alone = run(snapshot, jurisdiction=None)
    assert alone.presentation == "guidance" and alone.actions == ()


# --- the knowledge's own boundaries, as availability ------------------------------------------


def test_difc_investigation_continues_and_dismissal_needs_review(
    snapshot: ExecutionSnapshot,
) -> None:
    """Never the whole conversation; the action only."""
    investigation = run(snapshot, jurisdiction=DIFC, topics=("serious_investigation",))
    assert investigation.presentation == "guidance" and investigation.reviews == ()
    dismissal = run(
        snapshot, jurisdiction=DIFC, topics=("serious_investigation",), requested=("opt-dismissal",)
    )
    assert action(dismissal, "opt-dismissal").disposition == "escalate"
    assert dismissal.reviews[0].action == "opt-dismissal"


def test_a_deduction_always_needs_specialist_review(snapshot: ExecutionSnapshot) -> None:
    """(a review boundary): every jurisdiction, whatever the facts."""
    for jurisdiction in (FED, DIFC):
        evaluation = run(
            snapshot, jurisdiction=jurisdiction, requested=("opt-deduction",), facts={**READY}
        )
        assert action(evaluation, "opt-deduction").disposition == "escalate"


def test_investigative_and_disciplinary_suspension_stay_apart(snapshot: ExecutionSnapshot) -> None:
    """Different decisions, different rules; no cap on an investigative suspension."""
    facts = {"proposed_suspension_days": 20, **READY}
    investigative = run(snapshot, requested=("opt-investigative",), facts=facts)
    assert action(investigative, "opt-investigative").disposition == "allow"
    assert "EX-FED-CAP" not in action(investigative, "opt-investigative").conditions
    disciplinary = run(snapshot, requested=("opt-suspension",), facts=facts)
    assert "EX-FED-CAP" in action(disciplinary, "opt-suspension").conditions
    # DIFC unpaid disciplinary suspension: review; no Federal cap as DIFC authority.
    difc = run(snapshot, jurisdiction=DIFC, requested=("opt-suspension",), facts=facts)
    assert action(difc, "opt-suspension").disposition == "escalate"
    assert all(c.condition != "EX-FED-CAP" for c in difc.conditions)


# --- matters and technical availability -------------------------------------------------------


def test_unsupported_hr_is_a_review_requirement_and_outside_scope_is_nothing(
    snapshot: ExecutionSnapshot,
) -> None:
    hr = evaluate_conversation(snapshot, EvaluationRequest(matter="unsupported_hr"))
    assert hr.presentation == "expert_review" and hr.reviews[0].scope == "matter"
    assert not hr.reviews[0].service_available
    for matter in ("outside_product_scope", "unclear", "confidential_request"):
        nothing = evaluate_conversation(snapshot, EvaluationRequest(matter=matter))  # type: ignore[arg-type]
        assert nothing.presentation is None and nothing.reviews == ()


def test_a_technical_problem_is_never_an_hr_outcome(artifacts: Artifacts) -> None:
    """No profile, or an incompatible one: unavailable, no Block, no Expert Review."""
    bare = knowledge_only_runtime(knowledge(artifacts.knowledge)).current()
    evaluation = run(bare, requested=("opt-dismissal",))
    assert evaluation.availability == "execution_profile_missing"
    assert evaluation.presentation is None and evaluation.actions == ()
    artifacts.profile["workflows"][0]["knowledge_runtime_digest"] = "f" * 64
    stale = run(artifacts.snapshot(), requested=("opt-dismissal",))
    assert stale.availability == "incompatible_versions" and stale.presentation is None


def test_multiple_matters_are_never_mixed(snapshot: ExecutionSnapshot) -> None:
    evaluation = run(snapshot, requested=("opt-warning",), facts=READY, multiple_matters=True)
    assert evaluation.next_step == "choose_matter" and evaluation.workflow == "disciplinary"


def test_the_requested_step_is_its_stable_id_never_its_title(snapshot: ExecutionSnapshot) -> None:
    title = snapshot.workflows["disciplinary"].options["opt-warning"].title
    assert run(snapshot, requested=(title,)).actions == ()


# --- purity and determinism ----------------------------------------------------------------


def test_the_same_inputs_give_the_same_result(snapshot: ExecutionSnapshot) -> None:
    """–92: byte-identical records, repeated; no clock, randomness or I/O."""

    def once() -> str:
        evaluation = run(
            snapshot,
            requested=("opt-suspension", "opt-dismissal"),
            topics=("disciplinary_suspension",),
            facts={"proposed_suspension_days": 20, **READY},
        )
        return json.dumps(evaluation.record(), sort_keys=True)

    first = once()
    assert all(once() == first for _ in range(20))
    assert '"provenance"' in first and "synthetic-execution" in first


def test_the_evaluator_has_no_io_and_no_workflow_branches() -> None:
    """No workflow name in the core; nothing but pure code."""
    package = Path(__file__).resolve().parents[2] / "app" / "evaluation"
    for path in package.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for name in ("disciplinary", "probation", "synthetic_probation", "recruitment"):
            assert f'"{name}"' not in source and f"'{name}'" not in source, (path, name)
        for forbidden in (
            "import socket",
            "import httpx",
            "sqlalchemy",
            "fastapi",
            "pydantic",
            "import random",
            "datetime.now",
            "time.time()",
            "eval(",
            "exec(",
        ):
            if forbidden == "time.time()" and path.name == "continuation.py":
                continue  # expiry: an injected clock, defaulting to time.time
            assert forbidden not in source, (path, forbidden)


# --- the second, fictional workflow ------------------------------------------------------------


def test_a_structurally_different_workflow_uses_the_same_core(artifacts: Artifacts) -> None:
    """Its own facts, definition, rules and profile; no pathway; same contract."""
    snapshot = artifacts.snapshot()
    execution = snapshot.workflows[PROBATION]
    assert execution.profile.pathway_ownership == "none"
    assert execution.definition.key == PROBATION and execution.rule_bundle is not None
    # Fact bridge: typed by its own rule bundle.
    assert execution.schemas["extension_days_requested"].kind == "count"

    def go(
        facts: dict[str, Any], requested: tuple[str, ...], **extra: Any
    ) -> ConversationEvaluation:
        return run(snapshot, workflow=PROBATION, facts=facts, requested=requested, **extra)

    # A number against a number: WARN, then BLOCK once the employer insists.
    extend = go(
        {"extension_days_requested": 60, "trial_days_completed": 10, "trial_days_allowed": 90},
        ("sp-extend",),
    )
    assert action(extend, "sp-extend").disposition == "warn"
    assert extend.presentation == "warning" and extend.missing[0].kind == "insistence"
    insisted = go(
        {"extension_days_requested": 60, "trial_days_completed": 10, "trial_days_allowed": 90},
        ("sp-extend",),
        two_state={
            "extension_within_limit": TwoState("extension_within_limit", True, True, Tri.TRUE)
        },
    )
    assert action(insisted, "sp-extend").disposition == "block"
    # A number against another number: BLOCK.
    overrun = go(
        {"extension_days_requested": 5, "trial_days_completed": 100, "trial_days_allowed": 90},
        ("sp-extend",),
    )
    assert action(overrun, "sp-extend").disposition == "block"
    assert condition(overrun, "SP-TRIAL-OVERRUN").status == "fired"
    # Missing input: held for the facts, asked one at a time.
    missing = go({}, ("sp-extend",))
    assert action(missing, "sp-extend").disposition == "block"
    assert {m.key for m in missing.missing} >= {"trial_days_completed", "trial_days_allowed"}
    # ESCALATE, and a condition-specific follow-up.
    ending = go(
        {
            "review_meeting_held": "yes",
            "concerns_documented": "no",
            "trial_days_completed": 10,
            "trial_days_allowed": 90,
        },
        ("sp-end",),
    )
    assert action(ending, "sp-end").disposition == "escalate"
    assert ending.presentation == "expert_review"
    meeting = go(
        {
            "review_meeting_held": "no",
            "concerns_documented": "no",
            "trial_days_completed": 10,
            "trial_days_allowed": 90,
        },
        ("sp-end",),
    )
    assert condition(meeting, "SP-MEETING").action == "escalate"
    assert condition(meeting, "SP-MEETING").follow_up == "applied"
    # ALLOW: no rule prevents it.
    clear = go(
        {
            "review_meeting_held": "yes",
            "concerns_documented": "yes",
            "trial_days_completed": 10,
            "trial_days_allowed": 90,
        },
        ("sp-end",),
    )
    assert action(clear, "sp-end").disposition == "allow" and clear.presentation == "guidance"
    # NOT_ENFORCED stays out, in this workflow too.
    assert condition(clear, "SP-OLD").status == "not_evaluated"
    # The same contract and presentation mapping.
    assert type(clear) is ConversationEvaluation and clear.record()["schema"] == (
        "heroos.conversation-evaluation/1"
    )
    assert clear.provenance is not None and clear.provenance.workflow == PROBATION
