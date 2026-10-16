"""Guided workflow Cases (M2-01, M2-02): create, list, read and answer.

Same dependency chain as every Company route (bearer token -> HeroOS User ->
Membership -> transaction-local tenant context -> scoped repositories -> RLS).

Access policy (M2-01 interim least privilege, until JJ approves dedicated HR
access roles): **every** route here, reads included, is for Company
administrators only (``CompanyAdminDb``: the role is checked at authorization
and again inside the request's transaction). Ordinary members cannot list,
open, create or answer Disciplinary Cases; the generic Case record routes hide
them too (``app.workflows.access``).

Intake (M2-02): every read recomputes the intake evaluation from the saved
answers and the Company's live jurisdiction readiness (``app.workflows.intake``):
the Case jurisdiction, condition results, safety screening, hold, cautions and
status. Every save that writes a submission also appends the evaluation it
produced (``workflow_evaluations``) in the same transaction, under the same
instance lock. A hold never blocks saving answers (they stay correctable); it
closes the gate later stages must check (``IntakeEvaluation.next_stage_open``).
A specialist-review hold is never released by changed answers: once a save
recorded one, the Case stays held (no release exists in the product yet).

The safety screening (health-related questions) is offered only when the
deployment enables it for synthetic demo data (``HEROOS_SENSITIVE_SCREENING``);
otherwise its step can't be answered and no intake can be completed.

Responses:

- 401 / 403 exactly as the Company routes (403 also for any member).
- 404 ``Not found``: unknown workflow or step, or a Case that is not a workflow
  Case of the authorized Company (identical for another Company's Case).
- 409 ``Conflict``: a reused creation ``request_key`` with different details,
  a stale ``expected_revision`` (the answers changed since they were read), or
  a step that can't be answered in the Case's current state (its jurisdiction
  isn't confirmed, or no approved screening covers it).
- 422: invalid input; field locations only, submitted values are never echoed.

Idempotency: Case creation replays on the same ``request_key`` (200 with the
same Case); answer saves replay on the same ``submission_key`` (200, nothing
written twice). Nothing here classifies, assesses or decides anything about the
incident or the employee.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
)
from sqlalchemy.exc import IntegrityError

from app.api.companies import JurisdictionOut, jurisdiction_out, refuse_untidy_text
from app.auth.dependencies import CompanyContext
from app.companies.jurisdiction import JurisdictionAssessment, assess_jurisdiction
from app.core.config import SensitiveScreening
from app.db.models import WorkflowInstance
from app.db.models.membership import ROLE_COMPANY_ADMIN
from app.repositories import workflows
from app.repositories.company_blueprints import get_company_blueprint
from app.tenancy.dependencies import CompanyAdminDb
from app.tenancy.scope import CompanyScope
from app.workflows import conversation
from app.workflows.answers import validate_answers
from app.workflows.conditions import RuleSet
from app.workflows.definition import (
    StepGate,
    WorkflowDefinition,
    current_definition,
    definition_for,
)
from app.workflows.history import HistoryItem, compose_history, evaluation_results
from app.workflows.intake import (
    JURISDICTION_LABELS,
    EarlierEscalation,
    IntakeEvaluation,
    evaluate_intake,
    question_options,
    ruleset_for,
)
from app.workflows.progress import FactRecord, latest_answers, progress

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies/{company_id}", tags=["workflows"])

CaseTitle = Annotated[
    StrictStr, StringConstraints(min_length=1, max_length=200), AfterValidator(refuse_untidy_text)
]
# More than any step asks; a bound on the request, not a product rule.
MAX_ANSWERS_PER_SUBMISSION = 50


def screening_policy(request: Request) -> SensitiveScreening:
    """The deployment's setting for the sensitive safety screening."""
    policy: SensitiveScreening = request.app.state.sensitive_screening
    return policy


ScreeningPolicy = Annotated[SensitiveScreening, Depends(screening_policy)]


class CaseCreate(BaseModel):
    """A new workflow Case. ``case_type`` is set by the server from the workflow."""

    model_config = ConfigDict(extra="forbid")

    title: CaseTitle
    # Client-generated per creation attempt; a retry sends the same key.
    request_key: UUID


class AnswersIn(BaseModel):
    """Answers for one step: fact key -> value (``null`` clears an answer)."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: Annotated[StrictInt, Field(ge=0)]
    # Client-generated per save attempt; a retry sends the same key.
    submission_key: UUID
    answers: Annotated[
        dict[StrictStr, StrictStr | None], Field(max_length=MAX_ANSWERS_PER_SUBMISSION)
    ]


class StatusOut(BaseModel):
    code: str
    label: str


class CaseSummaryOut(BaseModel):
    id: UUID
    title: str
    case_type: str
    workflow_key: str
    status: StatusOut
    # Questions answered and asked in the Case's current state.
    answered: int
    total: int
    created_at: datetime
    # Last activity: creation or the latest saved answers.
    updated_at: datetime


class CaseRecordOut(BaseModel):
    id: UUID
    title: str
    case_type: str
    created_at: datetime
    updated_at: datetime


class WorkflowOut(BaseModel):
    key: str
    title: str
    definition_version: int
    # Send it back as ``expected_revision`` when saving answers.
    revision: int


class OptionOut(BaseModel):
    value: str
    label: str


class AskWhenOut(BaseModel):
    key: str
    values: list[str]


class QuestionOut(BaseModel):
    key: str
    kind: Literal["text", "date", "choice"]
    prompt: str
    label: str
    help: str | None
    options: list[OptionOut]
    max_length: int | None
    allow_not_sure: bool
    # Asked only while another answer is one of ``values``.
    ask_when: AskWhenOut | None


class StepOut(BaseModel):
    key: str
    title: str
    intro: str
    questions: list[QuestionOut]
    # The step can be answered in the Case's current state.
    available: bool
    unavailable_reason: str | None
    # The step's checks are development content still under legal review.
    provisional: bool
    # The step asks sensitive (health-related) questions.
    sensitive: bool


class ProgressOut(BaseModel):
    key: str
    label: str
    status: Literal["completed", "in_progress", "needs_information", "blocked", "coming_later"]
    detail: str


class InformationOut(BaseModel):
    kind: Literal["information"]
    id: str
    title: str
    body: str


class QuestionGroupOut(BaseModel):
    kind: Literal["question_group"]
    id: str
    step_key: str
    title: str
    body: str
    questions: list[str]


class AnsweredItemOut(BaseModel):
    key: str
    label: str
    display: str | None


class AnswerConfirmationOut(BaseModel):
    kind: Literal["answer_confirmation"]
    id: str
    step_key: str
    submitted_at: datetime
    by_viewer: bool
    items: list[AnsweredItemOut]


class MissingInformationOut(BaseModel):
    kind: Literal["missing_information"]
    id: str
    step_key: str
    title: str
    body: str
    items: list[str]


class StatusNoticeOut(BaseModel):
    kind: Literal["status_notice"]
    id: str
    tone: Literal["info", "caution", "success"]
    title: str
    body: str


class CautionOut(BaseModel):
    kind: Literal["caution"]
    id: str
    title: str
    body: str
    provisional: bool


class HoldOut(BaseModel):
    kind: Literal["hold"]
    id: str
    action: Literal["block", "escalate"]
    reason: Literal[
        "high_risk_factors",
        "jurisdiction_different",
        "jurisdiction_unsupported",
        "screening_not_covered",
        "earlier_escalation",
        "company_jurisdiction_unconfirmed",
        "case_jurisdiction_not_sure",
        "case_jurisdiction_outdated",
    ]
    title: str
    body: str
    items: list[str]
    provisional: bool


MessageOut = Annotated[
    InformationOut
    | QuestionGroupOut
    | AnswerConfirmationOut
    | MissingInformationOut
    | StatusNoticeOut
    | CautionOut
    | HoldOut,
    Field(discriminator="kind"),
]


class CaseJurisdictionOut(BaseModel):
    """The Case's employment jurisdiction (the routing rule's result)."""

    status: Literal[
        "resolved",
        "company_unconfirmed",
        "company_unsupported",
        "awaiting_case_confirmation",
        "case_not_sure",
        "case_different",
        "case_confirmation_outdated",
    ]
    # Set only when resolved.
    jurisdiction: Literal["uae_federal", "difc"] | None
    label: str | None
    # Basis: the Company's operator-confirmed jurisdiction and the employer's
    # confirmation for this Case.
    company_jurisdiction: Literal["uae_federal", "difc"] | None


class EscalationOut(BaseModel):
    """The Case's first specialist-review hold, kept whatever the answers say now."""

    since: datetime
    # Why it was first held (a hold reason code).
    reason: str
    # The current answers or jurisdiction themselves still call for it.
    current: bool


class IntakeOut(BaseModel):
    case_jurisdiction: CaseJurisdictionOut
    # The current answers' screening state (an earlier escalation is separate).
    screening: Literal[
        "not_applicable",
        "disabled",
        "not_started",
        "incomplete",
        "not_cleared",
        "cleared",
        "positive",
    ]
    hold: HoldOut | None
    escalation: EscalationOut | None
    cautions: list[CautionOut]
    # Later stages may start (server-side gate); never true while held.
    next_stage_open: bool


class HistoryItemOut(BaseModel):
    id: str
    kind: Literal[
        "case_created",
        "answers_saved",
        "jurisdiction",
        "hold_placed",
        "hold_kept",
        "hold_lifted",
        "screening",
        "caution",
        "intake_recorded",
    ]
    at: datetime
    by_viewer: bool | None
    title: str
    detail: str | None


class WorkflowViewOut(BaseModel):
    case: CaseRecordOut
    workflow: WorkflowOut
    # The caller may create Cases and save answers (server-side role).
    can_edit: bool
    steps: list[StepOut]
    # Every saved answer (fact key -> value); unanswered keys are absent. An
    # answer to a question that isn't asked now is kept but not in ``asked``.
    answers: dict[str, str]
    # How each saved answer reads back (option labels, readable dates).
    answer_labels: dict[str, str]
    # Questions asked in the current state (available step, relevant), in order.
    asked: list[str]
    missing: list[str]
    # Asked questions answered "Not sure".
    uncertain: list[str]
    progress: list[ProgressOut]
    status: StatusOut
    # The Company's jurisdiction readiness (M1-10C contract).
    jurisdiction: JurisdictionOut
    intake: IntakeOut
    # The deployment's screening setting: "synthetic_demo" means demo data only.
    sensitive_screening: Literal["disabled", "synthetic_demo"]
    # Stages of this workflow that are not available yet.
    not_available: list[str]
    conversation: list[MessageOut]
    history: list[HistoryItemOut]


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _conflict() -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflict")


def _workflow(workflow_key: str) -> WorkflowDefinition:
    definition = current_definition(workflow_key)
    if definition is None:
        raise _not_found()
    return definition


def _definition(instance: WorkflowInstance) -> WorkflowDefinition:
    definition = definition_for(instance.workflow_key, instance.definition_version)
    if definition is None:
        # A stored version this code cannot serve: a deployment error, not input.
        raise RuntimeError("workflow definition version is not available")
    return definition


def _jurisdiction(scope: CompanyScope) -> JurisdictionAssessment:
    return assess_jurisdiction(get_company_blueprint(scope))


def _summary(
    item: workflows.WorkflowCase,
    facts: list[FactRecord],
    company: JurisdictionAssessment,
    policy: SensitiveScreening,
    earlier: EarlierEscalation | None,
) -> CaseSummaryOut:
    definition = _definition(item.instance)
    evaluation = evaluate_intake(
        definition,
        latest_answers(facts),
        company,
        screening_enabled=policy == "synthetic_demo",
        earlier_escalation=earlier,
    )
    return CaseSummaryOut(
        id=item.case.id,
        title=item.case.title,
        case_type=item.case.case_type,
        workflow_key=item.instance.workflow_key,
        status=StatusOut(code=evaluation.status, label=evaluation.status_label),
        answered=evaluation.answered,
        total=evaluation.total,
        created_at=item.case.created_at,
        updated_at=item.instance.updated_at,
    )


_UNAVAILABLE: dict[StepGate, str] = {
    StepGate.COMPANY_JURISDICTION_CONFIRMED: (
        "Available once your company's employment jurisdiction is confirmed."
    ),
    StepGate.SCREENING_COVERED: "Available once the case's jurisdiction is confirmed.",
}


def _unavailable_reason(step_gate: StepGate | None, evaluation: IntakeEvaluation) -> str | None:
    if step_gate is None:
        return None
    if step_gate is StepGate.SCREENING_COVERED and evaluation.screening == "disabled":
        return "The safety screening isn't enabled in this environment."
    if step_gate is StepGate.SCREENING_COVERED and evaluation.jurisdiction.resolved:
        return "Not available for this jurisdiction yet."
    return _UNAVAILABLE[step_gate]


def _provisional_steps(ruleset: RuleSet) -> set[str]:
    """Steps whose escalating rule is still under legal review."""
    return {
        r.step
        for r in ruleset.rules
        if r.step is not None and r.action == "escalate" and r.provisional
    }


def _hold_out(hold: conversation.HoldNotice) -> HoldOut:
    return HoldOut(
        kind=hold.kind,
        id=hold.id,
        action=hold.action,
        reason=hold.reason,  # type: ignore[arg-type]
        title=hold.title,
        body=hold.body,
        items=list(hold.items),
        provisional=hold.provisional,
    )


def _caution_out(caution: conversation.CautionNotice) -> CautionOut:
    return CautionOut(
        kind=caution.kind,
        id=caution.id,
        title=caution.title,
        body=caution.body,
        provisional=caution.provisional,
    )


def _view(
    scope: CompanyScope,
    item: workflows.WorkflowCase,
    context: CompanyContext,
    policy: SensitiveScreening,
) -> WorkflowViewOut:
    definition = _definition(item.instance)
    ruleset = ruleset_for(definition)
    submissions = workflows.submissions(scope, item.instance.id)
    answers = latest_answers(
        FactRecord(s.revision, key, value) for s in submissions for key, value in s.facts.items()
    )
    known = {q.key for s in definition.steps for q in s.questions}
    company = _jurisdiction(scope)
    earlier = workflows.first_escalations(scope, [item.instance.id]).get(item.instance.id)
    evaluation = evaluate_intake(
        definition,
        answers,
        company,
        screening_enabled=policy == "synthetic_demo",
        earlier_escalation=earlier,
    )
    messages = conversation.compose(
        definition, submissions, evaluation, company, viewer_user_id=context.user_id
    )
    history = compose_history(
        definition,
        created_at=item.case.created_at,
        created_by_user_id=item.instance.created_by_user_id,
        submissions=submissions,
        evaluations=workflows.evaluations(scope, item.instance.id),
        viewer_user_id=context.user_id,
    )
    hold = (
        None
        if evaluation.hold is None
        else conversation.hold_notice(evaluation.hold, evaluation, company, definition)
    )
    provisional = _provisional_steps(ruleset)
    case_jurisdiction = evaluation.jurisdiction
    return WorkflowViewOut(
        case=CaseRecordOut(
            id=item.case.id,
            title=item.case.title,
            case_type=item.case.case_type,
            created_at=item.case.created_at,
            updated_at=item.instance.updated_at,
        ),
        workflow=WorkflowOut(
            key=definition.key,
            title=definition.title,
            definition_version=definition.version,
            revision=item.instance.revision,
        ),
        can_edit=context.role == ROLE_COMPANY_ADMIN,
        steps=[
            StepOut(
                key=step.key,
                title=step.title,
                intro=step.intro,
                questions=[
                    QuestionOut(
                        key=q.key,
                        kind=q.kind,
                        prompt=q.prompt,
                        label=q.label,
                        help=q.help,
                        options=[
                            OptionOut(value=o.value, label=o.label)
                            for o in question_options(q, company)
                        ],
                        max_length=q.max_length,
                        allow_not_sure=q.allow_not_sure,
                        ask_when=None
                        if q.ask_when is None
                        else AskWhenOut(key=q.ask_when.key, values=list(q.ask_when.values)),
                    )
                    for q in step.questions
                ],
                available=step.key in evaluation.available_steps,
                unavailable_reason=None
                if step.key in evaluation.available_steps
                else _unavailable_reason(step.gate, evaluation),
                provisional=step.key in provisional,
                sensitive=any(q.sensitive for q in step.questions),
            )
            for step in definition.steps
        ],
        answers={key: str(value) for key, value in answers.items() if key in known},
        answer_labels={
            key: conversation.display_answer(question, answers[key]) or ""
            for key in answers
            if (question := definition.question(key)) is not None
        },
        asked=list(evaluation.asked),
        missing=list(evaluation.missing),
        uncertain=list(evaluation.uncertain),
        progress=[
            ProgressOut(key=p.key, label=p.label, status=p.status, detail=p.detail)
            for p in progress(definition, evaluation)
        ],
        status=StatusOut(code=evaluation.status, label=evaluation.status_label),
        jurisdiction=jurisdiction_out(company),
        intake=IntakeOut(
            case_jurisdiction=CaseJurisdictionOut(
                status=case_jurisdiction.status,
                jurisdiction=case_jurisdiction.jurisdiction,  # type: ignore[arg-type]
                label=None
                if case_jurisdiction.jurisdiction is None
                else JURISDICTION_LABELS[case_jurisdiction.jurisdiction],
                company_jurisdiction=case_jurisdiction.company_jurisdiction,  # type: ignore[arg-type]
            ),
            screening=evaluation.screening,
            hold=None if hold is None else _hold_out(hold),
            escalation=None
            if earlier is None
            else EscalationOut(
                since=earlier.since,
                reason=earlier.reason,
                current=evaluation.currently_escalated,
            ),
            cautions=[
                _caution_out(conversation.caution_notice(caution))
                for caution in evaluation.cautions
            ],
            next_stage_open=evaluation.next_stage_open,
        ),
        sensitive_screening=policy,
        not_available=list(definition.not_available),
        conversation=[_message_out(message) for message in messages],
        history=[_history_out(entry) for entry in history],
    )


def _history_out(entry: HistoryItem) -> HistoryItemOut:
    return HistoryItemOut(
        id=entry.id,
        kind=entry.kind,
        at=entry.at,
        by_viewer=entry.by_viewer,
        title=entry.title,
        detail=entry.detail,
    )


def _message_out(message: conversation.Message) -> MessageOut:
    if isinstance(message, conversation.Information):
        return InformationOut(
            kind=message.kind, id=message.id, title=message.title, body=message.body
        )
    if isinstance(message, conversation.QuestionGroup):
        return QuestionGroupOut(
            kind=message.kind,
            id=message.id,
            step_key=message.step_key,
            title=message.title,
            body=message.body,
            questions=list(message.questions),
        )
    if isinstance(message, conversation.AnswerConfirmation):
        return AnswerConfirmationOut(
            kind=message.kind,
            id=message.id,
            step_key=message.step_key,
            submitted_at=message.submitted_at,
            by_viewer=message.by_viewer,
            items=[
                AnsweredItemOut(key=i.key, label=i.label, display=i.display) for i in message.items
            ],
        )
    if isinstance(message, conversation.MissingInformation):
        return MissingInformationOut(
            kind=message.kind,
            id=message.id,
            step_key=message.step_key,
            title=message.title,
            body=message.body,
            items=list(message.items),
        )
    if isinstance(message, conversation.CautionNotice):
        return _caution_out(message)
    if isinstance(message, conversation.HoldNotice):
        return _hold_out(message)
    return StatusNoticeOut(
        kind=message.kind, id=message.id, tone=message.tone, title=message.title, body=message.body
    )


@router.get("/workflows/{workflow_key}/cases", response_model=list[CaseSummaryOut])
def list_workflow_cases(
    workflow_key: str, scope: CompanyAdminDb, policy: ScreeningPolicy
) -> list[CaseSummaryOut]:
    definition = _workflow(workflow_key)
    items = workflows.list_workflow_cases(scope, definition.key)
    ids = [item.instance.id for item in items]
    facts = workflows.facts_by_instance(scope, ids)
    escalations = workflows.first_escalations(scope, ids)
    company = _jurisdiction(scope)
    return [
        _summary(item, facts[item.instance.id], company, policy, escalations.get(item.instance.id))
        for item in items
    ]


def _replayed_case(
    item: workflows.WorkflowCase,
    body: CaseCreate,
    definition: WorkflowDefinition,
    context: CompanyContext,
) -> bool:
    """The same creation request again (a retry), rather than a reused key."""
    return (
        item.instance.workflow_key == definition.key
        and item.instance.created_by_user_id == context.user_id
        and item.case.title == body.title
    )


@router.post(
    "/workflows/{workflow_key}/cases",
    response_model=CaseSummaryOut,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_case(
    workflow_key: str,
    body: CaseCreate,
    scope: CompanyAdminDb,
    context: CompanyContext,
    response: Response,
    policy: ScreeningPolicy,
) -> CaseSummaryOut:
    definition = _workflow(workflow_key)
    existing = workflows.find_by_request_key(scope, body.request_key)
    if existing is None:
        try:
            created = workflows.create_workflow_case(
                scope,
                definition,
                title=body.title,
                request_key=body.request_key,
                user_id=context.user_id,
            )
            scope.commit()
        except IntegrityError:
            # A concurrent request with the same key won the race.
            scope.rollback()
            existing = workflows.find_by_request_key(scope, body.request_key)
            if existing is None:
                raise
        else:
            logger.info(
                "Workflow case created (company_id=%s, workflow=%s)",
                scope.company_id,
                definition.key,
            )
            return _summary(created, [], _jurisdiction(scope), policy, None)
    if not _replayed_case(existing, body, definition, context):
        raise _conflict()
    response.status_code = status.HTTP_200_OK
    instance_id = existing.instance.id
    facts = workflows.facts_by_instance(scope, [instance_id])
    earlier = workflows.first_escalations(scope, [instance_id]).get(instance_id)
    return _summary(existing, facts[instance_id], _jurisdiction(scope), policy, earlier)


@router.get("/cases/{case_id}/workflow", response_model=WorkflowViewOut)
def get_case_workflow(
    case_id: UUID, scope: CompanyAdminDb, context: CompanyContext, policy: ScreeningPolicy
) -> WorkflowViewOut:
    item = workflows.get_workflow_case(scope, case_id)
    if item is None:
        raise _not_found()
    return _view(scope, item, context, policy)


def _reload(scope: CompanyScope, case_id: UUID) -> workflows.WorkflowCase:
    scope.session.expire_all()
    item = workflows.get_workflow_case(scope, case_id)
    if item is None:  # pragma: no cover - the Case cannot be deleted (no route, no grant)
        raise _not_found()
    return item


@router.put("/cases/{case_id}/workflow/steps/{step_key}/answers", response_model=WorkflowViewOut)
def save_step_answers(
    case_id: UUID,
    step_key: str,
    body: AnswersIn,
    scope: CompanyAdminDb,
    context: CompanyContext,
    policy: ScreeningPolicy,
) -> WorkflowViewOut:
    # Lock the instance first: concurrent saves of this Case run one after the
    # other, so the replay check, the revision check, the facts and the
    # evaluation all read the same committed state (a replay never answers
    # with an older revision).
    item = workflows.get_workflow_case(scope, case_id, for_update=True)
    if item is None:
        raise _not_found()
    definition = _definition(item.instance)
    step = definition.step(step_key)
    if step is None:
        raise _not_found()

    instance_id = item.instance.id
    if workflows.find_submission(scope, instance_id, body.submission_key) is not None:
        # A retry of a save that already succeeded: answered before any check
        # that depends on the current state, which that save may have changed.
        return _view(scope, item, context, policy)

    current = latest_answers(workflows.facts_by_instance(scope, [instance_id])[instance_id])
    company = _jurisdiction(scope)
    enabled = policy == "synthetic_demo"
    earlier = workflows.first_escalations(scope, [instance_id]).get(instance_id)
    before = evaluate_intake(
        definition, current, company, screening_enabled=enabled, earlier_escalation=earlier
    )
    if step.key not in before.available_steps:
        raise _conflict()
    accepted, errors = validate_answers(
        step,
        body.answers,
        today=datetime.now(UTC).date(),
        current=current,
        options={q.key: question_options(q, company) for q in step.questions if q.options_from},
    )
    if errors:
        raise RequestValidationError(
            [
                {"type": "value_error", "loc": ("body", "answers", e.key), "msg": e.message}
                for e in errors
            ]
        )
    if body.expected_revision != item.instance.revision:
        raise _conflict()

    changes = {key: value for key, value in accepted.items() if current.get(key) != value}
    if not changes:
        return _view(scope, item, context, policy)

    revision = workflows.advance_revision(scope, instance_id, body.expected_revision)
    if revision is None:
        # Another save committed first. Same key: that save was this one.
        scope.rollback()
        if workflows.find_submission(scope, instance_id, body.submission_key) is not None:
            return _view(scope, _reload(scope, case_id), context, policy)
        raise _conflict()
    submission = workflows.record_submission(
        scope,
        item.instance,
        step_key=step.key,
        revision=revision,
        idempotency_key=body.submission_key,
        user_id=context.user_id,
        changes=changes,
    )
    after = {**current, **changes}
    evaluation = evaluate_intake(
        definition,
        {k: v for k, v in after.items() if v is not None},
        company,
        screening_enabled=enabled,
        earlier_escalation=earlier,
    )
    workflows.record_evaluation(
        scope, submission, evaluation, evaluation_results(evaluation, ruleset_for(definition))
    )
    scope.commit()
    if evaluation.hold is not None and evaluation.hold != before.hold:
        # The kind only: never the reason or an answer (HR case content).
        logger.info(
            "Workflow case held (company_id=%s, hold=%s)", scope.company_id, evaluation.hold.kind
        )
    return _view(scope, _reload(scope, case_id), context, policy)
