"""The shared Case mutation pipeline: the one way a change to a Case's facts is persisted.

Every fact change, whatever produced it, goes through ``apply_case_fact_changes``
in the caller's transaction, under the instance lock the caller took
(``workflows.get_workflow_case(..., for_update=True)``), on a ``CaseState``
read under that lock:

1. compare-and-set the instance revision (optimistic concurrency);
2. append one ``WorkflowSubmission`` with its origin (a step's form, or an Ask
   HeroOS turn naming its founder message) and its ``CaseFact`` rows. Facts are
   append-only: a correction is a new row, the latest wins, and an unchanged
   value is refused rather than stored again;
3. re-evaluate the intake on the new answers and append the
   ``WorkflowEvaluation`` it produced;
4. re-evaluate progression and record every transition the rules newly
   escalate.

It never selects a pathway, starts or completes a stage, records an employer
decision or touches a CaseSubject: those stay the employer's own requests
(the progression and decision routes). Input validation stays with each
caller: the step form's validator, or M2-NEW-06's canonical trust pipeline
followed by the same step validator (``app.conversations.bridge``). The side
effects are the same for both.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.companies.jurisdiction import JurisdictionAssessment, assess_jurisdiction
from app.core.config import SensitiveScreening
from app.db.models import WorkflowInstance, WorkflowSubmission
from app.db.models.workflow import (
    ASSISTANT_STEP_KEY,
    SUBMISSION_ASSISTANT,
    SUBMISSION_STRUCTURED,
)
from app.repositories import workflows
from app.repositories.company_blueprints import get_company_blueprint
from app.tenancy.scope import CompanyScope
from app.workflows.conversation import SubmissionRecord
from app.workflows.definition import WorkflowDefinition, definition_for
from app.workflows.history import evaluation_results
from app.workflows.intake import EarlierEscalation, IntakeEvaluation, evaluate_intake, ruleset_for
from app.workflows.progress import FactRecord, latest_answers
from app.workflows.progression.bundle import RuleBundle
from app.workflows.progression.engine import (
    ProgressionEvaluation,
    TransitionEvaluation,
    evaluate_progression,
)
from app.workflows.progression.records import StoredEvent
from app.workflows.progression.spec import PROGRESSIONS, ProgressionSpec


def workflow_definition(instance: WorkflowInstance) -> WorkflowDefinition:
    definition = definition_for(instance.workflow_key, instance.definition_version)
    if definition is None:
        # A stored version this code cannot serve: a deployment error, not input.
        raise RuntimeError("workflow definition version is not available")
    return definition


def company_jurisdiction(scope: CompanyScope) -> JurisdictionAssessment:
    return assess_jurisdiction(get_company_blueprint(scope))


@dataclass(frozen=True, slots=True)
class CaseState:
    """Everything one request reads about a Case, evaluated once."""

    definition: WorkflowDefinition
    submissions: list[SubmissionRecord]
    answers: dict[str, object]
    company: JurisdictionAssessment
    earlier: EarlierEscalation | None
    intake: IntakeEvaluation
    spec: ProgressionSpec | None
    events: list[StoredEvent]
    progression: ProgressionEvaluation | None


def evaluate_case(
    scope: CompanyScope,
    item: workflows.WorkflowCase,
    policy: SensitiveScreening,
    bundle: RuleBundle | None,
) -> CaseState:
    definition = workflow_definition(item.instance)
    submissions = workflows.submissions(scope, item.instance.id)
    answers = latest_answers(
        FactRecord(s.revision, key, value) for s in submissions for key, value in s.facts.items()
    )
    company = company_jurisdiction(scope)
    earlier = workflows.first_escalations(scope, [item.instance.id]).get(item.instance.id)
    intake = evaluate_intake(
        definition,
        answers,
        company,
        screening_enabled=policy == "synthetic_demo",
        earlier_escalation=earlier,
    )
    spec = PROGRESSIONS.get(definition.key)
    events = workflows.progress_events(scope, item.instance.id) if spec is not None else []
    progression = (
        None
        if spec is None
        else evaluate_progression(spec, bundle, intake, answers, [e.engine() for e in events])
    )
    return CaseState(
        definition, submissions, answers, company, earlier, intake, spec, events, progression
    )


def transition_reasons(transition: TransitionEvaluation) -> list[dict[str, object]]:
    """The stored trace of a decision: every result, as codes (never an answer)."""
    return [
        {
            "rule": r.rule,
            "source": r.source,
            "action": r.action,
            "fired": r.fired,
            "reason": r.reason,
            "provisional": r.provisional,
            "unknown": list(r.unknown),
        }
        for r in transition.results
    ]


def record_escalations(
    scope: CompanyScope,
    item: workflows.WorkflowCase,
    progression: ProgressionEvaluation,
    *,
    bundle: RuleBundle,
    definition: WorkflowDefinition,
    intake: IntakeEvaluation,
    revision: int,
    submission_id: UUID | None,
    user_id: UUID,
) -> int:
    """Record every transition the rules newly escalate (sticky from now on)."""
    if not progression.open:
        return 0
    recorded = 0
    for transition in progression.transitions:
        if not transition.new_escalation or transition.key in progression.state.escalated:
            continue
        workflows.record_progress_event(
            scope,
            item.instance.id,
            kind="escalation_recorded",
            transition=transition.key,
            pathway=transition.pathway,
            previous_pathway=None,
            stage=transition.stage,
            decision="escalate",
            reasons=transition_reasons(transition),
            acknowledged=[],
            revision=revision,
            request_key=None,
            submission_id=submission_id,
            user_id=user_id,
            bundle=bundle,
            definition_version=definition.version,
            intake_status=intake.status,
        )
        recorded += 1
    return recorded


@dataclass(frozen=True, slots=True)
class FormOrigin:
    """Answers the employer saved through a step's form."""

    step_key: str


@dataclass(frozen=True, slots=True)
class AssistantOrigin:
    """Canonical facts an Ask HeroOS turn established; the founder message they came from."""

    message_id: UUID


@dataclass(frozen=True, slots=True)
class AppliedChanges:
    submission: WorkflowSubmission
    # The instance revision the change produced.
    revision: int
    # The intake evaluation on the new answers (appended as the submission's trace).
    intake: IntakeEvaluation
    # Transitions newly escalated by the change.
    escalated: int


def apply_case_fact_changes(
    scope: CompanyScope,
    item: workflows.WorkflowCase,
    state: CaseState,
    *,
    origin: FormOrigin | AssistantOrigin,
    changes: Mapping[str, object],
    expected_revision: int,
    idempotency_key: UUID,
    user_id: UUID,
    policy: SensitiveScreening,
    bundle: RuleBundle | None,
) -> AppliedChanges | None:
    """Persist validated fact changes and their side effects; None if the revision is stale.

    ``changes``: fact key -> value (``None`` clears), each different from the
    Case's current answer (``state.answers``); validated by the caller. Flushes,
    never commits: on None the caller rolls back.
    """
    if not changes:
        raise ValueError("no fact changes to apply")
    unchanged = sorted(k for k, v in changes.items() if state.answers.get(k) == v)
    if unchanged:
        # A repeated value is never stored again (the latest fact already says it).
        raise ValueError("fact changes repeat current values")
    revision = workflows.advance_revision(scope, item.instance.id, expected_revision)
    if revision is None:
        return None
    if isinstance(origin, AssistantOrigin):
        step_key, kind, source = ASSISTANT_STEP_KEY, SUBMISSION_ASSISTANT, origin.message_id
    else:
        step_key, kind, source = origin.step_key, SUBMISSION_STRUCTURED, None
    submission = workflows.record_submission(
        scope,
        item.instance,
        step_key=step_key,
        revision=revision,
        idempotency_key=idempotency_key,
        user_id=user_id,
        changes=changes,
        origin=kind,
        source_message_id=source,
    )
    after = {k: v for k, v in {**state.answers, **changes}.items() if v is not None}
    intake = evaluate_intake(
        state.definition,
        after,
        state.company,
        screening_enabled=policy == "synthetic_demo",
        earlier_escalation=state.earlier,
    )
    workflows.record_evaluation(
        scope, submission, intake, evaluation_results(intake, ruleset_for(state.definition))
    )
    escalated = 0
    if bundle is not None and state.spec is not None:
        # Changed answers can make a rule escalate a transition: record it now.
        progression = evaluate_progression(
            state.spec, bundle, intake, after, [e.engine() for e in state.events]
        )
        escalated = record_escalations(
            scope,
            item,
            progression,
            bundle=bundle,
            definition=state.definition,
            intake=intake,
            revision=revision,
            submission_id=submission.id,
            user_id=user_id,
        )
    return AppliedChanges(submission, revision, intake, escalated)


def latest_fact_revisions(submissions: Sequence[SubmissionRecord]) -> dict[str, int]:
    """Per fact key, the instance revision of the submission that last wrote it."""
    revisions: dict[str, int] = {}
    for submission in sorted(submissions, key=lambda s: s.revision):
        for key in submission.facts:
            revisions[key] = submission.revision
    return revisions
