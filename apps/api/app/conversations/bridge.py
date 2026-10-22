"""From an Ask HeroOS turn to its Case: the workflow threshold, a safe title and the facts.

Pure: it decides, it never writes (``app.conversations.service`` persists
through ``app.cases.mutation``, the same pipeline as a step's form).

**One conversation is one Case** (chat-first): the founder's first message
starts both, before HeroOS knows what the matter is ("Hi Hannah" included).
Such a Case is ``unclassified``: no workflow, no facts, titled "New case".

**A workflow attaches** to that same Case only when the turn's deterministic
evaluation says the matter is a supported HR matter of an established workflow
from the approved catalog that has a real ``WorkflowDefinition``; the founder
hasn't blended separate matters; the Case has no workflow yet and the
conversation established no other one. Anything else leaves the Case
unclassified (an unclear request, another HR matter, staffing strategy, a
non-HR question).

**Its title** is never typed by anyone and never names a person: "New case"
until a workflow attaches, then a neutral label for the kind of matter, from a
closed server-owned map of approved topic keys, else the workflow and the date
("Disciplinary case · 22 Oct"). A title only ever becomes more specific (a
topic label is never replaced). A topic about an employer decision or sanction
never becomes a title, and neither does the AI's pathway candidate.

**The narrative** ("What happened?") is the founder's own words: the message
that established the matter is saved as they wrote it when its workflow
attaches (never the AI's summary or reading of it).

**Facts** reach the Case only as ENGINE_TRUSTED canonical values (M2-NEW-06)
of a non-sensitive Case question the founder established in this
conversation (a direct answer, a confirmation, or an earlier turn's before the
Case existed), never a PROPOSED or conversational reading, a Blueprint value,
a value the Case itself supplied, the jurisdiction, or a requested action.
A value equal to the Case's current one is never stored again.

What is checked is the *value*, not the founder's path through the form:

- the question must be one of the Case definition's own steps (a stage
  checklist of the progression rules is never written from a conversation: it
  belongs to a stage the employer starts);
- its step's *semantic workflow gate* must be open (``StepGate``: the
  Company's jurisdiction confirmed, the screening covered). An ungated step is
  always open: the founder never has to have opened it in the form;
- the value must pass the form's own validator (``validate_answers``): an
  option of the question, and asked for the current answers (``AskWhen``: a
  follow-up only once its premise is known). A trusted value that can't be
  saved yet stays in the checkpoint and is saved by the turn that makes it
  valid.

**Noted readings** (``noted_facts``): what the founder said in passing (an
ESTABLISHED_CONVERSATIONAL reading, "it happened last month too, we spoke to
him then") is never trusted on the AI's reading. The server canonicalizes it
against the Case question and checks it like a fact; it is then shown for the
employer to save to the Case with one explicit action, never saved by itself.
"""

from collections.abc import Collection, Mapping
from datetime import date
from typing import Final

from app.assistant.gateway.service import Handoff
from app.evaluation.facts import canonical
from app.evaluation.model import ConversationEvaluation
from app.evaluation.snapshot import WorkflowExecution
from app.workflows.answers import validate_answers
from app.workflows.definition import NOT_SURE, WorkflowDefinition, current_definition

# The title of a Case whose workflow isn't known yet.
NEW_CASE_TITLE: Final = "New case"
# The Case question that holds the founder's own description of what happened.
NARRATIVE_KEY: Final = "incident.narrative"

# Approved topic key -> a neutral label for the kind of matter (never a sanction, an
# employer decision or a person). Every other topic gives the fallback title. Adding a
# label is a product content decision.
TOPIC_TITLES: Final[Mapping[str, str]] = {
    "misconduct_level": "Conduct concern",
}


def multiple_matters(evaluation: ConversationEvaluation, handoff: Handoff) -> bool:
    """The founder described separate matters (never blended into one Case)."""
    return evaluation.multiple_matters or "multiple_matters" in handoff.uncertainties


def case_definition(
    evaluation: ConversationEvaluation | None,
    handoff: Handoff,
    *,
    conversation_workflow: str | None,
    has_case: bool,
) -> WorkflowDefinition | None:
    """The workflow the conversation's Case takes now, or None: it stays as it is.

    ``has_case``: the Case already runs a workflow (it never switches to another).
    """
    if has_case or evaluation is None:
        return None
    if evaluation.matter != "supported" or evaluation.workflow is None:
        return None
    if multiple_matters(evaluation, handoff):
        return None
    if conversation_workflow not in (None, evaluation.workflow):
        return None  # never switches to another workflow
    return current_definition(evaluation.workflow)


def established_workflow(evaluation: ConversationEvaluation | None) -> str | None:
    """The supported workflow (with a definition) this turn established, if any."""
    if evaluation is None or evaluation.matter != "supported" or evaluation.workflow is None:
        return None
    definition = current_definition(evaluation.workflow)
    return None if definition is None else definition.key


def case_title(handoff: Handoff, definition: WorkflowDefinition, today: date) -> str:
    for topic in handoff.topics:
        label = TOPIC_TITLES.get(topic)
        if label is not None:
            return label
    return f"{definition.title} case · {today.day} {today:%b}"


def _specificity(title: str) -> int:
    if title == NEW_CASE_TITLE:
        return 0
    return 2 if title in TOPIC_TITLES.values() else 1


def better_title(
    current: str, handoff: Handoff, definition: WorkflowDefinition, today: date
) -> str | None:
    """A more specific server title for a Case of ``definition``, or None (keep ``current``)."""
    title = case_title(handoff, definition, today)
    return title if _specificity(title) > _specificity(current) else None


def fact_changes(
    evaluation: ConversationEvaluation,
    execution: WorkflowExecution,
    definition: WorkflowDefinition,
    *,
    current: Mapping[str, object],
    open_steps: Collection[str],
    from_case: Collection[str],
    today: date,
) -> dict[str, str]:
    """Case question key -> the new canonical value, for the shared mutation pipeline."""
    engine, sources = evaluation.facts.engine, evaluation.facts.sources
    candidates: dict[str, str] = {}
    for key, value in engine.items():
        source = sources.get(key)
        if source == "blueprint":
            continue  # context the Blueprint holds, never a Case fact
        if source == "continuation" and key in from_case:
            continue  # the Case's own value, carried into this turn
        question = _case_question(execution, definition, key)
        if question is None or not isinstance(value, str):
            continue
        candidates[question] = value
    return _accepted(candidates, definition, current=current, open_steps=open_steps, today=today)


def _case_question(
    execution: WorkflowExecution, definition: WorkflowDefinition, key: str
) -> str | None:
    """The non-sensitive Case question a fact key holds a canonical value of, if any."""
    schema = execution.schemas.get(key)
    if schema is None or schema.question is None:
        return None
    question = definition.question(schema.question)
    if question is None or question.sensitive or question.options_from is not None:
        return None
    return question.key


def noted_facts(
    evaluation: ConversationEvaluation,
    execution: WorkflowExecution,
    definition: WorkflowDefinition,
    *,
    current: Mapping[str, object],
    open_steps: Collection[str],
    today: date,
) -> dict[str, str]:
    """Case question key -> the server's canonical reading of what the founder said in passing.

    Only ESTABLISHED_CONVERSATIONAL readings (explicit, evidence-checked, not
    contradicted) that aren't trusted already, canonicalized by the server
    (never the AI's value as written) and valid for the Case now. Never saved
    here: the employer saves them, or not.
    """
    facts = evaluation.facts
    candidates: dict[str, str] = {}
    for key, said in facts.conversational.items():
        if key in facts.engine:
            continue  # trusted: saved (or waiting) through the fact pipeline
        question = _case_question(execution, definition, key)
        schema = execution.schemas.get(key)
        if question is None or schema is None:
            continue
        value = canonical(schema, said)
        if isinstance(value, str):
            candidates[question] = value
    return _accepted(candidates, definition, current=current, open_steps=open_steps, today=today)


def narrative_change(
    definition: WorkflowDefinition,
    message: str,
    *,
    current: Mapping[str, object],
    open_steps: Collection[str],
    today: date,
) -> dict[str, str]:
    """The founder's own words as the Case's narrative, when the Case has none yet."""
    if current.get(NARRATIVE_KEY) is not None or definition.question(NARRATIVE_KEY) is None:
        return {}
    return _accepted(
        {NARRATIVE_KEY: message.strip()},
        definition,
        current=current,
        open_steps=open_steps,
        today=today,
    )


def accepted_values(
    noted: Mapping[str, object],
    definition: WorkflowDefinition,
    *,
    current: Mapping[str, object],
    open_steps: Collection[str],
    today: date,
) -> dict[str, str]:
    """Noted readings the Case's validators still accept now (a value it holds already: none)."""
    candidates = {k: v for k, v in noted.items() if isinstance(v, str)}
    return _accepted(candidates, definition, current=current, open_steps=open_steps, today=today)


def noted_view(
    noted: Mapping[str, str], definition: WorkflowDefinition
) -> tuple[tuple[str, str], ...]:
    """(question label, answer in words) per noted reading, in the definition's order."""
    shown: list[tuple[str, str]] = []
    for step in definition.steps:
        for question in step.questions:
            value = noted.get(question.key)
            if value is None:
                continue
            option = next((o for o in question.options if o.value == value), None)
            if option is not None:
                answer = option.label
            elif question.kind == "date" and value != NOT_SURE:
                answer = f"{date.fromisoformat(value):%-d %B %Y}"
            else:
                answer = "Not sure" if value == NOT_SURE else value
            shown.append((question.label, answer))
    return tuple(shown)


def _accepted(
    candidates: Mapping[str, str],
    definition: WorkflowDefinition,
    *,
    current: Mapping[str, object],
    open_steps: Collection[str],
    today: date,
) -> dict[str, str]:
    """The candidates the Case's own validators accept now (question key -> value)."""
    accepted: dict[str, str] = {}
    merged = dict(current)
    # In definition order, so an answer another question depends on is checked first.
    for step in definition.steps:
        if step.gate is not None and step.key not in open_steps:
            continue  # a semantic workflow gate is closed (never a form navigation order)
        for question in step.questions:
            answer = candidates.get(question.key)
            if answer is None or merged.get(question.key) == answer:
                continue
            _, errors = validate_answers(step, {question.key: answer}, today=today, current=merged)
            if errors:
                continue
            accepted[question.key] = answer
            merged[question.key] = answer
    return accepted
