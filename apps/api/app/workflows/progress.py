"""Case progress, derived from persisted answers and the live intake evaluation.

Nothing here is stored or hard-coded: progress is recomputed on every read from
the Case's facts and the Company's current jurisdiction readiness (which an
operator confirmation can change at any time), through
``app.workflows.intake``. Stages that are not built yet are reported as
"coming later", never as pending results.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Literal

from app.workflows.definition import Step, StepGate, WorkflowDefinition
from app.workflows.intake import JURISDICTION_LABELS, IntakeEvaluation, JurisdictionStatus

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


def latest_answers(facts: Iterable[FactRecord]) -> dict[str, object]:
    """The current answer per fact key (a later revision wins; ``None`` clears)."""
    answers: dict[str, object] = {}
    for fact in sorted(facts, key=lambda f: f.revision):
        if fact.value is None:
            answers.pop(fact.key, None)
        else:
            answers[fact.key] = fact.value
    return answers


_JURISDICTION_PROGRESS: Final[Mapping[JurisdictionStatus, tuple[ProgressStatus, str]]] = {
    "company_unconfirmed": ("blocked", "Your company's jurisdiction isn't confirmed yet"),
    "company_unsupported": ("blocked", "Not supported yet"),
    "awaiting_case_confirmation": ("needs_information", "Confirm it for this case"),
    "case_not_sure": ("blocked", "Not sure: confirm when you can"),
    "case_different": ("blocked", "A different jurisdiction applies"),
    "case_confirmation_outdated": ("blocked", "Confirm it again for this case"),
}


def _step_item(step: Step, evaluation: IntakeEvaluation) -> ProgressItem:
    asked = [key for key in evaluation.asked if step.question(key) is not None]
    missing = [key for key in asked if key in evaluation.missing]
    total = len(asked)
    done = total - len(missing)
    if done == total:
        return ProgressItem(step.key, step.title, "completed", f"All {total} answered")
    if done == 0:
        return ProgressItem(step.key, step.title, "needs_information", "Not started")
    return ProgressItem(step.key, step.title, "in_progress", f"{done} of {total} answered")


def _jurisdiction_item(step: Step, evaluation: IntakeEvaluation) -> ProgressItem:
    case = evaluation.jurisdiction
    if case.resolved and case.jurisdiction is not None:
        return ProgressItem(
            step.key, step.title, "completed", JURISDICTION_LABELS[case.jurisdiction]
        )
    status, detail = _JURISDICTION_PROGRESS[case.status]
    return ProgressItem(step.key, step.title, status, detail)


def _screening_item(step: Step, evaluation: IntakeEvaluation) -> ProgressItem:
    match evaluation.screening:
        case "cleared":
            return ProgressItem(step.key, step.title, "completed", "No high-risk factors reported")
        case "disabled":
            return ProgressItem(step.key, step.title, "blocked", "Not enabled in this environment")
        case "positive":
            return ProgressItem(step.key, step.title, "blocked", "Specialist review needed")
        case "not_cleared":
            return ProgressItem(
                step.key, step.title, "needs_information", "“Not sure” answers to check"
            )
        case "not_applicable":
            detail = (
                "Not available for this jurisdiction yet"
                if evaluation.jurisdiction.resolved
                else "Needs the case's jurisdiction first"
            )
            return ProgressItem(step.key, step.title, "blocked", detail)
        case _:
            return _step_item(step, evaluation)


def progress(definition: WorkflowDefinition, evaluation: IntakeEvaluation) -> list[ProgressItem]:
    items = [ProgressItem("case_created", "Case created", "completed", "Saved")]
    for step in definition.steps:
        if step.gate is StepGate.COMPANY_JURISDICTION_CONFIRMED:
            items.append(_jurisdiction_item(step, evaluation))
        elif step.gate is StepGate.SCREENING_COVERED:
            items.append(_screening_item(step, evaluation))
        else:
            items.append(_step_item(step, evaluation))
    if evaluation.hold is not None:
        items.append(ProgressItem("next_stages", "Next stages", "blocked", "On hold"))
    else:
        items.append(
            ProgressItem("next_stages", "Next stages", "coming_later", "Not available yet")
        )
    return items
