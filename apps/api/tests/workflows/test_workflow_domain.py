"""The workflow domain without a database (M2-01, extended by M2-02): definitions,
validation and the conversation.

Proves the definitions store answers as given, that Disciplinary v2 serves
M2-01 Cases without reinterpreting any saved answer, that conditional and
server-built questions are validated against the Case's state, and that nothing
HeroOS says reads as an assessment, a recommendation, a finding about the
employee or a promise of expert review. The intake rules themselves are in
test_intake.py.
"""

import re
import uuid
from dataclasses import fields
from datetime import UTC, date, datetime

import pytest

from app.companies.jurisdiction import (
    JurisdictionAssessment,
    JurisdictionReadiness,
    ReadinessReason,
)
from app.workflows import conversation
from app.workflows.answers import validate_answers
from app.workflows.conditions import DISCIPLINARY_INTAKE
from app.workflows.conversation import CASE_RECORD, record_title
from app.workflows.definition import (
    CASE_JURISDICTION_KEY,
    DISCIPLINARY_V1,
    DISCIPLINARY_V2,
    INCIDENT_CONTEXT,
    INITIAL_FACTS,
    JURISDICTION,
    NOT_SURE,
    SAFETY_SCREENING,
    WORKFLOWS,
    current_definition,
    definition_for,
)
from app.workflows.intake import EarlierEscalation, evaluate_intake, question_options
from app.workflows.progress import FactRecord, latest_answers

TODAY = date(2026, 10, 15)
STEP = INITIAL_FACTS
COMPLETE = {
    "incident.narrative": "A team member left the site early on two shifts.\nNo one was told.",
    "incident.date": "2026-10-10",
    "incident.history": "new",
    "incident.discussed_with_employee": "no",
    "incident.evidence_available": NOT_SURE,
}
UNCONFIRMED = JurisdictionAssessment(
    JurisdictionReadiness.UNCONFIRMED, ReadinessReason.LICENSING_NOT_PROVIDED
)
AWAITING = JurisdictionAssessment(
    JurisdictionReadiness.UNCONFIRMED, ReadinessReason.AWAITING_CONFIRMATION
)
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
UNSUPPORTED = JurisdictionAssessment(
    JurisdictionReadiness.UNSUPPORTED,
    ReadinessReason.JURISDICTION_NOT_SUPPORTED,
    jurisdiction="adgm",
    confirmed_at=datetime(2026, 10, 1, tzinfo=UTC),
)
VIEWER = uuid.uuid4()


# --- definitions ----------------------------------------------------------------------


def test_disciplinary_v1_asks_exactly_the_five_initial_questions() -> None:
    assert [s.key for s in DISCIPLINARY_V1.steps] == ["initial_facts"]
    assert [(q.key, q.kind) for q in STEP.questions] == [
        ("incident.narrative", "text"),
        ("incident.date", "date"),
        ("incident.history", "choice"),
        ("incident.discussed_with_employee", "choice"),
        ("incident.evidence_available", "choice"),
    ]
    # Evidence is yes / no / not sure only: nothing can be uploaded yet.
    evidence = STEP.question("incident.evidence_available")
    assert evidence is not None
    assert [o.value for o in evidence.options] == ["yes", "no", NOT_SURE]


def test_v2_is_current_and_adds_the_intake_after_the_unchanged_initial_facts() -> None:
    assert current_definition("disciplinary") is DISCIPLINARY_V2
    assert current_definition("probation") is None
    assert DISCIPLINARY_V2.case_type == "disciplinary"
    assert [s.key for s in DISCIPLINARY_V2.steps] == [
        "initial_facts",
        "jurisdiction",
        "incident_context",
        "safety_screening",
    ]
    # The very same step: every M2-01 question, option and limit is unchanged.
    assert DISCIPLINARY_V2.steps[0] is DISCIPLINARY_V1.steps[0]
    keys = [q.key for s in DISCIPLINARY_V2.steps for q in s.questions]
    assert len(keys) == len(set(keys))


def test_v2_serves_m2_01_cases_and_nothing_unknown() -> None:
    # A Case keeps the version it started with; v2 declares v1 Cases
    # compatible because it reinterprets none of their answers.
    assert DISCIPLINARY_V2.serves_versions == {1}
    assert definition_for("disciplinary", 1) is DISCIPLINARY_V2
    assert definition_for("disciplinary", 2) is DISCIPLINARY_V2
    assert definition_for("disciplinary", 3) is None
    assert definition_for("probation", 1) is None
    for question in DISCIPLINARY_V1.steps[0].questions:
        assert DISCIPLINARY_V2.question(question.key) == question


def test_intake_questions_allow_not_sure_and_never_ask_for_details() -> None:
    for step in (INCIDENT_CONTEXT, SAFETY_SCREENING):
        for question in step.questions:
            assert question.kind == "choice"
            assert NOT_SURE in [o.value for o in question.options], question.key
    # Nine screening factors, each Yes / No / Not sure, nothing free-text.
    assert len(SAFETY_SCREENING.questions) == 9
    assert all(
        [o.value for o in q.options] == ["yes", "no", NOT_SURE] for q in SAFETY_SCREENING.questions
    )
    assert "Don't add any details" in SAFETY_SCREENING.intro


def test_follow_up_questions_are_asked_only_after_the_answer_that_needs_them() -> None:
    connection = INCIDENT_CONTEXT.question("context.work_connection")
    documented = INCIDENT_CONTEXT.question("history.documented_action")
    assert connection is not None and documented is not None
    assert connection.ask_when is not None
    assert (connection.ask_when.key, connection.ask_when.values) == (
        "context.location",
        ("outside_work",),
    )
    # Reuses the M2-01 answer instead of asking "raised before?" again.
    assert documented.ask_when is not None
    assert (documented.ask_when.key, documented.ask_when.values) == (
        "incident.history",
        ("raised_before",),
    )


def test_the_case_jurisdiction_options_come_from_the_company_confirmation() -> None:
    question = JURISDICTION.questions[0]
    assert question.key == CASE_JURISDICTION_KEY
    assert question.options == ()
    assert [(o.value, o.label) for o in question_options(question, FEDERAL)] == [
        ("uae_federal", "Yes, UAE Federal (MOHRE)"),
        ("different", "No, a different jurisdiction applies"),
        (NOT_SURE, "Not sure"),
    ]
    assert [o.value for o in question_options(question, DIFC)][0] == "difc"
    # No confirmed, supported Company jurisdiction: nothing to confirm.
    for assessment in (UNCONFIRMED, AWAITING, UNSUPPORTED):
        assert question_options(question, assessment) == ()


# --- wording --------------------------------------------------------------------------


EARLIER = EarlierEscalation("high_risk_factors", datetime(2026, 10, 16, 9, 0, tzinfo=UTC))


def _all_states() -> list[tuple[dict[str, object], JurisdictionAssessment]]:
    """Answers and readiness covering every hold, caution and screening state."""
    base: dict[str, object] = {**COMPLETE}
    fed = {**base, CASE_JURISDICTION_KEY: "uae_federal"}
    context = {
        "context.location": "outside_work",
        "context.work_connection": "no",
        "history.same_incident_sanction": "yes",
        "context.policy_awareness": "no",
        "evidence.witnesses": NOT_SURE,
    }
    clear = {q.key: "no" for q in SAFETY_SCREENING.questions}
    return [
        ({}, UNCONFIRMED),
        ({}, AWAITING),
        (base, UNSUPPORTED),
        (base, FEDERAL),
        ({**base, CASE_JURISDICTION_KEY: "different"}, FEDERAL),
        ({**base, CASE_JURISDICTION_KEY: NOT_SURE}, FEDERAL),
        ({**base, CASE_JURISDICTION_KEY: "difc"}, FEDERAL),
        ({**base, CASE_JURISDICTION_KEY: "difc"}, DIFC),
        ({**fed, **context, **clear}, FEDERAL),
        ({**fed, **context, **clear, "screening.sick_leave": NOT_SURE}, FEDERAL),
        ({**fed, **context, **clear, "screening.whistleblower": "yes"}, FEDERAL),
    ]


def _statements() -> list[str]:
    """Everything HeroOS *says* (not what it asks), in every state."""
    texts: list[str] = []
    for definition in WORKFLOWS.values():
        texts += [definition.title, definition.welcome_title, definition.welcome]
        texts += list(definition.not_available)
        texts += [step.intro for step in definition.steps]
    variants = (
        {"screening_enabled": True},
        {"screening_enabled": False},
        {"screening_enabled": True, "earlier_escalation": EARLIER},
    )
    for answers, company in _all_states():
        for variant in variants:
            evaluation = evaluate_intake(DISCIPLINARY_V2, answers, company, **variant)  # type: ignore[arg-type]
            for message in conversation.compose(
                DISCIPLINARY_V2, [], evaluation, company, viewer_user_id=VIEWER
            ):
                if isinstance(message, conversation.QuestionGroup | conversation.CautionNotice):
                    continue  # questions ask; cautions are checked separately
                texts += [getattr(message, "title", ""), getattr(message, "body", "")]
                texts += list(getattr(message, "items", ()))
    return texts


def _questions() -> list[str]:
    texts: list[str] = []
    for step in DISCIPLINARY_V2.steps:
        for question in step.questions:
            texts += [question.prompt, question.label, question.help or ""]
            texts += [option.label for option in question.options]
    return texts


def _cautions() -> list[str]:
    return [f"{title} {body}" for title, body in conversation.caution_notices().values()]


@pytest.mark.parametrize(
    "word",
    ["penalt", "terminat", "guilt", "misconduct", "serious", "recommend", "lawful", "eligible"],
)
def test_nothing_heroos_writes_assesses_or_recommends(word: str) -> None:
    # Facts and checks only: words like these would read as a classification,
    # an outcome, approval or advice that nothing here has produced.
    offending = [t for t in _statements() + _questions() + _cautions() if word in f" {t.lower()} "]
    assert offending == []


@pytest.mark.parametrize("word", ["sanction", "dismiss", "warning"])
def test_outcome_words_appear_only_where_a_question_or_a_caution_needs_them(word: str) -> None:
    # The screening must ask about a dismissal being considered and the
    # incident context about an earlier sanction or written warning; a caution
    # may explain the one-sanction rule. HeroOS's own statements never use
    # these words.
    assert [t for t in _statements() if word in t.lower()] == []


def test_no_message_promises_an_expert_or_names_an_internal_rule() -> None:
    texts = _statements() + _cautions()
    for phrase in ("will contact", "will review", "we'll", "ticket", "HeroOS team", "call HeroOS"):
        assert [t for t in texts if phrase.lower() in t.lower()] == []
    # Nothing claims a hold was cleared, approved or released by anyone.
    for phrase in ("cleared by", "approved by", "has been released", "hold lifted", "expert has"):
        assert [t for t in texts if phrase in t.lower()] == []
    for rule in DISCIPLINARY_INTAKE.rules:
        assert [t for t in texts + _questions() if rule.key in t] == []
    # No identifier-like tokens (reference codes) in anything a customer reads.
    identifier = re.compile(r"\b[A-Z]{2,}(?:-[A-Z0-9]{2,})+\b")
    assert [t for t in texts + _questions() if identifier.search(t)] == []


def test_the_versioned_welcome_is_historical_and_the_case_record_says_what_is_current() -> None:
    # v2's own welcome stays with its version (definition semantics are unchanged)...
    assert "not an AI assistant" in DISCIPLINARY_V2.welcome
    assert "doesn't analyse" in DISCIPLINARY_V2.welcome
    # ...but a Case's record presents the current product (M2-NEW-08): Ask HeroOS is where the
    # founder talks to HeroOS, and the Case is the formal record the employer controls.
    assert "not an AI assistant" not in CASE_RECORD and "guided workflow" not in CASE_RECORD
    assert "Ask HeroOS" in CASE_RECORD and "doesn't make employment decisions" in CASE_RECORD
    assert record_title(DISCIPLINARY_V2) == "Your Disciplinary case"


# --- validation -----------------------------------------------------------------------


def test_complete_answers_are_accepted_exactly_as_sent() -> None:
    accepted, errors = validate_answers(STEP, COMPLETE, today=TODAY)
    assert errors == []
    assert accepted == COMPLETE


def test_partial_answers_and_clearing_are_accepted() -> None:
    accepted, errors = validate_answers(
        STEP, {"incident.history": "raised_before", "incident.date": None}, today=TODAY
    )
    assert errors == []
    assert accepted == {"incident.history": "raised_before", "incident.date": None}


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("incident.unknown", "x", "is not a question of this step"),
        ("incident.narrative", "", "an answer must not be empty"),
        ("incident.narrative", "   ", "an answer must not be empty"),
        ("incident.narrative", " padded", "must not start or end with whitespace"),
        ("incident.narrative", "x" * 4001, "must be at most 4000 characters"),
        ("incident.narrative", "bell\x07", "must not contain control characters"),
        ("incident.narrative", "carriage\rreturn", "must not contain control characters"),
        ("incident.narrative", 12, "must be text"),
        ("incident.date", "15/10/2026", "must be a date (YYYY-MM-DD)"),
        ("incident.date", "20261015", "must be a date (YYYY-MM-DD)"),
        ("incident.date", "2026-02-30", "must be a date (YYYY-MM-DD)"),
        ("incident.date", "2026-10-17", "must not be in the future"),
        ("incident.date", "1989-12-31", "is too far in the past"),
        ("incident.history", "serious", "must be one of the listed options"),
        ("incident.evidence_available", "maybe", "must be one of the listed options"),
    ],
)
def test_invalid_answers_are_refused_without_echoing_them(
    key: str, value: object, message: str
) -> None:
    accepted, errors = validate_answers(STEP, {key: value}, today=TODAY)
    assert accepted == {}
    assert [(e.key, e.message) for e in errors] == [(key, message)]
    if isinstance(value, str) and value.strip():
        assert value not in errors[0].message


def test_text_may_span_lines_and_use_tabs() -> None:
    _, errors = validate_answers(STEP, {"incident.narrative": "a\n\tb"}, today=TODAY)
    assert errors == []


def test_one_invalid_answer_rejects_the_whole_group() -> None:
    accepted, errors = validate_answers(
        STEP, {**COMPLETE, "incident.history": "other"}, today=TODAY
    )
    assert accepted == {}
    assert [e.key for e in errors] == ["incident.history"]


def test_tomorrow_is_tolerated_for_time_zones() -> None:
    _, errors = validate_answers(STEP, {"incident.date": "2026-10-16"}, today=TODAY)
    assert errors == []


def test_a_follow_up_is_accepted_only_while_it_is_asked() -> None:
    connection = {"context.work_connection": "yes"}
    # Not asked: no location yet, or "at work".
    for current in ({}, {"context.location": "at_work"}):
        accepted, errors = validate_answers(
            INCIDENT_CONTEXT, connection, today=TODAY, current=current
        )
        assert accepted == {}
        assert [(e.key, e.message) for e in errors] == [
            ("context.work_connection", "is not asked for the current answers")
        ]
    # Asked: saved earlier, or answered in the same group.
    for current, answers in (
        ({"context.location": "outside_work"}, connection),
        ({}, {"context.location": "outside_work", **connection}),
    ):
        _, errors = validate_answers(INCIDENT_CONTEXT, answers, today=TODAY, current=current)
        assert errors == []
    # The parent changed in the same group: the follow-up is no longer asked.
    _, errors = validate_answers(
        INCIDENT_CONTEXT,
        {"context.location": "at_work", **connection},
        today=TODAY,
        current={"context.location": "outside_work"},
    )
    assert [e.key for e in errors] == ["context.work_connection"]
    # Clearing is always accepted.
    accepted, errors = validate_answers(
        INCIDENT_CONTEXT, {"context.work_connection": None}, today=TODAY, current={}
    )
    assert (accepted, errors) == ({"context.work_connection": None}, [])


def test_a_follow_up_can_depend_on_another_steps_answer() -> None:
    documented = {"history.documented_action": "verbal_only"}
    _, errors = validate_answers(
        INCIDENT_CONTEXT, documented, today=TODAY, current={"incident.history": "new"}
    )
    assert [e.key for e in errors] == ["history.documented_action"]
    _, errors = validate_answers(
        INCIDENT_CONTEXT, documented, today=TODAY, current={"incident.history": "raised_before"}
    )
    assert errors == []


@pytest.mark.parametrize(
    ("company", "value", "ok"),
    [
        (FEDERAL, "uae_federal", True),
        (FEDERAL, "different", True),
        (FEDERAL, NOT_SURE, True),
        # A Case can't pick a jurisdiction the Company's confirmation doesn't support.
        (FEDERAL, "difc", False),
        (DIFC, "uae_federal", False),
        (DIFC, "difc", True),
        (FEDERAL, "adgm", False),
        (UNCONFIRMED, "uae_federal", False),
    ],
)
def test_the_case_jurisdiction_accepts_only_the_server_built_options(
    company: JurisdictionAssessment, value: str, ok: bool
) -> None:
    options = {CASE_JURISDICTION_KEY: question_options(JURISDICTION.questions[0], company)}
    _, errors = validate_answers(
        JURISDICTION, {CASE_JURISDICTION_KEY: value}, today=TODAY, options=options
    )
    assert (errors == []) is ok


# --- conversation ---------------------------------------------------------------------


def test_latest_answers_replays_revisions_and_clears() -> None:
    facts = [
        FactRecord(2, "incident.history", "raised_before"),
        FactRecord(1, "incident.history", "new"),
        FactRecord(1, "incident.date", "2026-10-01"),
        FactRecord(3, "incident.date", None),
    ]
    assert latest_answers(facts) == {"incident.history": "raised_before"}


def _submission(
    revision: int,
    facts: dict[str, object],
    *,
    by: uuid.UUID = VIEWER,
    step: str = "initial_facts",
) -> conversation.SubmissionRecord:
    return conversation.SubmissionRecord(
        id=uuid.uuid4(),
        step_key=step,
        revision=revision,
        submitted_at=datetime(2026, 10, 15, 9, revision, tzinfo=UTC),
        submitted_by_user_id=by,
        facts=facts,
    )


def _compose(
    submissions: list[conversation.SubmissionRecord], company: JurisdictionAssessment
) -> list[conversation.Message]:
    answers = latest_answers(
        FactRecord(s.revision, k, v) for s in submissions for k, v in s.facts.items()
    )
    evaluation = evaluate_intake(DISCIPLINARY_V2, answers, company, screening_enabled=True)
    return conversation.compose(
        DISCIPLINARY_V2, submissions, evaluation, company, viewer_user_id=VIEWER
    )


def test_a_new_case_welcomes_asks_and_explains_what_is_not_available() -> None:
    messages = _compose([], FEDERAL)
    assert [(m.kind, m.id) for m in messages] == [
        ("information", "welcome"),
        ("question_group", "step:initial_facts"),
        ("status_notice", "jurisdiction"),
        ("missing_information", "missing:initial_facts"),
        ("question_group", "step:jurisdiction"),
        ("question_group", "step:incident_context"),
        ("status_notice", "next_stages"),
    ]
    group = messages[1]
    assert isinstance(group, conversation.QuestionGroup)
    assert group.questions == tuple(q.prompt for q in STEP.questions)
    assert messages[2].title == "Confirm the jurisdiction for this case"  # type: ignore[union-attr]
    later = messages[-1]
    assert isinstance(later, conversation.StatusNotice)
    assert "Nothing in this case has been assessed or decided" in later.body
    # Follow-up questions aren't asked before the answer that needs them.
    context = messages[5]
    assert isinstance(context, conversation.QuestionGroup)
    assert "Is the conduct connected to work in any way?" not in context.questions


def test_an_unconfirmed_company_pauses_jurisdiction_dependent_steps() -> None:
    messages = _compose([], AWAITING)
    kinds = [(m.kind, m.id) for m in messages]
    assert ("hold", "hold") in kinds
    assert ("question_group", "step:jurisdiction") not in kinds
    hold = next(m for m in messages if isinstance(m, conversation.HoldNotice))
    assert hold.action == "block"
    assert "confirms it separately" in hold.body
    assert "Your answers stay saved." in hold.body


def test_submissions_become_employer_turns_with_neutral_acknowledgements() -> None:
    other_admin = uuid.uuid4()
    submissions = [
        _submission(1, {"incident.history": "new", "incident.date": NOT_SURE}),
        _submission(
            2,
            {k: v for k, v in COMPLETE.items() if k != "incident.history"},
            by=other_admin,
        ),
        _submission(3, {CASE_JURISDICTION_KEY: "uae_federal"}, step="jurisdiction"),
    ]
    messages = _compose(submissions, FEDERAL)
    first, second, third = (m for m in messages if isinstance(m, conversation.AnswerConfirmation))
    assert first.by_viewer is True and second.by_viewer is False
    # Items follow the question order; answers read back as given.
    assert [(i.key, i.display) for i in first.items] == [
        ("incident.date", "Not sure"),
        ("incident.history", "This is a new issue"),
    ]
    assert ("incident.date", "10 October 2026") in [(i.key, i.display) for i in second.items]
    assert [(i.key, i.display) for i in third.items] == [
        (CASE_JURISDICTION_KEY, "Yes, UAE Federal (MOHRE)")
    ]
    saved = [m for m in messages if m.id.startswith("saved:")]
    assert [m.body for m in saved] == [  # type: ignore[union-attr]
        "Your answers to “Initial facts” are saved.",
        "Your answers to “Initial facts” are saved.",
        "Your answers to “Employment jurisdiction” are saved.",
    ]
    jurisdiction = next(m for m in messages if m.id == "jurisdiction")
    assert jurisdiction.title == "Jurisdiction confirmed for this case"  # type: ignore[union-attr]
    # Uncertain answers are listed, never read as "No".
    uncertain = next(m for m in messages if m.id == "uncertain")
    assert isinstance(uncertain, conversation.MissingInformation)
    # The date was "Not sure" at first, then given; only the evidence stays uncertain.
    assert uncertain.items == ("Supporting evidence",)


def test_a_cleared_answer_reads_as_removed_and_is_missing_again() -> None:
    submissions = [
        _submission(1, dict(COMPLETE)),
        _submission(2, {"incident.date": None}),
    ]
    messages = _compose(submissions, FEDERAL)
    cleared = [m for m in messages if isinstance(m, conversation.AnswerConfirmation)][1]
    assert [(i.key, i.display) for i in cleared.items] == [("incident.date", None)]
    missing = next(m for m in messages if m.id == "missing:initial_facts")
    assert missing.items == ("When did the incident happen?",)  # type: ignore[union-attr]


def test_messages_are_plain_data() -> None:
    # Presentation-independent: every message is a frozen dataclass with a kind.
    for message_type in (
        conversation.Information,
        conversation.QuestionGroup,
        conversation.AnswerConfirmation,
        conversation.MissingInformation,
        conversation.StatusNotice,
        conversation.CautionNotice,
        conversation.HoldNotice,
    ):
        assert "kind" in {f.name for f in fields(message_type)}
