"""The M2-01 workflow domain without a database: definition, validation,
progress and conversation. Proves the slice stores answers as given, derives
progress only from them and the live jurisdiction readiness, and never says
anything that reads as an assessment, a sanction or a legal conclusion.
"""

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
from app.workflows.definition import (
    DISCIPLINARY_V1,
    NOT_SURE,
    WORKFLOWS,
    current_definition,
    definition_for,
)
from app.workflows.progress import (
    FactRecord,
    answered_count,
    case_status,
    latest_answers,
    progress,
)

TODAY = date(2026, 10, 15)
STEP = DISCIPLINARY_V1.steps[0]
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
CONFIRMED = JurisdictionAssessment(
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


# --- definition -----------------------------------------------------------------------


def test_disciplinary_v1_asks_exactly_the_five_initial_questions() -> None:
    assert current_definition("disciplinary") is DISCIPLINARY_V1
    assert definition_for("disciplinary", 1) is DISCIPLINARY_V1
    assert current_definition("probation") is None
    assert definition_for("disciplinary", 2) is None
    assert DISCIPLINARY_V1.case_type == "disciplinary"
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


def _authored_text() -> list[str]:
    texts: list[str] = []
    for definition in WORKFLOWS.values():
        texts += [definition.title, definition.welcome_title, definition.welcome]
        texts += list(definition.not_available)
        for step in definition.steps:
            texts += [step.title, step.intro]
            for question in step.questions:
                texts += [question.prompt, question.label, question.help or ""]
                texts += [option.label for option in question.options]
    for assessment in (UNCONFIRMED, AWAITING, CONFIRMED, UNSUPPORTED):
        notice = conversation.jurisdiction_notice(assessment)
        texts += [notice.title, notice.body]
    return texts


@pytest.mark.parametrize(
    "word",
    [
        "penalt",
        "sanction",
        "dismiss",
        "terminat",
        "guilt",
        "misconduct",
        "serious",
        "warning",
        "recommend",
        "lawful",
        "eligible",
    ],
)
def test_authored_text_never_assesses_or_recommends(word: str) -> None:
    # The slice collects facts only. Words like these would read as a
    # classification, an outcome or advice that nothing here has produced.
    offending = [text for text in _authored_text() if word in f" {text.lower()} "]
    assert offending == []


def test_welcome_says_the_workflow_is_guided_not_ai() -> None:
    assert "not an AI assistant" in DISCIPLINARY_V1.welcome
    assert "doesn't analyse" in DISCIPLINARY_V1.welcome


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


# --- progress -------------------------------------------------------------------------


def test_latest_answers_replays_revisions_and_clears() -> None:
    facts = [
        FactRecord(2, "incident.history", "raised_before"),
        FactRecord(1, "incident.history", "new"),
        FactRecord(1, "incident.date", "2026-10-01"),
        FactRecord(3, "incident.date", None),
    ]
    assert latest_answers(facts) == {"incident.history": "raised_before"}


@pytest.mark.parametrize(
    ("answers", "jurisdiction", "code", "facts_status", "facts_detail", "jurisdiction_status"),
    [
        ({}, UNCONFIRMED, "case_created", "needs_information", "Not started", "blocked"),
        (
            {"incident.history": "new"},
            CONFIRMED,
            "initial_facts_in_progress",
            "in_progress",
            "1 of 5 answered",
            "completed",
        ),
        (
            COMPLETE,
            UNCONFIRMED,
            "awaiting_jurisdiction",
            "completed",
            "All 5 questions answered",
            "blocked",
        ),
        (COMPLETE, UNSUPPORTED, "jurisdiction_unsupported", "completed", None, "blocked"),
        (COMPLETE, CONFIRMED, "initial_facts_completed", "completed", None, "completed"),
    ],
)
def test_progress_and_status_follow_answers_and_live_jurisdiction(
    answers: dict[str, object],
    jurisdiction: JurisdictionAssessment,
    code: str,
    facts_status: str,
    facts_detail: str | None,
    jurisdiction_status: str,
) -> None:
    assert case_status(DISCIPLINARY_V1, answers, jurisdiction).code == code
    items = {item.key: item for item in progress(DISCIPLINARY_V1, answers, jurisdiction)}
    assert list(items) == ["case_created", "initial_facts", "jurisdiction", "next_stages"]
    assert items["case_created"].status == "completed"
    assert items["initial_facts"].status == facts_status
    if facts_detail is not None:
        assert items["initial_facts"].detail == facts_detail
    assert items["jurisdiction"].status == jurisdiction_status
    # Later stages are never reported as anything but "coming later".
    assert items["next_stages"].status == "coming_later"
    assert answered_count(DISCIPLINARY_V1, answers) == len(answers)


# --- conversation ---------------------------------------------------------------------


def _submission(
    revision: int, facts: dict[str, object], *, by: uuid.UUID = VIEWER
) -> conversation.SubmissionRecord:
    return conversation.SubmissionRecord(
        id=uuid.uuid4(),
        step_key="initial_facts",
        revision=revision,
        submitted_at=datetime(2026, 10, 15, 9, revision, tzinfo=UTC),
        submitted_by_user_id=by,
        facts=facts,
    )


def test_a_new_case_welcomes_asks_and_explains_what_is_not_available() -> None:
    messages = conversation.compose(DISCIPLINARY_V1, [], UNCONFIRMED, viewer_user_id=VIEWER)
    assert [m.kind for m in messages] == [
        "information",
        "question_group",
        "missing_information",
        "status_notice",
        "status_notice",
    ]
    welcome, group, missing, jurisdiction, later = messages
    assert isinstance(group, conversation.QuestionGroup)
    assert group.questions == tuple(q.prompt for q in STEP.questions)
    assert isinstance(missing, conversation.MissingInformation)
    assert len(missing.items) == 5
    assert isinstance(jurisdiction, conversation.StatusNotice)
    assert jurisdiction.id == "jurisdiction" and jurisdiction.tone == "caution"
    assert "can't continue" in jurisdiction.body
    assert isinstance(later, conversation.StatusNotice)
    assert later.id == "next_stages"
    assert "Nothing in this case has been assessed or decided" in later.body


def test_submissions_become_employer_turns_with_neutral_acknowledgements() -> None:
    other_admin = uuid.uuid4()
    submissions = [
        _submission(1, {"incident.history": "new", "incident.date": NOT_SURE}),
        _submission(
            2,
            {k: v for k, v in COMPLETE.items() if k != "incident.history"},
            by=other_admin,
        ),
    ]
    messages = conversation.compose(DISCIPLINARY_V1, submissions, CONFIRMED, viewer_user_id=VIEWER)
    kinds = [m.kind for m in messages]
    assert kinds == [
        "information",
        "question_group",
        "answer_confirmation",
        "status_notice",
        "answer_confirmation",
        "status_notice",
        "information",
        "status_notice",
        "status_notice",
    ]
    first, second = messages[2], messages[4]
    assert isinstance(first, conversation.AnswerConfirmation)
    assert isinstance(second, conversation.AnswerConfirmation)
    assert first.by_viewer is True and second.by_viewer is False
    # Items follow the question order; answers read back as given.
    assert [(i.key, i.display) for i in first.items] == [
        ("incident.date", "Not sure"),
        ("incident.history", "This is a new issue"),
    ]
    assert ("incident.date", "10 October 2026") in [(i.key, i.display) for i in second.items]
    assert messages[3].body.startswith("2 of 5 initial questions answered")  # type: ignore[union-attr]
    assert messages[5].body == "All initial questions are answered."  # type: ignore[union-attr]
    complete = messages[6]
    assert isinstance(complete, conversation.Information)
    assert "hasn't assessed them" in complete.body
    assert messages[7].title == "Jurisdiction confirmed"  # type: ignore[union-attr]


def test_a_cleared_answer_reads_as_removed_and_is_missing_again() -> None:
    submissions = [
        _submission(1, dict(COMPLETE)),
        _submission(2, {"incident.date": None}),
    ]
    messages = conversation.compose(
        DISCIPLINARY_V1, submissions, UNCONFIRMED, viewer_user_id=VIEWER
    )
    cleared = messages[4]
    assert isinstance(cleared, conversation.AnswerConfirmation)
    assert [(i.key, i.display) for i in cleared.items] == [("incident.date", None)]
    missing = [m for m in messages if isinstance(m, conversation.MissingInformation)]
    assert [m.items for m in missing] == [("When did the incident happen?",)]


@pytest.mark.parametrize(
    ("assessment", "title", "phrase"),
    [
        (UNCONFIRMED, "Jurisdiction not confirmed yet", "Company details"),
        (AWAITING, "Jurisdiction not confirmed yet", "confirms it separately"),
        (UNSUPPORTED, "Jurisdiction not supported yet", "can't continue"),
        (CONFIRMED, "Jurisdiction confirmed", "isn't available yet"),
    ],
)
def test_jurisdiction_notice_reflects_readiness_without_naming_rules(
    assessment: JurisdictionAssessment, title: str, phrase: str
) -> None:
    notice = conversation.jurisdiction_notice(assessment)
    assert notice.title == title
    assert phrase in notice.body
    # The notice never names a legal regime or article.
    for name in ("DIFC", "MOHRE", "Federal", "Article"):
        assert name not in notice.body


def test_messages_are_plain_data() -> None:
    # Presentation-independent: every message is a frozen dataclass with a kind.
    for message_type in (
        conversation.Information,
        conversation.QuestionGroup,
        conversation.AnswerConfirmation,
        conversation.MissingInformation,
        conversation.StatusNotice,
    ):
        assert "kind" in {f.name for f in fields(message_type)}
