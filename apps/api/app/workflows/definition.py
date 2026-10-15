"""Code-defined, versioned workflow definitions (M2-01).

A definition is data: the steps of a guided workflow and the structured
questions each step asks. Every word here is neutral, authored text: it asks
for facts and never assesses them. A Case records the definition ``version`` it
runs (``workflow_instances.definition_version``), so a later version can change
questions without reinterpreting earlier Cases.

Only what the M2-01 slice needs exists: one Disciplinary step collecting the
initial facts. Conditions, classification, jurisdiction-specific guidance,
decisions, documents and expert review are later M2 work and are not modelled
here, not even as placeholders that could look like results.
"""

from dataclasses import dataclass
from typing import Final, Literal

from app.db.models.workflow import WORKFLOW_DISCIPLINARY

QuestionKind = Literal["text", "date", "choice"]

# The answer value meaning "the employer doesn't know (yet)". It answers the
# question; it is never treated as a fact about the incident.
NOT_SURE: Final = "not_sure"


@dataclass(frozen=True, slots=True)
class Option:
    value: str
    label: str


@dataclass(frozen=True, slots=True)
class Question:
    """One structured question; ``key`` is the fact key its answer is stored under."""

    key: str
    kind: QuestionKind
    prompt: str
    # Short label for answer summaries and missing-information lists.
    label: str
    help: str | None = None
    options: tuple[Option, ...] = ()
    max_length: int | None = None
    # ``date`` only: NOT_SURE is an accepted answer.
    allow_not_sure: bool = False


@dataclass(frozen=True, slots=True)
class Step:
    key: str
    title: str
    intro: str
    questions: tuple[Question, ...]

    def question(self, key: str) -> Question | None:
        return next((q for q in self.questions if q.key == key), None)


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    key: str
    version: int
    title: str
    # ``cases.case_type`` for Cases this workflow creates (set by the server).
    case_type: str
    welcome_title: str
    welcome: str
    steps: tuple[Step, ...]
    # Plain-language names of the stages that do not exist yet. Shown as
    # "not available yet", never as pending results.
    not_available: tuple[str, ...]

    def step(self, key: str) -> Step | None:
        return next((s for s in self.steps if s.key == key), None)


YES_NO_NOT_SURE: Final = (
    Option("yes", "Yes"),
    Option("no", "No"),
    Option(NOT_SURE, "Not sure"),
)

INITIAL_FACTS: Final = Step(
    key="initial_facts",
    title="Initial facts",
    intro=(
        "Let's start with what happened. Answer what you can now; you can add or change "
        "answers later. Keep to the facts, and leave out health, family or other personal "
        "details that aren't needed to describe the incident."
    ),
    questions=(
        Question(
            key="incident.narrative",
            kind="text",
            prompt="What happened?",
            label="What happened",
            help=(
                "Describe the incident in your own words: what happened, where, and who was "
                "involved (by role, for example “a team member”). HeroOS saves what you write "
                "as it is and doesn't analyse or classify it."
            ),
            max_length=4000,
        ),
        Question(
            key="incident.date",
            kind="date",
            prompt="When did the incident happen?",
            label="Date of the incident",
            help="Choose “Not sure” if you don't know the exact date yet.",
            allow_not_sure=True,
        ),
        Question(
            key="incident.history",
            kind="choice",
            prompt="Is this a new issue, or has it been raised before?",
            label="New or previously raised",
            options=(
                Option("new", "This is a new issue"),
                Option("raised_before", "It has been raised before"),
                Option(NOT_SURE, "Not sure"),
            ),
        ),
        Question(
            key="incident.discussed_with_employee",
            kind="choice",
            prompt="Has the matter already been discussed with the employee?",
            label="Discussed with the employee",
            options=YES_NO_NOT_SURE,
        ),
        Question(
            key="incident.evidence_available",
            kind="choice",
            prompt="Is any supporting evidence available?",
            label="Supporting evidence",
            help=(
                "For example emails, messages, records or witness accounts. You can't upload "
                "anything yet; just tell us whether it exists."
            ),
            options=YES_NO_NOT_SURE,
        ),
    ),
)

DISCIPLINARY_V1: Final = WorkflowDefinition(
    key=WORKFLOW_DISCIPLINARY,
    version=1,
    title="Disciplinary",
    case_type="disciplinary",
    welcome_title="Welcome to your Disciplinary case",
    welcome=(
        "This is a guided workflow, not an AI assistant. HeroOS asks structured questions "
        "and saves your answers to this case. It doesn't analyse what you write, classify "
        "the incident or make any decision for you."
    ),
    steps=(INITIAL_FACTS,),
    not_available=(
        "Conditions and safeguard checks",
        "Legal assessment and jurisdiction-specific guidance",
        "Documents",
        "Expert review",
    ),
)

# The current definition of each workflow. A Case keeps the version it started
# with; only version 1 exists so far.
WORKFLOWS: Final[dict[str, WorkflowDefinition]] = {DISCIPLINARY_V1.key: DISCIPLINARY_V1}
VERSIONS: Final[dict[tuple[str, int], WorkflowDefinition]] = {
    (DISCIPLINARY_V1.key, DISCIPLINARY_V1.version): DISCIPLINARY_V1
}


def current_definition(workflow_key: str) -> WorkflowDefinition | None:
    return WORKFLOWS.get(workflow_key)


def definition_for(workflow_key: str, version: int) -> WorkflowDefinition | None:
    return VERSIONS.get((workflow_key, version))
