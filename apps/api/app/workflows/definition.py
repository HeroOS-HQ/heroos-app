"""Code-defined, versioned workflow definitions (M2-01, M2-02).

A definition is data: the steps of a guided workflow and the structured
questions each step asks. Every word here is neutral, authored text: it asks
for facts and never assesses them. A Case records the definition ``version`` it
started with (``workflow_instances.definition_version``). A later version may
serve earlier Cases only when it declares them compatible: every question of
the earlier version is kept unchanged (same key, kind and options), so no
saved answer is reinterpreted (``definition_for``).

Disciplinary v2 (M2-02) keeps v1's initial facts and adds the intake: the
case's employment jurisdiction, incident context and the safety screening.
What the answers trigger lives in ``app.workflows.conditions`` and
``app.workflows.intake``, not here.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Literal

from app.db.models.workflow import WORKFLOW_DISCIPLINARY

QuestionKind = Literal["text", "date", "choice"]

# The answer value meaning "the employer doesn't know (yet)". It answers the
# question; it is never treated as a fact about the incident, and never as "No".
NOT_SURE: Final = "not_sure"


@dataclass(frozen=True, slots=True)
class Option:
    value: str
    label: str


@dataclass(frozen=True, slots=True)
class AskWhen:
    """Ask a question only while another answer is one of ``values``.

    Relevance is decided on the saved answers merged with the ones being
    saved. An answer to a question that is not asked is refused; an answer
    saved while it was asked is kept, but ignored while it is not.
    """

    key: str
    values: tuple[str, ...]


class OptionsFrom(StrEnum):
    """Options the server builds for each Case instead of fixed ones."""

    # The Company's confirmed employment jurisdiction ("yes, it applies"),
    # "a different jurisdiction applies" or "not sure".
    COMPANY_JURISDICTION = "company_jurisdiction"


class StepGate(StrEnum):
    """When a step can be answered; evaluated by ``app.workflows.intake``."""

    # The Company's employment jurisdiction is confirmed and supported.
    COMPANY_JURISDICTION_CONFIRMED = "company_jurisdiction_confirmed"
    # The Case's jurisdiction is resolved and approved screening covers it.
    SCREENING_COVERED = "screening_covered"


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
    ask_when: AskWhen | None = None
    options_from: OptionsFrom | None = None
    # Health-related or otherwise legally sensitive (the safety screening):
    # collected only where enabled (Settings.heroos_sensitive_screening), never
    # copied into evaluation traces or history details.
    sensitive: bool = False


@dataclass(frozen=True, slots=True)
class Step:
    key: str
    title: str
    intro: str
    questions: tuple[Question, ...]
    gate: StepGate | None = None

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
    # Earlier versions whose Cases this definition can serve unchanged.
    serves_versions: frozenset[int] = field(default_factory=frozenset)

    def step(self, key: str) -> Step | None:
        return next((s for s in self.steps if s.key == key), None)

    def question(self, key: str) -> Question | None:
        return next((q for s in self.steps for q in s.questions if q.key == key), None)


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

# --- Disciplinary v2 (M2-02): intake -------------------------------------------------

CASE_JURISDICTION_KEY: Final = "jurisdiction.case_confirmation"
# Case answer: this employee is employed under a different jurisdiction.
JURISDICTION_DIFFERENT: Final = "different"

JURISDICTION: Final = Step(
    key="jurisdiction",
    title="Employment jurisdiction",
    intro=(
        "HeroOS needs to know which employment law applies to this employee before it shows "
        "any checks that depend on it. Your company's employment jurisdiction was confirmed "
        "separately; please confirm that it applies to this employee."
    ),
    questions=(
        Question(
            key=CASE_JURISDICTION_KEY,
            kind="choice",
            prompt="Is this employee employed under your company's confirmed employment "
            "jurisdiction?",
            label="Employment jurisdiction for this case",
            help=(
                "Choose “No” if a different employment law applies to this employee, for "
                "example because another company employs them. HeroOS then pauses the "
                "checks that depend on the jurisdiction."
            ),
            options_from=OptionsFrom.COMPANY_JURISDICTION,
        ),
    ),
    gate=StepGate.COMPANY_JURISDICTION_CONFIRMED,
)

INCIDENT_CONTEXT: Final = Step(
    key="incident_context",
    title="Incident context",
    intro=(
        "A few more facts about the incident and its background. “Not sure” is always a valid "
        "answer, and HeroOS never reads it as “No”."
    ),
    questions=(
        Question(
            key="context.location",
            kind="choice",
            prompt="Did the incident happen at work, or while the employee was carrying out "
            "work duties?",
            label="At work or outside work",
            options=(
                Option("at_work", "Yes, at work or while working"),
                Option("outside_work", "No, outside work"),
                Option(NOT_SURE, "Not sure"),
            ),
        ),
        Question(
            key="context.work_connection",
            kind="choice",
            prompt="Is the conduct connected to work in any way?",
            label="Connection to work",
            help=(
                "For example: it involved colleagues, clients or confidential information, "
                "affected safety, or could affect the company's reputation or another "
                "legitimate business interest."
            ),
            options=YES_NO_NOT_SURE,
            ask_when=AskWhen("context.location", ("outside_work",)),
        ),
        Question(
            key="history.documented_action",
            kind="choice",
            prompt="Was the earlier action on this issue documented in writing?",
            label="Earlier action documented",
            help="For example a written reminder or a written warning letter.",
            options=(
                Option("yes", "Yes, in writing"),
                Option("verbal_only", "No, it was only raised verbally"),
                Option(NOT_SURE, "Not sure"),
            ),
            ask_when=AskWhen("incident.history", ("raised_before",)),
        ),
        Question(
            key="history.same_incident_sanction",
            kind="choice",
            prompt="Has a disciplinary sanction already been issued for this same incident?",
            label="Earlier sanction for this incident",
            help="This is about this one incident, not earlier incidents of the same kind.",
            options=YES_NO_NOT_SURE,
        ),
        Question(
            key="context.policy_awareness",
            kind="choice",
            prompt="Had the employee been told what was expected of them?",
            label="Expected standard explained",
            help=(
                "For example through a written policy, a conversation, onboarding or "
                "established company practice."
            ),
            options=YES_NO_NOT_SURE,
        ),
        Question(
            key="evidence.witnesses",
            kind="choice",
            prompt="Did anyone witness the incident?",
            label="Witnesses",
            help="You don't need to name anyone.",
            options=YES_NO_NOT_SURE,
        ),
    ),
)


def _screening(key: str, prompt: str, label: str) -> Question:
    return Question(
        key=f"screening.{key}",
        kind="choice",
        prompt=prompt,
        label=label,
        options=YES_NO_NOT_SURE,
        sensitive=True,
    )


# The high-risk factors (app.workflows.conditions).
SAFETY_SCREENING: Final = Step(
    key="safety_screening",
    title="Safety screening",
    intro=(
        "Some situations need specialist advice before any disciplinary step is taken. Answer "
        "each question with Yes, No or Not sure; screening is complete only when every answer "
        "is Yes or No. Don't add any details: HeroOS stores only your Yes, No or Not sure."
    ),
    questions=(
        _screening(
            "recent_complaint",
            "Has the employee recently complained to MOHRE or to the company's management?",
            "Recent complaint by the employee",
        ),
        _screening(
            "harassment_concern",
            "Has the employee raised a concern about harassment, bullying or discrimination?",
            "Harassment or discrimination concern",
        ),
        _screening(
            "pregnancy_maternity",
            "Is the employee pregnant or on maternity leave?",
            "Pregnancy or maternity leave",
        ),
        _screening("sick_leave", "Is the employee currently on sick leave?", "Sick leave"),
        _screening(
            "medical_condition",
            "Does the employee have a medical condition that you know of?",
            "Medical condition",
        ),
        _screening(
            "whistleblower",
            "Has the employee reported wrongdoing in the company (whistleblowing)?",
            "Whistleblowing",
        ),
        _screening("senior_employee", "Is the employee in a senior role?", "Senior role"),
        _screening(
            "criminal_allegation",
            "Is the employee involved in an allegation that could be a criminal matter?",
            "Possible criminal allegation",
        ),
        _screening(
            "dismissal_without_notice",
            "Are you considering dismissing the employee without notice?",
            "Dismissal without notice considered",
        ),
    ),
    gate=StepGate.SCREENING_COVERED,
)

DISCIPLINARY_V2: Final = WorkflowDefinition(
    key=WORKFLOW_DISCIPLINARY,
    version=2,
    title="Disciplinary",
    case_type="disciplinary",
    welcome_title="Welcome to your Disciplinary case",
    welcome=(
        "This is a guided workflow, not an AI assistant. HeroOS asks structured questions, "
        "saves your answers to this case and runs fixed checks on them. It doesn't analyse "
        "what you write, classify the incident or make any decision for you."
    ),
    steps=(INITIAL_FACTS, JURISDICTION, INCIDENT_CONTEXT, SAFETY_SCREENING),
    not_available=(
        "Classification of the incident",
        "Options and decisions",
        "Documents",
        "Expert review",
    ),
    serves_versions=frozenset({1}),
)

# The current definition of each workflow: new Cases start with it.
WORKFLOWS: Final[dict[str, WorkflowDefinition]] = {DISCIPLINARY_V2.key: DISCIPLINARY_V2}
DEFINITIONS: Final = (DISCIPLINARY_V1, DISCIPLINARY_V2)


def current_definition(workflow_key: str) -> WorkflowDefinition | None:
    return WORKFLOWS.get(workflow_key)


def definition_for(workflow_key: str, version: int) -> WorkflowDefinition | None:
    """The definition serving a Case that started with ``version``.

    The current definition when it is that version or declares it compatible;
    otherwise the definition of exactly that version, if it still exists.
    """
    current = WORKFLOWS.get(workflow_key)
    if current is not None and (current.version == version or version in current.serves_versions):
        return current
    return next(
        (d for d in DEFINITIONS if d.key == workflow_key and d.version == version),
        None,
    )
