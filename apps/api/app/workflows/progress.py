"""Case progress, derived from persisted answers and live jurisdiction readiness.

Nothing here is stored or hard-coded: progress is recomputed on every read from
the Case's facts and the Company's current jurisdiction assessment (which an
operator confirmation can change at any time). Stages that are not built yet
are reported as "coming later", never as pending results.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from app.companies.jurisdiction import JurisdictionAssessment, JurisdictionReadiness
from app.workflows.definition import Question, Step, WorkflowDefinition

ProgressStatus = Literal["completed", "in_progress", "needs_information", "blocked", "coming_later"]


@dataclass(frozen=True, slots=True)
class FactRecord:
    """One stored fact as the read path sees it, in revision order."""

    revision: int
    key: str
    value: object


@dataclass(frozen=True, slots=True)
class ProgressItem:
    key: str
    label: str
    status: ProgressStatus
    detail: str


@dataclass(frozen=True, slots=True)
class CaseStatus:
    code: str
    label: str


def latest_answers(facts: Iterable[FactRecord]) -> dict[str, object]:
    """The current answer per fact key (a later revision wins; ``None`` clears)."""
    answers: dict[str, object] = {}
    for fact in sorted(facts, key=lambda f: f.revision):
        if fact.value is None:
            answers.pop(fact.key, None)
        else:
            answers[fact.key] = fact.value
    return answers


def questions(definition: WorkflowDefinition) -> list[Question]:
    return [question for step in definition.steps for question in step.questions]


def missing_questions(step: Step, answers: Mapping[str, object]) -> list[Question]:
    return [question for question in step.questions if question.key not in answers]


def answered_count(definition: WorkflowDefinition, answers: Mapping[str, object]) -> int:
    return sum(1 for question in questions(definition) if question.key in answers)


def _step_item(step: Step, answers: Mapping[str, object]) -> ProgressItem:
    total = len(step.questions)
    done = total - len(missing_questions(step, answers))
    if done == total:
        return ProgressItem(step.key, step.title, "completed", f"All {total} questions answered")
    if done == 0:
        return ProgressItem(step.key, step.title, "needs_information", "Not started")
    return ProgressItem(step.key, step.title, "in_progress", f"{done} of {total} answered")


def _jurisdiction_item(jurisdiction: JurisdictionAssessment) -> ProgressItem:
    if jurisdiction.readiness is JurisdictionReadiness.SUPPORTED_CONFIRMED:
        return ProgressItem("jurisdiction", "Jurisdiction", "completed", "Confirmed")
    if jurisdiction.readiness is JurisdictionReadiness.UNSUPPORTED:
        return ProgressItem("jurisdiction", "Jurisdiction", "blocked", "Not supported yet")
    return ProgressItem("jurisdiction", "Jurisdiction", "blocked", "Awaiting confirmation")


def progress(
    definition: WorkflowDefinition,
    answers: Mapping[str, object],
    jurisdiction: JurisdictionAssessment,
) -> list[ProgressItem]:
    return [
        ProgressItem("case_created", "Case created", "completed", "Saved"),
        *(_step_item(step, answers) for step in definition.steps),
        _jurisdiction_item(jurisdiction),
        ProgressItem(
            "next_stages",
            "Assessment, decisions and documents",
            "coming_later",
            "Not available yet",
        ),
    ]


def case_status(
    definition: WorkflowDefinition,
    answers: Mapping[str, object],
    jurisdiction: JurisdictionAssessment,
) -> CaseStatus:
    total = len(questions(definition))
    done = answered_count(definition, answers)
    if done == 0:
        return CaseStatus("case_created", "Case created")
    if done < total:
        return CaseStatus("initial_facts_in_progress", "Initial facts in progress")
    if jurisdiction.readiness is JurisdictionReadiness.UNSUPPORTED:
        return CaseStatus("jurisdiction_unsupported", "Jurisdiction not supported yet")
    if jurisdiction.readiness is not JurisdictionReadiness.SUPPORTED_CONFIRMED:
        return CaseStatus("awaiting_jurisdiction", "Awaiting jurisdiction confirmation")
    return CaseStatus("initial_facts_completed", "Initial facts completed")
