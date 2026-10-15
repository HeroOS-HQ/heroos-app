"""The guided conversation, composed from workflow state (no AI, nothing inferred).

Every HeroOS message is neutral authored text chosen by the current state: the
definition's welcome and step introduction, an acknowledgement after each saved
answer group, what is still missing, the Company's jurisdiction readiness and
the stages that are not available yet. The employer's turns are the persisted
submissions. Facts are stored independently (``case_facts``); this module only
presents them, so a future presentation (or an M4 assistant) can change without
touching the data.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Literal
from uuid import UUID

from app.companies.jurisdiction import (
    JurisdictionAssessment,
    JurisdictionReadiness,
    ReadinessReason,
)
from app.workflows.definition import NOT_SURE, Question, WorkflowDefinition
from app.workflows.progress import FactRecord, latest_answers, missing_questions, questions

Tone = Literal["info", "caution", "success"]

_MONTHS: Final = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


@dataclass(frozen=True, slots=True)
class Information:
    id: str
    title: str
    body: str
    kind: Literal["information"] = "information"


@dataclass(frozen=True, slots=True)
class QuestionGroup:
    id: str
    step_key: str
    title: str
    body: str
    questions: tuple[str, ...]
    kind: Literal["question_group"] = "question_group"


@dataclass(frozen=True, slots=True)
class AnsweredItem:
    key: str
    label: str
    # None: the answer was removed in this submission.
    display: str | None


@dataclass(frozen=True, slots=True)
class AnswerConfirmation:
    id: str
    step_key: str
    submitted_at: datetime
    by_viewer: bool
    items: tuple[AnsweredItem, ...]
    kind: Literal["answer_confirmation"] = "answer_confirmation"


@dataclass(frozen=True, slots=True)
class MissingInformation:
    id: str
    step_key: str
    title: str
    body: str
    items: tuple[str, ...]
    kind: Literal["missing_information"] = "missing_information"


@dataclass(frozen=True, slots=True)
class StatusNotice:
    id: str
    tone: Tone
    title: str
    body: str
    kind: Literal["status_notice"] = "status_notice"


Message = Information | QuestionGroup | AnswerConfirmation | MissingInformation | StatusNotice


@dataclass(frozen=True, slots=True)
class SubmissionRecord:
    id: UUID
    step_key: str
    revision: int
    submitted_at: datetime
    submitted_by_user_id: UUID
    # Fact key -> value as saved by this submission (None = cleared).
    facts: Mapping[str, object]


def display_answer(question: Question, value: object) -> str | None:
    """How a stored answer reads back to the employer (never interpreted)."""
    if value is None:
        return None
    text = str(value)
    if question.kind == "choice":
        return next((option.label for option in question.options if option.value == text), text)
    if question.kind == "date":
        if text == NOT_SURE:
            return "Not sure"
        try:
            parsed = date.fromisoformat(text)
        except ValueError:
            return text
        return f"{parsed.day} {_MONTHS[parsed.month - 1]} {parsed.year}"
    return text


def jurisdiction_notice(jurisdiction: JurisdictionAssessment) -> StatusNotice:
    if jurisdiction.readiness is JurisdictionReadiness.SUPPORTED_CONFIRMED:
        return StatusNotice(
            "jurisdiction",
            "info",
            "Jurisdiction confirmed",
            "Your company's employment jurisdiction is confirmed. Jurisdiction-specific "
            "guidance for this workflow isn't available yet.",
        )
    if jurisdiction.readiness is JurisdictionReadiness.UNSUPPORTED:
        return StatusNotice(
            "jurisdiction",
            "caution",
            "Jurisdiction not supported yet",
            "HeroOS doesn't support your company's confirmed employment jurisdiction yet, so "
            "jurisdiction-specific guidance can't continue for this case. Your answers stay saved.",
        )
    next_step = (
        "HeroOS confirms it separately from your licensing details."
        if jurisdiction.reason is ReadinessReason.AWAITING_CONFIRMATION
        else "A company administrator can add or update the licensing details in Company details."
    )
    return StatusNotice(
        "jurisdiction",
        "caution",
        "Jurisdiction not confirmed yet",
        "Your company's employment jurisdiction hasn't been confirmed, so HeroOS can't continue "
        f"with any jurisdiction-specific guidance. {next_step} Your answers stay saved.",
    )


def _saved_notice(
    submission: SubmissionRecord, answers: Mapping[str, object], total: int
) -> StatusNotice:
    done = len(answers)
    body = (
        "All initial questions are answered."
        if done >= total
        else f"{done} of {total} initial questions answered. You can add the rest whenever "
        "you're ready."
    )
    return StatusNotice(f"saved:{submission.id}", "success", "Saved", body)


def compose(
    definition: WorkflowDefinition,
    submissions: Sequence[SubmissionRecord],
    jurisdiction: JurisdictionAssessment,
    *,
    viewer_user_id: UUID,
) -> list[Message]:
    """The full conversation for the current state, oldest first."""
    messages: list[Message] = [
        Information("welcome", definition.welcome_title, definition.welcome),
    ]
    for step in definition.steps:
        messages.append(
            QuestionGroup(
                f"step:{step.key}",
                step.key,
                step.title,
                step.intro,
                tuple(question.prompt for question in step.questions),
            )
        )

    all_questions = {question.key: question for question in questions(definition)}
    order = list(all_questions)
    replayed: list[FactRecord] = []
    for submission in sorted(submissions, key=lambda s: s.revision):
        items = tuple(
            AnsweredItem(key, all_questions[key].label, display_answer(all_questions[key], value))
            for key, value in sorted(
                submission.facts.items(),
                key=lambda kv: order.index(kv[0]) if kv[0] in all_questions else len(order),
            )
            if key in all_questions
        )
        messages.append(
            AnswerConfirmation(
                f"submission:{submission.id}",
                submission.step_key,
                submission.submitted_at,
                submission.submitted_by_user_id == viewer_user_id,
                items,
            )
        )
        replayed.extend(
            FactRecord(submission.revision, key, value) for key, value in submission.facts.items()
        )
        current = {k: v for k, v in latest_answers(replayed).items() if k in all_questions}
        messages.append(_saved_notice(submission, current, len(all_questions)))

    answers = latest_answers(replayed)
    for step in definition.steps:
        missing = missing_questions(step, answers)
        if missing:
            messages.append(
                MissingInformation(
                    f"missing:{step.key}",
                    step.key,
                    "Still to answer",
                    "You can answer these now or come back to them later.",
                    tuple(question.prompt for question in missing),
                )
            )
        else:
            messages.append(
                Information(
                    f"complete:{step.key}",
                    f"{step.title} recorded",
                    "HeroOS has saved your answers. It hasn't assessed them: they are kept for the "
                    "next stages of this workflow.",
                )
            )

    messages.append(jurisdiction_notice(jurisdiction))
    messages.append(
        StatusNotice(
            "next_stages",
            "info",
            "What happens next",
            "The next stages of this workflow aren't available yet: "
            + ", ".join(stage.lower() for stage in definition.not_available)
            + ". Nothing in this case has been assessed or decided.",
        )
    )
    return messages
