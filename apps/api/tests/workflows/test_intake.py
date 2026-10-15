"""The Disciplinary intake rules (M2-02) without a database.

Proves, for the conditions mapped from the Conditions Library:

- the source metadata is preserved exactly (IDs, order, jurisdiction tags,
  actions, citation and enforcement statuses, source files and rows) and the
  rule-set digest changes with any of it;
- predicates are typed three-valued logic: unanswered and "Not sure" are
  UNKNOWN, never "No";
- ``JURISDICTION-ROUTING-001`` runs first and nothing jurisdiction-specific
  runs while the Case jurisdiction is unresolved; a UAE-FED condition never
  runs for a DIFC Case, which is held instead of screened;
- a high-risk answer holds the Case (a provisional, internal hold: no ticket),
  an uncertain or missing screening answer never clears the screening, and only
  a fully answered, cleared intake opens the gate to later stages;
- the stored trace holds codes and enumerated answers only.
"""

import dataclasses
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


def intake(answers: Mapping[str, object], company: JurisdictionAssessment) -> IntakeEvaluation:
    return evaluate_intake(DISCIPLINARY_V2, answers, company)


def results(evaluation: IntakeEvaluation) -> dict[str, tuple[str, str | None, str]]:
    return {r.condition_id: (r.outcome, r.action, r.reason) for r in evaluation.results}


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


def test_not_sure_can_count_as_a_value_when_the_source_says_not_stated() -> None:
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


def test_predicates_are_data_not_code() -> None:
    # Triggers are dataclasses of keys and literal values: nothing executable.
    for condition in DISCIPLINARY_INTAKE.conditions:
        if condition.predicate is None:
            continue
        for key in predicate_keys(condition.predicate):
            assert DISCIPLINARY_V2.question(key) is not None, key
    assert not hasattr(conditions, "eval_trigger")


# --- rule set -------------------------------------------------------------------------


def test_the_mapped_conditions_keep_their_source_metadata() -> None:
    rows = [
        (
            c.id,
            c.order,
            c.jurisdiction,
            c.type,
            c.action,
            c.source_action,
            c.citation_status,
            c.enforcement_status,
            c.step,
        )
        for c in DISCIPLINARY_INTAKE.conditions
    ]
    assert rows == [
        ("JURISDICTION-ROUTING-001", 1, "GLOBAL", "precondition", "block", "blocking",
         "confirmed", "active", None),
        ("POLICY-ACK-CASE", 2, "UAE-FED", "step_caution", "warn", "warn",
         "needs_legal_review", "active", "incident_context"),
        ("UAE-ONE-PENALTY-SAME-INCIDENT", 3, "UAE-FED", "step_caution", "warn", "warn",
         "confirmed", "active", "incident_context"),
        ("UAE-OFFDUTY-CONNECTION", 4, "UAE-FED", "step_caution", "warn", "warn",
         "confirmed", "active", "incident_context"),
        ("UAE-STOP-CALL-FIRST", 5, "UAE-FED", "blocking", "escalate", "escalate",
         "needs_legal_review", "active", "safety_screening"),
    ]  # fmt: skip
    routing = DISCIPLINARY_INTAKE.condition("JURISDICTION-ROUTING-001")
    assert routing.alternate_action == "escalate"
    # Workbook rows (Conditions Library sheet) and the rules they implement.
    assert [s.location for c in DISCIPLINARY_INTAKE.conditions for s in c.sources[:1]] == [
        "Conditions Library!R41",
        "Conditions Library!R5",
        "Conditions Library!R14",
        "Conditions Library!R15",
        "Conditions Library!R16",
    ]
    assert {"Rule 7", "Rule 17"} <= {s.location for s in routing.sources}
    # No jurisdiction tag was changed: the "proposed SHARED" ones stay UAE-FED.
    assert DISCIPLINARY_INTAKE.screening_by_jurisdiction == {"UAE-FED": "UAE-STOP-CALL-FIRST"}


def test_the_rule_set_pins_its_sources_and_digest() -> None:
    sources = DISCIPLINARY_INTAKE.sources
    assert sources["conditions_library"].file == "HeroOS_Conditions_Library-13.xlsx"
    assert sources["conditions_library"].sha256 == (
        "ee7cfe5afe0986b01febf6a7a8f225fa75596ec33d435aba2bad5f08fb0be57d"
    )
    assert sources["implementation_rules"].sha256 == (
        "de03a865e830b9cf0b32e93699e036a16fa6c1bd21c90dd5c9625211273d26eb"
    )
    digest = DISCIPLINARY_INTAKE.digest
    assert len(digest) == 64 and digest == DISCIPLINARY_INTAKE.digest
    # Any change of a rule or a status changes the digest.
    first = DISCIPLINARY_INTAKE.conditions[1]
    for change in (
        {"citation_status": "confirmed"},
        {"enforcement_status": "not_enforced"},
        {"jurisdiction": "SHARED"},
        {"predicate": AnswerIn("context.policy_awareness", ("no", NOT_SURE))},
    ):
        changed = dataclasses.replace(
            DISCIPLINARY_INTAKE,
            conditions=(
                DISCIPLINARY_INTAKE.conditions[0],
                dataclasses.replace(first, **change),  # type: ignore[arg-type]
                *DISCIPLINARY_INTAKE.conditions[2:],
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
    assert evaluation.hold.condition_id == "JURISDICTION-ROUTING-001"
    assert results(evaluation)["JURISDICTION-ROUTING-001"] == (
        "fired",
        action,
        evaluation.jurisdiction.status,
    )
    for condition_id, (outcome, _, why) in results(evaluation).items():
        if condition_id != "JURISDICTION-ROUTING-001":
            assert (outcome, why) == ("not_applicable", "jurisdiction_unresolved")
    assert evaluation.cautions == ()
    assert evaluation.screening == "not_applicable"
    assert "safety_screening" not in evaluation.available_steps
    assert evaluation.status in ("awaiting_jurisdiction", "held_for_specialist_review")
    assert evaluation.next_stage_open is False


def test_awaiting_the_case_confirmation_is_missing_information_not_a_hold() -> None:
    evaluation = intake(INITIAL, FEDERAL)
    assert evaluation.hold is None
    assert results(evaluation)["JURISDICTION-ROUTING-001"][0] == "unknown"
    assert CASE_JURISDICTION_KEY in evaluation.missing
    assert evaluation.status == "intake_in_progress"


def test_an_unconfirmed_company_is_not_asked_to_confirm_for_the_case() -> None:
    evaluation = intake(INITIAL, UNCONFIRMED)
    assert "jurisdiction" not in evaluation.available_steps
    assert CASE_JURISDICTION_KEY not in evaluation.asked


def test_uae_federal_resolves_and_runs_its_conditions_in_order() -> None:
    evaluation = intake(COMPLETE_FED, FEDERAL)
    assert evaluation.jurisdiction.resolved
    assert evaluation.jurisdiction.jurisdiction == "uae_federal"
    assert [r.condition_id for r in evaluation.results] == [
        c.id for c in DISCIPLINARY_INTAKE.conditions
    ]
    assert {k: v[0] for k, v in results(evaluation).items()} == {
        "JURISDICTION-ROUTING-001": "not_fired",
        "POLICY-ACK-CASE": "not_fired",
        "UAE-ONE-PENALTY-SAME-INCIDENT": "not_fired",
        "UAE-OFFDUTY-CONNECTION": "not_fired",
        "UAE-STOP-CALL-FIRST": "not_fired",
    }
    assert "safety_screening" in evaluation.available_steps


def test_a_difc_case_gets_no_uae_federal_rule_and_is_held_for_specialist_review() -> None:
    answers = {
        **INITIAL,
        CASE_JURISDICTION_KEY: "difc",
        # Every UAE-FED trigger would fire for a UAE Federal Case.
        "context.location": "outside_work",
        "context.work_connection": "no",
        "context.policy_awareness": "no",
        "history.same_incident_sanction": "yes",
        "evidence.witnesses": "no",
        **{k: "yes" for k in SCREENING_KEYS},
    }
    evaluation = intake(answers, DIFC)
    assert evaluation.jurisdiction.jurisdiction == "difc"
    for condition_id, (outcome, _, why) in results(evaluation).items():
        if condition_id != "JURISDICTION-ROUTING-001":
            assert (outcome, why) == ("not_applicable", "other_jurisdiction")
    assert results(evaluation)["JURISDICTION-ROUTING-001"] == (
        "fired",
        "escalate",
        "screening_not_covered",
    )
    assert evaluation.hold is not None
    assert (evaluation.hold.kind, evaluation.hold.reason) == (
        "specialist_review",
        "screening_not_covered",
    )
    # No Federal guidance: no caution, no screening, no Federal rule's hold.
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
    assert evaluation.hold.condition_id == "UAE-STOP-CALL-FIRST"
    # Development content: the source condition is still under legal review.
    assert evaluation.hold.provisional is True
    assert evaluation.status == "held_for_specialist_review"
    assert evaluation.next_stage_open is False


def test_a_yes_holds_even_before_the_other_factors_are_answered() -> None:
    evaluation = intake({**FED_CASE, "screening.criminal_allegation": "yes"}, FEDERAL)
    assert evaluation.screening == "positive"
    assert evaluation.hold is not None and evaluation.hold.reason == "high_risk_factors"


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
    stop = results(evaluation)["UAE-STOP-CALL-FIRST"]
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
    assert results(evaluation)["UAE-OFFDUTY-CONNECTION"][0] == outcome
    shown = [c.notice for c in evaluation.cautions]
    assert ("off_duty_connection" in shown) is (outcome == "fired")


@pytest.mark.parametrize(
    ("key", "notice", "fires_on", "provisional"),
    [
        ("context.policy_awareness", "policy_awareness", "no", True),
        ("history.same_incident_sanction", "same_incident_sanction", "yes", False),
    ],
)
def test_step_cautions_fire_only_on_the_answer_that_triggers_them(
    key: str, notice: str, fires_on: str, provisional: bool
) -> None:
    for value in ("yes", "no", NOT_SURE):
        evaluation = intake({**COMPLETE_FED, key: value}, FEDERAL)
        cautions = {c.notice: c for c in evaluation.cautions}
        assert (notice in cautions) is (value == fires_on)
        if value == fires_on:
            assert (cautions[notice].citation_status == "needs_legal_review") is provisional
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
    policy = next(r for r in evaluation.results if r.condition_id == "POLICY-ACK-CASE")
    assert (policy.outcome, policy.action, policy.shown) == ("fired", "warn", False)
    assert evaluation.cautions == ()


def test_a_not_enforced_condition_is_never_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    ruleset = dataclasses.replace(
        DISCIPLINARY_INTAKE,
        conditions=tuple(
            dataclasses.replace(c, enforcement_status="not_enforced")
            if c.id == "POLICY-ACK-CASE"
            else c
            for c in DISCIPLINARY_INTAKE.conditions
        ),
    )
    monkeypatch.setattr("app.workflows.intake.RULESETS", {"disciplinary": ruleset})
    evaluation = intake({**COMPLETE_FED, "context.policy_awareness": "no"}, FEDERAL)
    assert results(evaluation)["POLICY-ACK-CASE"] == ("not_applicable", None, "not_enforced")
    assert evaluation.cautions == ()
    assert evaluation.ruleset_digest == ruleset.digest != DISCIPLINARY_INTAKE.digest


def test_conditions_under_legal_review_never_authorize_an_outcome() -> None:
    # The only actions any condition can take are warn, block and escalate: no
    # condition marks anything approved, lawful or available.
    assert {c.action for c in DISCIPLINARY_INTAKE.conditions} <= {"warn", "block", "escalate"}
    review = [c for c in DISCIPLINARY_INTAKE.conditions if c.citation_status != "confirmed"]
    assert [c.id for c in review] == ["POLICY-ACK-CASE", "UAE-STOP-CALL-FIRST"]
    assert all(c.action in ("warn", "escalate") for c in review)
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
    # The M2-01 answers satisfy the initial facts; the "raised before" answer
    # decides whether the documented-action follow-up is asked at all.
    evaluation = intake({**FED_CASE, **CONTEXT}, FEDERAL)
    assert not any(key.startswith("incident.") for key in evaluation.missing)
    assert "history.documented_action" not in evaluation.asked
    raised = intake({**FED_CASE, **CONTEXT, "incident.history": "raised_before"}, FEDERAL)
    assert "history.documented_action" in raised.missing
    # The jurisdiction is the Company's: the Case only confirms it.
    assert intake(FED_CASE, FEDERAL).jurisdiction.jurisdiction == "uae_federal"


def test_an_answer_to_a_question_no_longer_asked_is_kept_but_ignored() -> None:
    answers = {**COMPLETE_FED, "context.work_connection": "no"}  # location: at work
    evaluation = intake(answers, FEDERAL)
    assert "context.work_connection" not in evaluation.asked
    assert results(evaluation)["UAE-OFFDUTY-CONNECTION"][0] == "not_fired"


def test_uncertain_answers_are_listed_and_counted_as_answered() -> None:
    evaluation = intake({**COMPLETE_FED, "evidence.witnesses": NOT_SURE}, FEDERAL)
    assert evaluation.uncertain == ("evidence.witnesses",)
    assert evaluation.answered == evaluation.total


# --- progress -------------------------------------------------------------------------


def test_progress_follows_the_intake() -> None:
    def items(
        answers: Mapping[str, object], company: JurisdictionAssessment
    ) -> dict[str, tuple[str, str]]:
        return {
            p.key: (p.status, p.detail) for p in progress(DISCIPLINARY_V2, intake(answers, company))
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


# --- trace and history ----------------------------------------------------------------


def test_the_stored_trace_holds_codes_and_enumerated_answers_only() -> None:
    evaluation = intake({**COMPLETE_FED, "screening.sick_leave": "yes"}, FEDERAL)
    data = evaluation_results(evaluation, DISCIPLINARY_INTAKE)
    assert [d["condition"] for d in data] == [c.id for c in DISCIPLINARY_INTAKE.conditions]
    stop = data[-1]
    assert stop["outcome"] == "fired" and stop["action"] == "escalate"
    assert stop["jurisdiction"] == "UAE-FED"
    assert stop["citation_status"] == "needs_legal_review"
    assert stop["enforcement_status"] == "active"
    assert stop["inputs"]["screening.sick_leave"] == "yes"  # type: ignore[index]
    routing = data[0]["inputs"]
    assert routing == {  # the jurisdiction's source, recorded
        "company.readiness": "supported_confirmed",
        "company.reason": "confirmed",
        "company.jurisdiction": "uae_federal",
        CASE_JURISDICTION_KEY: "uae_federal",
    }
    # The narrative (free text) is never part of the trace.
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


def test_history_records_material_intake_events_in_order() -> None:
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
    for revision, (step, facts, by) in enumerate(steps, start=1):
        answers.update(facts)
        submission = SubmissionRecord(
            uuid.uuid4(), step, revision, datetime(2026, 10, 16, 9, revision, tzinfo=UTC), by, facts
        )
        submissions.append(submission)
        records[submission.id] = _record(submission.id, intake(answers, FEDERAL))
    # The first save predates M2-02: no evaluation was stored for it.
    del records[submissions[0].id]

    history = compose_history(
        DISCIPLINARY_V2,
        DISCIPLINARY_INTAKE,
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
        ("hold_lifted", "Hold lifted after answers changed"),
        ("screening", "Safety screening completed"),
        ("intake_recorded", "Intake recorded"),
    ]
    assert [h.by_viewer for h in history if h.kind == "answers_saved"] == [
        True,
        True,
        False,
        True,
        True,
    ]
    # Labels of what changed, never the values.
    screening_saved = history[6]
    assert screening_saved.detail is not None and "Sick leave" in screening_saved.detail
    assert all("yes" not in (h.detail or "").lower().split() for h in history)
    text = " ".join(f"{h.title} {h.detail or ''}" for h in history)
    for condition in DISCIPLINARY_INTAKE.conditions:
        assert condition.id not in text
    assert NARRATIVE not in text
