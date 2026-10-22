"""From an Ask HeroOS turn to its Case: the creation threshold, a safe title and the facts.

Pure: it decides, it never writes (``app.conversations.service`` persists
through ``app.cases.mutation``, the same pipeline as a step's form).

**A Case** is created only when the turn's deterministic evaluation says the
matter is a supported HR matter of an established workflow from the approved
catalog that has a real ``WorkflowDefinition``; the founder hasn't blended
separate matters; the conversation has no Case yet and established no other
workflow. Anything else stays a conversation (an unclear request, another HR
matter, staffing strategy, a non-HR question).

**Its title** is never typed by anyone and never names a person: a neutral label
for the kind of matter, from a closed server-owned map of approved topic keys,
else the workflow and the date ("Disciplinary case · 22 Oct"). A topic about
an employer decision or sanction never becomes a title, and neither does the
AI's pathway candidate.

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
"""

from collections.abc import Collection, Mapping
from datetime import date
from typing import Final

from app.assistant.gateway.service import Handoff
from app.evaluation.model import ConversationEvaluation
from app.evaluation.snapshot import WorkflowExecution
from app.workflows.answers import validate_answers
from app.workflows.definition import WorkflowDefinition, current_definition

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
    """The definition a new Case would run, or None: this turn stays a conversation."""
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
        schema = execution.schemas.get(key)
        if schema is None or schema.question is None or not isinstance(value, str):
            continue
        question = definition.question(schema.question)
        if question is None or question.sensitive or question.options_from is not None:
            continue
        candidates[question.key] = value
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
