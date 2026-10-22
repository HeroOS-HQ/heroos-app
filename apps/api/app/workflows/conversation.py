"""The guided conversation, composed from workflow state (no AI, nothing inferred).

Every HeroOS message is neutral authored text chosen by the current state: the
definition's welcome and step introductions, an acknowledgement after each
saved answer group, the Case jurisdiction, holds, cautions, what is still
missing or uncertain, and the stages that are not available yet. The employer's
turns are the persisted submissions. Facts are stored independently
(``case_facts``); this module only presents them, so a future presentation (or
the M2 AI conversation) can change without touching the data.

Stage checklists (M2-03, ``extra_steps``) are saved like any answer group and
appear as the employer's turns too, labelled by the installed rules; the final
"what happens next" notice can be replaced by the progression's own
(``next_notice``).

Facts an Ask HeroOS turn established (M2-NEW-07, ``origin`` ``assistant``)
are never presented as answers the employer typed into a step: they appear as
one neutral notice naming what was updated (labels only, never a value).

Wording rules: no rule keys or other internal labels; no recommendation of
any disciplinary action; no promise that a HeroOS expert will review or contact
anyone (no staffed expert-review workflow exists); a high-risk answer is never
presented as a finding about the employee; changed answers are never presented
as releasing a hold.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Literal
from uuid import UUID

from app.companies.jurisdiction import JurisdictionAssessment, ReadinessReason
from app.db.models.workflow import SUBMISSION_ASSISTANT
from app.workflows.definition import (
    JURISDICTION_DIFFERENT,
    NOT_SURE,
    OptionsFrom,
    Question,
    Step,
    WorkflowDefinition,
)
from app.workflows.intake import JURISDICTION_LABELS, Caution, Hold, IntakeEvaluation

Tone = Literal["info", "caution", "success"]

ASSISTANT_ORIGIN: Final = SUBMISSION_ASSISTANT
# How an Ask HeroOS update reads in the guided conversation and the Case history.
ASSISTANT_UPDATE_TITLE: Final = "Case information updated through Ask HeroOS"

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


@dataclass(frozen=True, slots=True)
class CautionNotice:
    """A ``warn`` rule that fired: information for the employer, not a block."""

    id: str
    title: str
    body: str
    # The underlying rule is still under legal review (development content).
    provisional: bool
    kind: Literal["caution"] = "caution"


@dataclass(frozen=True, slots=True)
class HoldNotice:
    """The Case is paused (``block``) or held for specialist review (``escalate``)."""

    id: str
    action: Literal["block", "escalate"]
    # Stable code of why (app.workflows.intake.HoldReason); never a rule key.
    reason: str
    title: str
    body: str
    # What caused the hold, in plain words (for example the screening answers).
    items: tuple[str, ...]
    provisional: bool
    kind: Literal["hold"] = "hold"


Message = (
    Information
    | QuestionGroup
    | AnswerConfirmation
    | MissingInformation
    | StatusNotice
    | CautionNotice
    | HoldNotice
)


@dataclass(frozen=True, slots=True)
class SubmissionRecord:
    id: UUID
    step_key: str
    revision: int
    submitted_at: datetime
    submitted_by_user_id: UUID
    # Fact key -> value as saved by this submission (None = cleared).
    facts: Mapping[str, object]
    # ``structured`` (a step's form) or ``assistant`` (an Ask HeroOS turn, M2-NEW-07).
    origin: str = "structured"


def _jurisdiction_option_label(value: str) -> str:
    if value in JURISDICTION_LABELS:
        return f"Yes, {JURISDICTION_LABELS[value]}"
    if value == JURISDICTION_DIFFERENT:
        return "No, a different jurisdiction applies"
    return "Not sure" if value == NOT_SURE else value


def display_answer(question: Question, value: object) -> str | None:
    """How a stored answer reads back to the employer (never interpreted)."""
    if value is None:
        return None
    text = str(value)
    if question.options_from is OptionsFrom.COMPANY_JURISDICTION:
        return _jurisdiction_option_label(text)
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


# --- notices ---------------------------------------------------------------------------

# Why a Case was first held for specialist review, in plain words.
ORIGINS: Final[Mapping[str, str]] = {
    "high_risk_factors": "a screening answer needed specialist advice",
    "jurisdiction_different": "a different jurisdiction applied to this employee",
    "jurisdiction_unsupported": "the company's jurisdiction wasn't supported",
    "screening_not_covered": "no safety screening was available for the case's jurisdiction",
}

NO_EXPERT_SERVICE: Final = (
    "HeroOS doesn't offer expert review in the app yet and hasn't contacted anyone about this case."
)
ANSWERS_KEPT: Final = "Your answers stay saved."


def _company_next_step(company: JurisdictionAssessment) -> str:
    if company.reason is ReadinessReason.AWAITING_CONFIRMATION:
        return "HeroOS confirms it separately from your licensing details."
    return "A company administrator can add or update the licensing details in Company details."


def jurisdiction_notice(evaluation: IntakeEvaluation) -> StatusNotice | None:
    """The Case jurisdiction, when it isn't explained by a hold."""
    case = evaluation.jurisdiction
    if case.resolved and case.jurisdiction is not None:
        label = JURISDICTION_LABELS[case.jurisdiction]
        return StatusNotice(
            "jurisdiction",
            "info",
            "Jurisdiction confirmed for this case",
            f"You confirmed that {label} applies to this employee. HeroOS uses only checks for "
            "that jurisdiction in this case.",
        )
    if case.status == "awaiting_case_confirmation" and case.company_jurisdiction is not None:
        label = JURISDICTION_LABELS[case.company_jurisdiction]
        return StatusNotice(
            "jurisdiction",
            "info",
            "Confirm the jurisdiction for this case",
            f"Your company's employment jurisdiction is confirmed as {label}. Please confirm "
            "that it applies to this employee: until you do, HeroOS won't run any check that "
            "depends on the jurisdiction.",
        )
    return None


def hold_notice(
    hold: Hold,
    evaluation: IntakeEvaluation,
    company: JurisdictionAssessment,
    definition: WorkflowDefinition,
) -> HoldNotice:
    escalated = "Seek advice from an employment-law specialist before taking any disciplinary step."
    items: tuple[str, ...] = ()
    match hold.reason:
        case "company_jurisdiction_unconfirmed":
            title = "Paused: jurisdiction not confirmed"
            body = (
                "Your company's employment jurisdiction hasn't been confirmed yet, so HeroOS "
                f"can't run any check that depends on it. {_company_next_step(company)} "
                f"{ANSWERS_KEPT}"
            )
        case "case_jurisdiction_not_sure":
            title = "Paused: jurisdiction not confirmed for this case"
            body = (
                "You weren't sure which employment law applies to this employee. HeroOS won't "
                f"run checks that depend on the jurisdiction until you confirm it. {ANSWERS_KEPT}"
            )
        case "case_jurisdiction_outdated":
            title = "Paused: confirm the jurisdiction again"
            body = (
                "Your company's confirmed employment jurisdiction changed after you confirmed it "
                "for this case. Please confirm again which jurisdiction applies to this employee. "
                f"{ANSWERS_KEPT}"
            )
        case "jurisdiction_different":
            title = "On hold: specialist review needed"
            body = (
                "You said a different employment jurisdiction applies to this employee. HeroOS "
                "can only use your company's confirmed jurisdiction, so it can't guide this case. "
                f"{escalated} {NO_EXPERT_SERVICE} {ANSWERS_KEPT}"
            )
        case "jurisdiction_unsupported":
            title = "On hold: specialist review needed"
            body = (
                "HeroOS doesn't support your company's confirmed employment jurisdiction yet, so "
                f"it can't guide this case. {escalated} {NO_EXPERT_SERVICE} {ANSWERS_KEPT}"
            )
        case "screening_not_covered":
            label = JURISDICTION_LABELS.get(evaluation.jurisdiction.jurisdiction or "", "this")
            title = "On hold: specialist review needed"
            body = (
                f"HeroOS's safety screening isn't available for {label} cases yet, so it can't "
                "check this case for situations that need specialist advice. "
                f"{escalated} {NO_EXPERT_SERVICE} {ANSWERS_KEPT}"
            )
        case "earlier_escalation":
            title = "On hold: specialist review needed"
            body = (
                "This case was held for specialist review because of an earlier answer. Changed "
                "answers are saved, but they don't release the hold, and HeroOS can't release it "
                f"in the app yet. {escalated} {NO_EXPERT_SERVICE} {ANSWERS_KEPT}"
            )
            items = (f"First held because: {ORIGINS[hold.origin or 'high_risk_factors']}",)
        case "high_risk_factors":
            title = "On hold: specialist review needed"
            body = (
                "Your screening answers include a situation that needs specialist advice before "
                "any disciplinary step is taken or anything is put in writing to the employee. "
                "HeroOS has paused this case and won't offer further steps or guidance for it. "
                "A Yes answer isn't a finding about the employee. "
                f"{escalated} {NO_EXPERT_SERVICE} {ANSWERS_KEPT}"
            )
            labels = {q.key: q.label for s in definition.steps for q in s.questions}
            items = tuple(labels[key] for key in hold.factors)
    return HoldNotice("hold", hold.action, hold.reason, title, body, items, hold.provisional)


_CAUTIONS: Final[Mapping[str, tuple[str, str]]] = {
    "off_duty_connection": (
        "Conduct outside work",
        "You said the incident happened outside work, and no connection to work is confirmed. "
        "Conduct outside work should only be treated as a disciplinary matter where it's "
        "connected to work: for example to colleagues, clients, confidential information, "
        "safety or the company's reputation. Without such a connection, it may not be a "
        "disciplinary matter at all.",
    ),
    "policy_awareness": (
        "Expected standard not explained",
        "You said the employee hadn't been told what was expected of them. Before any "
        "sanction, check how the expected standard was communicated: a policy, a conversation, "
        "onboarding or company practice. If it genuinely wasn't, that weakens the case for "
        "any sanction.",
    ),
    "same_incident_sanction": (
        "This incident already has a sanction",
        "You said a disciplinary sanction has already been issued for this same incident. "
        "Under UAE Federal law, an employee can't be sanctioned twice for the same violation. "
        "This is about the same single incident: it doesn't apply to next steps for behaviour "
        "that is repeated or continues.",
    ),
}


def caution_notice(caution: Caution) -> CautionNotice:
    title, body = _CAUTIONS[caution.rule]
    return CautionNotice(f"caution:{caution.rule}", title, body, caution.provisional)


def caution_notices() -> Mapping[str, tuple[str, str]]:
    """Every caution's wording, by notice key (for wording checks)."""
    return _CAUTIONS


def _saved_notice(
    submission: SubmissionRecord, definition: WorkflowDefinition, extra: Mapping[str, Step]
) -> StatusNotice:
    step = definition.step(submission.step_key) or extra.get(submission.step_key)
    name = step.title if step is not None else "this step"
    return StatusNotice(
        f"saved:{submission.id}", "success", "Saved", f"Your answers to “{name}” are saved."
    )


def _assistant_notice(
    submission: SubmissionRecord, questions: Mapping[str, Question], order: Sequence[str]
) -> StatusNotice:
    labels = [questions[k].label for k in order if k in submission.facts]
    return StatusNotice(
        f"assistant:{submission.id}",
        "info",
        ASSISTANT_UPDATE_TITLE,
        "Updated: " + ", ".join(labels) + "." if labels else ASSISTANT_UPDATE_TITLE + ".",
    )


# M2-NEW-08: the current product framing of a Case's record, in the presentation layer. A
# definition's own welcome ("a guided workflow, not an AI assistant") is historical wording
# kept with its versioned definition; Ask HeroOS is where the founder talks to HeroOS now.
CASE_RECORD: Final = (
    "This is the case's record. Ask HeroOS is where you describe the situation and ask "
    "questions in your own words; here your company reviews the case details, records its own "
    "workflow decisions (the pathway and each stage) and keeps the history. HeroOS doesn't make "
    "employment decisions."
)


def record_title(definition: WorkflowDefinition) -> str:
    return f"Your {definition.title} case"


def compose(
    definition: WorkflowDefinition,
    submissions: Sequence[SubmissionRecord],
    evaluation: IntakeEvaluation,
    company: JurisdictionAssessment,
    *,
    viewer_user_id: UUID,
    extra_steps: Sequence[Step] = (),
    next_notice: StatusNotice | None = None,
) -> list[Message]:
    """The full conversation for the current state, oldest first."""
    first = definition.steps[0]
    messages: list[Message] = [
        Information("welcome", record_title(definition), CASE_RECORD),
        QuestionGroup(
            f"step:{first.key}",
            first.key,
            first.title,
            first.intro,
            tuple(q.prompt for q in first.questions if q.key in evaluation.asked),
        ),
    ]

    extra = {step.key: step for step in extra_steps}
    questions = {q.key: q for s in (*definition.steps, *extra_steps) for q in s.questions}
    order = list(questions)
    for submission in sorted(submissions, key=lambda s: s.revision):
        if submission.origin == ASSISTANT_ORIGIN:
            # Never shown as a form the employer filled in, and never restating a value.
            messages.append(_assistant_notice(submission, questions, order))
            continue
        items = tuple(
            AnsweredItem(key, questions[key].label, display_answer(questions[key], value))
            for key, value in sorted(
                submission.facts.items(),
                key=lambda kv: order.index(kv[0]) if kv[0] in questions else len(order),
            )
            if key in questions
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
        messages.append(_saved_notice(submission, definition, extra))

    notice = jurisdiction_notice(evaluation)
    if notice is not None:
        messages.append(notice)
    if evaluation.hold is not None:
        messages.append(hold_notice(evaluation.hold, evaluation, company, definition))
    messages += [caution_notice(caution) for caution in evaluation.cautions]

    for step in definition.steps:
        if step.key not in evaluation.available_steps:
            continue
        asked = [q for q in step.questions if q.key in evaluation.asked]
        missing = [q for q in asked if q.key in evaluation.missing]
        if not missing:
            continue
        if step.key != first.key and len(missing) == len(asked):
            messages.append(
                QuestionGroup(
                    f"step:{step.key}",
                    step.key,
                    step.title,
                    step.intro,
                    tuple(q.prompt for q in asked),
                )
            )
        else:
            messages.append(
                MissingInformation(
                    f"missing:{step.key}",
                    step.key,
                    f"Still to answer: {step.title}",
                    "You can answer these now or come back to them later.",
                    tuple(q.prompt for q in missing),
                )
            )

    if evaluation.uncertain:
        messages.append(
            MissingInformation(
                "uncertain",
                "",
                "Answers marked “Not sure”",
                "HeroOS never reads “Not sure” as “No”. Update these answers when you know more.",
                tuple(questions[key].label for key in evaluation.uncertain),
            )
        )

    if evaluation.hold is None and evaluation.screening == "disabled":
        messages.append(
            StatusNotice(
                "screening",
                "caution",
                "Safety screening isn't enabled here",
                "This environment doesn't collect the safety screening, so the intake can't be "
                f"completed here. {ANSWERS_KEPT}",
            )
        )
    if evaluation.hold is None and evaluation.screening == "not_cleared":
        messages.append(
            StatusNotice(
                "screening",
                "caution",
                "Safety screening not cleared",
                "One or more screening answers are “Not sure”, so the screening can't be "
                "completed. Update them when you know. If you can't find out, seek specialist "
                "advice before any disciplinary step.",
            )
        )
    if evaluation.status == "intake_recorded":
        messages.append(
            StatusNotice(
                "intake_recorded",
                "success",
                "Intake recorded",
                "The intake is complete and no high-risk factors were reported in the safety "
                "screening. This is a preliminary status, not a legal assessment: HeroOS hasn't "
                "assessed the incident or approved any action.",
            )
        )

    if next_notice is not None:
        messages.append(next_notice)
        return messages
    stages = ", ".join(stage.lower() for stage in definition.not_available)
    messages.append(
        StatusNotice(
            "next_stages",
            "info",
            "What happens next",
            (
                f"This case is on hold, so the next stages ({stages}) aren't available for it."
                if evaluation.hold is not None
                else f"The next stages of this workflow aren't available yet: {stages}."
            )
            + " Nothing in this case has been assessed or decided.",
        )
    )
    return messages
