"""The Disciplinary intake rules (M2-02) without a database.

Proves that:

- the rule set is neutral data (keys, jurisdictions, actions, review and
  enforcement flags, typed predicates) and its digest changes with any of it;
- predicates are typed three-valued logic: unanswered and "Not sure" are
  UNKNOWN, never "No";
- the routing rule runs first and nothing jurisdiction-specific runs while the
  Case jurisdiction is unresolved; a UAE Federal rule never runs for a DIFC
  Case, which is held instead of screened;
- a high-risk answer holds the Case (provisional, internal: no ticket), an
  uncertain or missing screening answer never clears the screening, and only a
  fully answered, cleared intake opens the gate to later stages;
- once held for specialist review, a Case stays held whatever the answers
  change to (no release exists yet), and the current screening is still
  reported separately;
- the safety screening is unavailable unless the environment enables it;
- the stored trace holds codes and enumerated answers only, and for sensitive
  questions only counts.
"""

import dataclasses
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from app.companies.jurisdiction import (
    JurisdictionAssessment,
    JurisdictionReadiness,
    ReadinessReason,
)
from app.workflows import conditions
from app.workflows.conditions import (
    DISCIPLINARY_INTAKE,
    AllOf,
    AnswerIn,
    AnyOf,
    Tri,
    evaluate,
    predicate_keys,
)
from app.workflows.conversation import SubmissionRecord
from app.workflows.definition import (
    CASE_JURISDICTION_KEY,
    DISCIPLINARY_V2,
    NOT_SURE,
    SAFETY_SCREENING,
)
from app.workflows.history import EvaluationRecord, compose_history, evaluation_results
from app.workflows.intake import (
    EarlierEscalation,
    IntakeEvaluation,
    evaluate_intake,
    resolve_jurisdiction,
)
from app.workflows.progress import progress

FEDERAL = JurisdictionAssessment(
    JurisdictionReadiness.SUPPORTED_CONFIRMED,
    ReadinessReason.CONFIRMED,
    jurisdiction="uae_federal",
    confirmed_at=datetime(2026, 10, 1, tzinfo=UTC),
)
DIFC = JurisdictionAssessment(
    JurisdictionReadiness.SUPPORTED_CONFIRMED,
    ReadinessReason.CONFIRMED,
    jurisdiction="difc",
    confirmed_at=datetime(2026, 10, 1, tzinfo=UTC),
)
UNCONFIRMED = JurisdictionAssessment(
    JurisdictionReadiness.UNCONFIRMED, ReadinessReason.AWAITING_CONFIRMATION
)
UNSUPPORTED = JurisdictionAssessment(
    JurisdictionReadiness.UNSUPPORTED,
    ReadinessReason.JURISDICTION_NOT_SUPPORTED,
    jurisdiction="adgm",
    confirmed_at=datetime(2026, 10, 1, tzinfo=UTC),
)
NARRATIVE = "[SYNTHETIC] A team member shouted at a colleague during a shift handover."
INITIAL = {
    "incident.narrative": NARRATIVE,
    "incident.date": "2026-10-10",
    "incident.history": "new",
    "incident.discussed_with_employee": "no",
    "incident.evidence_available": "yes",
}
CONTEXT = {
    "context.location": "at_work",
    "history.same_incident_sanction": "no",
    "context.policy_awareness": "yes",
    "evidence.witnesses": "yes",
}
CLEAR = {q.key: "no" for q in SAFETY_SCREENING.questions}
FED_CASE = {**INITIAL, CASE_JURISDICTION_KEY: "uae_federal"}
COMPLETE_FED = {**FED_CASE, **CONTEXT, **CLEAR}
SCREENING_KEYS = [q.key for q in SAFETY_SCREENING.questions]
HELD = EarlierEscalation("high_risk_factors", datetime(2026, 10, 16, 9, 0, tzinfo=UTC))


def intake(
    answers: Mapping[str, object],
    company: JurisdictionAssessment,
    *,
    enabled: bool = True,
    earlier: EarlierEscalation | None = None,
) -> IntakeEvaluation:
    return evaluate_intake(
        DISCIPLINARY_V2, answers, company, screening_enabled=enabled, earlier_escalation=earlier
    )


def results(evaluation: IntakeEvaluation) -> dict[str, tuple[str, str | None, str]]:
    return {r.rule: (r.outcome, r.action, r.reason) for r in evaluation.results}


# --- predicates -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answers", "expected"),
    [
        ({}, Tri.UNKNOWN),
        ({"a": NOT_SURE}, Tri.UNKNOWN),
        ({"a": "yes"}, Tri.TRUE),
        ({"a": "no"}, Tri.FALSE),
        ({"a": 1}, Tri.FALSE),
    ],
)
def test_an_answer_predicate_never_reads_unknown_as_no(
    answers: dict[str, object], expected: Tri
) -> None:
    assert evaluate(AnswerIn("a", ("yes",)), answers) is expected


def test_not_sure_can_count_as_a_value_when_a_rule_triggers_on_not_stated() -> None:
    stated = AnswerIn("a", ("no", NOT_SURE), unknown=())
    assert evaluate(stated, {"a": NOT_SURE}) is Tri.TRUE
    assert evaluate(stated, {}) is Tri.UNKNOWN


@pytest.mark.parametrize(
    ("a", "b", "all_of", "any_of"),
    [
        ("yes", "yes", Tri.TRUE, Tri.TRUE),
        ("yes", "no", Tri.FALSE, Tri.TRUE),
        ("no", "no", Tri.FALSE, Tri.FALSE),
        ("yes", None, Tri.UNKNOWN, Tri.TRUE),
        ("no", None, Tri.FALSE, Tri.UNKNOWN),
        (None, None, Tri.UNKNOWN, Tri.UNKNOWN),
        (NOT_SURE, "no", Tri.FALSE, Tri.UNKNOWN),
    ],
)
def test_combinations_use_kleene_logic(
    a: str | None, b: str | None, all_of: Tri, any_of: Tri
) -> None:
    terms = (AnswerIn("a", ("yes",)), AnswerIn("b", ("yes",)))
    answers = {k: v for k, v in (("a", a), ("b", b)) if v is not None}
    assert evaluate(AllOf(terms), answers) is all_of
    assert evaluate(AnyOf(terms), answers) is any_of


def test_predicates_are_data_over_known_questions() -> None:
    # Triggers are dataclasses of keys and literal values: nothing executable.
    for rule in DISCIPLINARY_INTAKE.rules:
        if rule.predicate is None:
            continue
        for key in predicate_keys(rule.predicate):
            assert DISCIPLINARY_V2.question(key) is not None, key


# --- rule set -------------------------------------------------------------------------


def test_the_rule_set_is_neutral_ordered_data() -> None:
    rows = [
        (r.key, r.order, r.applies_in, r.action, r.alternate_action, r.provisional, r.enforced)
        for r in DISCIPLINARY_INTAKE.rules
    ]
    assert rows == [
        ("case_jurisdiction", 1, (), "block", "escalate", False, True),
        ("policy_awareness", 2, ("uae_federal",), "warn", None, True, True),
        ("same_incident_sanction", 3, ("uae_federal",), "warn", None, False, True),
        ("off_duty_connection", 4, ("uae_federal",), "warn", None, False, True),
        ("high_risk_screening", 5, ("uae_federal",), "escalate", None, True, True),
    ]
    assert DISCIPLINARY_INTAKE.screening_by_jurisdiction == {"uae_federal": "high_risk_screening"}
    # Keys are neutral engine identifiers, never external document references.
    for rule in DISCIPLINARY_INTAKE.rules:
        assert re.fullmatch(r"[a-z][a-z_]+", rule.key)
    assert set(DISCIPLINARY_INTAKE.data()) == {
        "version",
        "workflow_key",
        "rules",
        "screening_by_jurisdiction",
    }


def test_the_digest_changes_with_any_rule_change() -> None:
    digest = DISCIPLINARY_INTAKE.digest
    assert re.fullmatch(r"[0-9a-f]{64}", digest) and digest == DISCIPLINARY_INTAKE.digest
    second = DISCIPLINARY_INTAKE.rules[1]
    for change in (
        {"provisional": False},
        {"enforced": False},
        {"applies_in": ("uae_federal", "difc")},
        {"predicate": AnswerIn("context.policy_awareness", ("no", NOT_SURE))},
    ):
        changed = dataclasses.replace(
            DISCIPLINARY_INTAKE,
            rules=(
                DISCIPLINARY_INTAKE.rules[0],
                dataclasses.replace(second, **change),  # type: ignore[arg-type]
                *DISCIPLINARY_INTAKE.rules[2:],
            ),
        )
        assert changed.digest != digest, change


# --- jurisdiction routing -------------------------------------------------------------


@pytest.mark.parametrize(
    ("company", "answer", "status", "resolved"),
    [
        (FEDERAL, None, "awaiting_case_confirmation", None),
        (FEDERAL, "uae_federal", "resolved", "uae_federal"),
        (FEDERAL, "different", "case_different", None),
        (FEDERAL, NOT_SURE, "case_not_sure", None),
        (FEDERAL, "difc", "case_confirmation_outdated", None),
        (DIFC, "difc", "resolved", "difc"),
        (DIFC, "uae_federal", "case_confirmation_outdated", None),
        (UNCONFIRMED, "uae_federal", "company_unconfirmed", None),
        (UNCONFIRMED, None, "company_unconfirmed", None),
        (UNSUPPORTED, "uae_federal", "company_unsupported", None),
    ],
)
def test_the_case_jurisdiction_resolves_only_against_the_company_confirmation(
    company: JurisdictionAssessment, answer: str | None, status: str, resolved: str | None
) -> None:
    answers = {} if answer is None else {CASE_JURISDICTION_KEY: answer}
    case = resolve_jurisdiction(company, answers)
    assert (case.status, case.jurisdiction) == (status, resolved)


@pytest.mark.parametrize(
    ("company", "answer", "hold", "reason", "action"),
    [
        (UNCONFIRMED, None, "jurisdiction", "company_jurisdiction_unconfirmed", "block"),
        (FEDERAL, NOT_SURE, "jurisdiction", "case_jurisdiction_not_sure", "block"),
        (FEDERAL, "difc", "jurisdiction", "case_jurisdiction_outdated", "block"),
        (FEDERAL, "different", "specialist_review", "jurisdiction_different", "escalate"),
        (UNSUPPORTED, None, "specialist_review", "jurisdiction_unsupported", "escalate"),
    ],
)
def test_an_unresolved_jurisdiction_holds_and_nothing_jurisdiction_specific_runs(
    company: JurisdictionAssessment, answer: str | None, hold: str, reason: str, action: str
) -> None:
    # Every factor answered "Yes" and every caution's trigger met: none of it
    # may run while the jurisdiction is unresolved.
    answers: dict[str, object] = {
        **INITIAL,
        **{k: "yes" for k in SCREENING_KEYS},
        "context.location": "outside_work",
        "context.work_connection": "no",
        "context.policy_awareness": "no",
        "history.same_incident_sanction": "yes",
    }
    if answer is not None:
        answers[CASE_JURISDICTION_KEY] = answer
    evaluation = intake(answers, company)
    assert evaluation.hold is not None
    assert (evaluation.hold.kind, evaluation.hold.reason, evaluation.hold.action) == (
        hold,
        reason,
        action,
    )
    assert evaluation.hold.rule == "case_jurisdiction"
    assert results(evaluation)["case_jurisdiction"] == (
        "fired",
        action,
        evaluation.jurisdiction.status,
    )
    for rule, (outcome, _, why) in results(evaluation).items():
        if rule != "case_jurisdiction":
            assert (outcome, why) == ("not_applicable", "jurisdiction_unresolved")
    assert evaluation.cautions == ()
    assert evaluation.screening == "not_applicable"
    assert "safety_screening" not in evaluation.available_steps
    assert evaluation.status in ("awaiting_jurisdiction", "held_for_specialist_review")
    assert evaluation.next_stage_open is False


def test_awaiting_the_case_confirmation_is_missing_information_not_a_hold() -> None:
    evaluation = intake(INITIAL, FEDERAL)
    assert evaluation.hold is None
    assert results(evaluation)["case_jurisdiction"][0] == "unknown"
    assert CASE_JURISDICTION_KEY in evaluation.missing
    assert evaluation.status == "intake_in_progress"


def test_an_unconfirmed_company_is_not_asked_to_confirm_for_the_case() -> None:
    evaluation = intake(INITIAL, UNCONFIRMED)
    assert "jurisdiction" not in evaluation.available_steps
    assert CASE_JURISDICTION_KEY not in evaluation.asked


def test_uae_federal_resolves_and_runs_its_rules_in_order() -> None:
    evaluation = intake(COMPLETE_FED, FEDERAL)
    assert evaluation.jurisdiction.resolved
    assert evaluation.jurisdiction.jurisdiction == "uae_federal"
    assert [r.rule for r in evaluation.results] == [r.key for r in DISCIPLINARY_INTAKE.rules]
    assert {k: v[0] for k, v in results(evaluation).items()} == dict.fromkeys(
        [r.key for r in DISCIPLINARY_INTAKE.rules], "not_fired"
    )
    assert "safety_screening" in evaluation.available_steps


def test_a_difc_case_gets_no_uae_federal_rule_and_is_held_for_specialist_review() -> None:
    answers = {
        **INITIAL,
        CASE_JURISDICTION_KEY: "difc",
        # Every UAE Federal trigger would fire for a UAE Federal Case.
        "context.location": "outside_work",
        "context.work_connection": "no",
        "context.policy_awareness": "no",
        "history.same_incident_sanction": "yes",
        "evidence.witnesses": "no",
        **{k: "yes" for k in SCREENING_KEYS},
    }
    evaluation = intake(answers, DIFC)
    assert evaluation.jurisdiction.jurisdiction == "difc"
    for rule, (outcome, _, why) in results(evaluation).items():
        if rule != "case_jurisdiction":
            assert (outcome, why) == ("not_applicable", "other_jurisdiction")
    assert results(evaluation)["case_jurisdiction"] == (
        "fired",
        "escalate",
        "screening_not_covered",
    )
    assert evaluation.hold is not None
    assert (evaluation.hold.kind, evaluation.hold.reason) == (
        "specialist_review",
        "screening_not_covered",
    )
    assert evaluation.cautions == ()
    assert evaluation.screening == "not_applicable"
    assert "safety_screening" not in evaluation.available_steps
    assert not any(key in evaluation.asked for key in SCREENING_KEYS)
    assert evaluation.status == "held_for_specialist_review"
    assert evaluation.next_stage_open is False


# --- safety screening -----------------------------------------------------------------


@pytest.mark.parametrize("factor", SCREENING_KEYS)
def test_any_one_high_risk_factor_holds_the_case(factor: str) -> None:
    evaluation = intake({**COMPLETE_FED, factor: "yes"}, FEDERAL)
    assert evaluation.screening == "positive"
    assert evaluation.hold is not None
    assert (evaluation.hold.kind, evaluation.hold.reason, evaluation.hold.action) == (
        "specialist_review",
        "high_risk_factors",
        "escalate",
    )
    assert evaluation.hold.factors == (factor,)
    assert evaluation.hold.rule == "high_risk_screening"
    # Development content: the rule is still under legal review.
    assert evaluation.hold.provisional is True
    assert evaluation.currently_escalated is True
    assert evaluation.status == "held_for_specialist_review"
    assert evaluation.next_stage_open is False


def test_a_yes_holds_even_before_the_other_factors_are_answered() -> None:
    evaluation = intake({**FED_CASE, "screening.criminal_allegation": "yes"}, FEDERAL)
    assert evaluation.screening == "positive"
    assert evaluation.hold is not None and evaluation.hold.reason == "high_risk_factors"


def test_several_factors_are_all_named() -> None:
    answers = {**COMPLETE_FED, "screening.sick_leave": "yes", "screening.senior_employee": "yes"}
    evaluation = intake(answers, FEDERAL)
    assert evaluation.hold is not None
    assert evaluation.hold.factors == ("screening.sick_leave", "screening.senior_employee")


@pytest.mark.parametrize(
    ("screening", "state", "status"),
    [
        ({}, "not_started", "intake_in_progress"),
        ({SCREENING_KEYS[0]: "no"}, "incomplete", "intake_in_progress"),
        ({**CLEAR, SCREENING_KEYS[4]: NOT_SURE}, "not_cleared", "screening_not_cleared"),
        ({k: NOT_SURE for k in SCREENING_KEYS}, "not_cleared", "screening_not_cleared"),
        (CLEAR, "cleared", "intake_recorded"),
    ],
)
def test_screening_clears_only_when_every_factor_is_answered_no(
    screening: dict[str, str], state: str, status: str
) -> None:
    evaluation = intake({**FED_CASE, **CONTEXT, **screening}, FEDERAL)
    assert evaluation.screening == state
    assert evaluation.status == status
    assert evaluation.hold is None
    stop = results(evaluation)["high_risk_screening"]
    assert stop[0] == ("not_fired" if state == "cleared" else "unknown")
    assert evaluation.next_stage_open is (state == "cleared")


def test_a_cleared_intake_is_a_preliminary_status_without_legal_approval() -> None:
    evaluation = intake(COMPLETE_FED, FEDERAL)
    assert evaluation.status == "intake_recorded"
    assert evaluation.status_label == "Intake recorded"
    assert evaluation.next_stage_open is True
    assert evaluation.missing == () and evaluation.uncertain == ()
    # Nothing else is produced: no classification, decision or document.
    assert {r.action for r in evaluation.results} == {None}


# --- holds are never released by changed answers -------------------------------------


@pytest.mark.parametrize(
    ("change", "screening"),
    [
        ({"screening.sick_leave": "no"}, "cleared"),  # Yes -> No
        ({"screening.sick_leave": NOT_SURE}, "not_cleared"),  # Yes -> Not sure
        ({}, "positive"),  # still Yes
    ],
)
def test_an_earlier_escalation_stays_whatever_the_answers_change_to(
    change: dict[str, str], screening: str
) -> None:
    answers = {**COMPLETE_FED, "screening.sick_leave": "yes", **change}
    evaluation = intake(answers, FEDERAL, earlier=HELD)
    # The current answers are reported as they are...
    assert evaluation.screening == screening
    # ...but the Case stays held: no release exists, so changed answers can't be one.
    assert evaluation.hold is not None
    assert evaluation.hold.kind == "specialist_review"
    assert evaluation.status == "held_for_specialist_review"
    assert evaluation.next_stage_open is False
    if screening == "positive":
        assert evaluation.hold.reason == "high_risk_factors"
        assert evaluation.currently_escalated is True
    else:
        assert (evaluation.hold.reason, evaluation.hold.origin) == (
            "earlier_escalation",
            "high_risk_factors",
        )
        assert evaluation.hold.provisional is True
        assert evaluation.currently_escalated is False
    assert evaluation.earlier_escalation == HELD


def test_an_earlier_jurisdiction_escalation_outlasts_a_corrected_jurisdiction() -> None:
    earlier = EarlierEscalation("jurisdiction_different", HELD.since)
    evaluation = intake(COMPLETE_FED, FEDERAL, earlier=earlier)
    assert evaluation.jurisdiction.resolved
    assert evaluation.hold is not None
    assert (evaluation.hold.reason, evaluation.hold.origin) == (
        "earlier_escalation",
        "jurisdiction_different",
    )
    assert evaluation.status == "held_for_specialist_review"


def test_an_earlier_escalation_outranks_a_jurisdiction_pause() -> None:
    evaluation = intake(COMPLETE_FED, UNCONFIRMED, earlier=HELD)
    assert evaluation.hold is not None
    assert (evaluation.hold.kind, evaluation.hold.reason) == (
        "specialist_review",
        "earlier_escalation",
    )


def test_not_sure_then_no_clears_only_a_case_that_was_never_held() -> None:
    uncertain = intake({**COMPLETE_FED, "screening.whistleblower": NOT_SURE}, FEDERAL)
    assert (uncertain.status, uncertain.hold) == ("screening_not_cleared", None)
    assert intake(COMPLETE_FED, FEDERAL).status == "intake_recorded"


def test_cautions_are_recorded_but_not_shown_while_escalated_earlier() -> None:
    answers = {**COMPLETE_FED, "context.policy_awareness": "no"}
    evaluation = intake(answers, FEDERAL, earlier=HELD)
    policy = next(r for r in evaluation.results if r.rule == "policy_awareness")
    assert (policy.outcome, policy.shown) == ("fired", False)
    assert evaluation.cautions == ()


# --- the screening needs the environment's permission ---------------------------------


def test_the_screening_is_unavailable_unless_the_environment_enables_it() -> None:
    evaluation = intake({**FED_CASE, **CONTEXT}, FEDERAL, enabled=False)
    assert "safety_screening" not in evaluation.available_steps
    assert not any(key in evaluation.asked for key in SCREENING_KEYS)
    assert evaluation.screening == "disabled"
    assert results(evaluation)["high_risk_screening"] == (
        "not_applicable",
        None,
        "screening_disabled",
    )
    # Nothing is missing, yet the intake can't be recorded without the screening.
    assert evaluation.missing == ()
    assert evaluation.status == "screening_unavailable"
    assert evaluation.next_stage_open is False


def test_stored_answers_never_trigger_while_the_screening_is_disabled() -> None:
    # Answers saved in an environment that allowed the screening are ignored,
    # never evaluated, where it is disabled; the gate stays closed.
    evaluation = intake({**COMPLETE_FED, "screening.sick_leave": "yes"}, FEDERAL, enabled=False)
    assert evaluation.hold is None
    assert evaluation.status == "screening_unavailable"
    assert evaluation.next_stage_open is False


def test_a_disabled_screening_never_hides_an_earlier_escalation() -> None:
    evaluation = intake(COMPLETE_FED, FEDERAL, enabled=False, earlier=HELD)
    assert evaluation.hold is not None and evaluation.hold.reason == "earlier_escalation"
    assert evaluation.status == "held_for_specialist_review"


# --- cautions -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("location", "connection", "outcome"),
    [
        (None, None, "unknown"),
        ("at_work", None, "not_fired"),
        (NOT_SURE, None, "unknown"),
        ("outside_work", None, "unknown"),
        ("outside_work", "yes", "not_fired"),
        ("outside_work", "no", "fired"),
        # "No stated connection": Not sure states none.
        ("outside_work", NOT_SURE, "fired"),
    ],
)
def test_off_duty_conduct_without_a_stated_work_connection_is_cautioned(
    location: str | None, connection: str | None, outcome: str
) -> None:
    answers = {**COMPLETE_FED}
    answers.pop("context.location")
    if location is not None:
        answers["context.location"] = location
    if connection is not None:
        answers["context.work_connection"] = connection
    evaluation = intake(answers, FEDERAL)
    assert results(evaluation)["off_duty_connection"][0] == outcome
    shown = [c.rule for c in evaluation.cautions]
    assert ("off_duty_connection" in shown) is (outcome == "fired")


@pytest.mark.parametrize(
    ("key", "rule", "fires_on", "provisional"),
    [
        ("context.policy_awareness", "policy_awareness", "no", True),
        ("history.same_incident_sanction", "same_incident_sanction", "yes", False),
    ],
)
def test_cautions_fire_only_on_the_answer_that_triggers_them(
    key: str, rule: str, fires_on: str, provisional: bool
) -> None:
    for value in ("yes", "no", NOT_SURE):
        evaluation = intake({**COMPLETE_FED, key: value}, FEDERAL)
        cautions = {c.rule: c for c in evaluation.cautions}
        assert (rule in cautions) is (value == fires_on)
        if value == fires_on:
            assert cautions[rule].provisional is provisional
            # A caution informs; it never blocks or opens anything by itself.
            assert evaluation.status == "intake_recorded"


def test_cautions_are_recorded_but_not_shown_while_held_for_specialist_review() -> None:
    answers = {
        **COMPLETE_FED,
        "context.policy_awareness": "no",
        "screening.harassment_concern": "yes",
    }
    evaluation = intake(answers, FEDERAL)
    assert evaluation.hold is not None and evaluation.hold.reason == "high_risk_factors"
    policy = next(r for r in evaluation.results if r.rule == "policy_awareness")
    assert (policy.outcome, policy.action, policy.shown) == ("fired", "warn", False)
    assert evaluation.cautions == ()


def test_a_not_enforced_rule_is_never_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    ruleset = dataclasses.replace(
        DISCIPLINARY_INTAKE,
        rules=tuple(
            dataclasses.replace(r, enforced=False) if r.key == "policy_awareness" else r
            for r in DISCIPLINARY_INTAKE.rules
        ),
    )
    monkeypatch.setattr("app.workflows.intake.RULESETS", {"disciplinary": ruleset})
    evaluation = intake({**COMPLETE_FED, "context.policy_awareness": "no"}, FEDERAL)
    assert results(evaluation)["policy_awareness"] == ("not_applicable", None, "not_enforced")
    assert evaluation.cautions == ()
    assert evaluation.ruleset_digest == ruleset.digest != DISCIPLINARY_INTAKE.digest


def test_rules_under_legal_review_never_authorize_an_outcome() -> None:
    # The only actions any rule can take are warn, block and escalate: no rule
    # marks anything approved, lawful or available.
    assert {r.action for r in DISCIPLINARY_INTAKE.rules} <= {"warn", "block", "escalate"}
    review = [r for r in DISCIPLINARY_INTAKE.rules if r.provisional]
    assert [r.key for r in review] == ["policy_awareness", "high_risk_screening"]
    assert all(r.action in ("warn", "escalate") for r in review)
    # The next-stage gate depends only on a complete, cleared intake.
    for answers in (
        {**COMPLETE_FED, "context.policy_awareness": "no"},
        {**COMPLETE_FED, SCREENING_KEYS[0]: NOT_SURE},
        {**COMPLETE_FED, SCREENING_KEYS[0]: "yes"},
        {k: v for k, v in COMPLETE_FED.items() if k != "evidence.witnesses"},
    ):
        evaluation = intake(answers, FEDERAL)
        assert evaluation.next_stage_open is (evaluation.status == "intake_recorded")


# --- facts reused, questions asked ----------------------------------------------------


def test_previously_saved_facts_are_reused_not_asked_again() -> None:
    evaluation = intake({**FED_CASE, **CONTEXT}, FEDERAL)
    assert not any(key.startswith("incident.") for key in evaluation.missing)
    assert "history.documented_action" not in evaluation.asked
    raised = intake({**FED_CASE, **CONTEXT, "incident.history": "raised_before"}, FEDERAL)
    assert "history.documented_action" in raised.missing
    assert intake(FED_CASE, FEDERAL).jurisdiction.jurisdiction == "uae_federal"


def test_an_answer_to_a_question_no_longer_asked_is_kept_but_ignored() -> None:
    answers = {**COMPLETE_FED, "context.work_connection": "no"}  # location: at work
    evaluation = intake(answers, FEDERAL)
    assert "context.work_connection" not in evaluation.asked
    assert results(evaluation)["off_duty_connection"][0] == "not_fired"


def test_uncertain_answers_are_listed_and_counted_as_answered() -> None:
    evaluation = intake({**COMPLETE_FED, "evidence.witnesses": NOT_SURE}, FEDERAL)
    assert evaluation.uncertain == ("evidence.witnesses",)
    assert evaluation.answered == evaluation.total


# --- progress -------------------------------------------------------------------------


def test_progress_follows_the_intake() -> None:
    def items(
        answers: Mapping[str, object], company: JurisdictionAssessment, *, enabled: bool = True
    ) -> dict[str, tuple[str, str]]:
        return {
            p.key: (p.status, p.detail)
            for p in progress(DISCIPLINARY_V2, intake(answers, company, enabled=enabled))
        }

    fresh = items({}, FEDERAL)
    assert list(fresh) == [
        "case_created",
        "initial_facts",
        "jurisdiction",
        "incident_context",
        "safety_screening",
        "next_stages",
    ]
    assert fresh["jurisdiction"] == ("needs_information", "Confirm it for this case")
    assert fresh["safety_screening"] == ("blocked", "Needs the case's jurisdiction first")
    assert fresh["next_stages"] == ("coming_later", "Not available yet")

    done = items(COMPLETE_FED, FEDERAL)
    assert done["jurisdiction"] == ("completed", "UAE Federal (MOHRE)")
    assert done["safety_screening"] == ("completed", "No high-risk factors reported")
    held = items({**COMPLETE_FED, SCREENING_KEYS[2]: "yes"}, FEDERAL)
    assert held["safety_screening"] == ("blocked", "Specialist review needed")
    assert held["next_stages"] == ("blocked", "On hold")
    difc = items({**INITIAL, CASE_JURISDICTION_KEY: "difc"}, DIFC)
    assert difc["jurisdiction"] == ("completed", "DIFC")
    assert difc["safety_screening"] == ("blocked", "Not available for this jurisdiction yet")
    assert items(INITIAL, UNCONFIRMED)["jurisdiction"][0] == "blocked"
    disabled = items(FED_CASE, FEDERAL, enabled=False)
    assert disabled["safety_screening"] == ("blocked", "Not enabled in this environment")


# --- trace and history ----------------------------------------------------------------


def test_the_stored_trace_holds_codes_and_never_sensitive_answers() -> None:
    evaluation = intake({**COMPLETE_FED, "screening.sick_leave": "yes"}, FEDERAL)
    data = evaluation_results(evaluation, DISCIPLINARY_INTAKE)
    assert [d["rule"] for d in data] == [r.key for r in DISCIPLINARY_INTAKE.rules]
    stop = data[-1]
    assert (stop["outcome"], stop["action"]) == ("fired", "escalate")
    assert (stop["applies_in"], stop["provisional"], stop["enforced"]) == (
        ["uae_federal"],
        True,
        True,
    )
    # Which screening question had which answer is not copied: counts only.
    assert stop["inputs"] == {
        "sensitive_answers": {"yes": 1, "no": 8, "not_sure": 0, "unanswered": 0}
    }
    assert "screening." not in repr(data)
    assert data[0]["inputs"] == {  # the jurisdiction's basis, recorded
        "company.readiness": "supported_confirmed",
        "company.reason": "confirmed",
        "company.jurisdiction": "uae_federal",
        CASE_JURISDICTION_KEY: "uae_federal",
    }
    # Free text is never part of the trace.
    assert NARRATIVE not in repr(data)
    assert "incident.narrative" not in repr(data)


def _record(submission_id: uuid.UUID, evaluation: IntakeEvaluation) -> EvaluationRecord:
    return EvaluationRecord(
        submission_id=submission_id,
        status=evaluation.status,
        hold=None if evaluation.hold is None else evaluation.hold.kind,
        hold_reason=None if evaluation.hold is None else evaluation.hold.reason,
        jurisdiction=evaluation.jurisdiction.jurisdiction,
        screening=evaluation.screening,
        results=evaluation_results(evaluation, DISCIPLINARY_INTAKE),
    )


def test_history_records_material_intake_events_and_keeps_the_hold() -> None:
    viewer, other = uuid.uuid4(), uuid.uuid4()
    steps = [
        ("initial_facts", INITIAL, viewer),
        ("jurisdiction", {CASE_JURISDICTION_KEY: "uae_federal"}, viewer),
        ("incident_context", {**CONTEXT, "context.policy_awareness": "no"}, other),
        ("safety_screening", {**CLEAR, "screening.sick_leave": "yes"}, viewer),
        ("safety_screening", {"screening.sick_leave": "no"}, viewer),
    ]
    answers: dict[str, object] = {}
    submissions: list[SubmissionRecord] = []
    records: dict[uuid.UUID, EvaluationRecord] = {}
    earlier: EarlierEscalation | None = None
    for revision, (step, facts, by) in enumerate(steps, start=1):
        answers.update(facts)
        at = datetime(2026, 10, 16, 9, revision, tzinfo=UTC)
        submission = SubmissionRecord(uuid.uuid4(), step, revision, at, by, facts)
        submissions.append(submission)
        evaluation = intake(answers, FEDERAL, earlier=earlier)
        records[submission.id] = _record(submission.id, evaluation)
        if earlier is None and evaluation.currently_escalated and evaluation.hold is not None:
            earlier = EarlierEscalation(evaluation.hold.reason, at)
    # The first save predates M2-02: no evaluation was stored for it.
    del records[submissions[0].id]

    history = compose_history(
        DISCIPLINARY_V2,
        created_at=datetime(2026, 10, 16, 9, 0, tzinfo=UTC),
        created_by_user_id=viewer,
        submissions=submissions,
        evaluations=records,
        viewer_user_id=viewer,
    )
    assert [(h.kind, h.title) for h in history] == [
        ("case_created", "Case created"),
        ("answers_saved", "Answers saved: Initial facts"),
        ("answers_saved", "Answers saved: Employment jurisdiction"),
        ("jurisdiction", "Jurisdiction confirmed for this case: UAE Federal (MOHRE)"),
        ("answers_saved", "Answers saved: Incident context"),
        ("caution", "Caution raised: Expected standard not explained"),
        ("answers_saved", "Answers saved: Safety screening"),
        ("hold_placed", "Case held for specialist review"),
        ("screening", "High-risk factor reported in the safety screening"),
        ("answers_saved", "Answers saved: Safety screening"),
        # Never "lifted": the changed answer is recorded, the hold is kept.
        ("hold_kept", "Hold kept after answers changed"),
        ("screening", "Safety screening completed"),
    ]
    assert "hold_lifted" not in [h.kind for h in history]
    assert [h.by_viewer for h in history if h.kind == "answers_saved"] == [
        True,
        True,
        False,
        True,
        True,
    ]
    # Sensitive answers: how many changed, never which ones.
    assert history[6].detail == "Changed: 9 screening answers"
    assert history[9].detail == "Changed: 1 screening answer"
    text = " ".join(f"{h.title} {h.detail or ''}" for h in history)
    for label in [q.label for q in SAFETY_SCREENING.questions]:
        assert label not in text
    assert NARRATIVE not in text


def test_no_rule_set_metadata_reaches_the_module_namespace() -> None:
    # The public module keeps no record of external source documents.
    names = {name.lower() for name in vars(conditions)}
    for word in ("source", "sha256", "citation"):
        assert not any(word in name for name in names), word
