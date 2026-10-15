"""Guided workflow Cases (M2-01): create, list, read and answer.

Same dependency chain as every Company route (bearer token -> HeroOS User ->
Membership -> transaction-local tenant context -> scoped repositories -> RLS).

Access policy (M2-01 interim least privilege, until JJ approves dedicated HR
access roles): **every** route here, reads included, is for Company
administrators only (``CompanyAdminDb``: the role is checked at authorization
and again inside the request's transaction). Ordinary members cannot list,
open, create or answer Disciplinary Cases; the generic Case record routes hide
them too (``app.workflows.access``).

Responses:

- 401 / 403 exactly as the Company routes (403 also for any member).
- 404 ``Not found``: unknown workflow or step, or a Case that is not a workflow
  Case of the authorized Company (identical for another Company's Case).
- 409 ``Conflict``: a reused creation ``request_key`` with different details,
  or a stale ``expected_revision`` (the answers changed since they were read).
- 422: invalid input; field locations only, submitted values are never echoed.

Idempotency: Case creation replays on the same ``request_key`` (200 with the
same Case); answer saves replay on the same ``submission_key`` (200, nothing
written twice). Nothing here classifies, assesses or decides anything: answers
are stored as given and progress is derived from them.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
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
from app.db.models import WorkflowInstance
from app.db.models.membership import ROLE_COMPANY_ADMIN
from app.repositories import workflows
from app.repositories.company_blueprints import get_company_blueprint
from app.tenancy.dependencies import CompanyAdminDb
from app.tenancy.scope import CompanyScope
from app.workflows import conversation
from app.workflows.answers import validate_answers
from app.workflows.definition import (
    WorkflowDefinition,
    current_definition,
    definition_for,
)
from app.workflows.progress import (
    FactRecord,
    answered_count,
    case_status,
    latest_answers,
    missing_questions,
    progress,
    questions,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies/{company_id}", tags=["workflows"])

CaseTitle = Annotated[
    StrictStr, StringConstraints(min_length=1, max_length=200), AfterValidator(refuse_untidy_text)
]
# More than any step asks; a bound on the request, not a product rule.
MAX_ANSWERS_PER_SUBMISSION = 50


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


class QuestionOut(BaseModel):
    key: str
    kind: Literal["text", "date", "choice"]
    prompt: str
    label: str
    help: str | None
    options: list[OptionOut]
    max_length: int | None
    allow_not_sure: bool


class StepOut(BaseModel):
    key: str
    title: str
    intro: str
    questions: list[QuestionOut]


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


MessageOut = Annotated[
    InformationOut
    | QuestionGroupOut
    | AnswerConfirmationOut
    | MissingInformationOut
    | StatusNoticeOut,
    Field(discriminator="kind"),
]


class WorkflowViewOut(BaseModel):
    case: CaseRecordOut
    workflow: WorkflowOut
    # The caller may create Cases and save answers (server-side role).
    can_edit: bool
    steps: list[StepOut]
    # Current answers only (fact key -> value); unanswered keys are absent.
    answers: dict[str, str]
    missing: list[str]
    progress: list[ProgressOut]
    status: StatusOut
    jurisdiction: JurisdictionOut
    # Stages of this workflow that are not available yet.
    not_available: list[str]
    conversation: list[MessageOut]


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
    jurisdiction: JurisdictionAssessment,
) -> CaseSummaryOut:
    definition = _definition(item.instance)
    answers = latest_answers(facts)
    found = case_status(definition, answers, jurisdiction)
    return CaseSummaryOut(
        id=item.case.id,
        title=item.case.title,
        case_type=item.case.case_type,
        workflow_key=item.instance.workflow_key,
        status=StatusOut(code=found.code, label=found.label),
        answered=answered_count(definition, answers),
        total=len(questions(definition)),
        created_at=item.case.created_at,
        updated_at=item.instance.updated_at,
    )


def _view(
    scope: CompanyScope, item: workflows.WorkflowCase, context: CompanyContext
) -> WorkflowViewOut:
    definition = _definition(item.instance)
    submissions = workflows.submissions(scope, item.instance.id)
    answers = latest_answers(
        FactRecord(s.revision, key, value) for s in submissions for key, value in s.facts.items()
    )
    known = {question.key for question in questions(definition)}
    jurisdiction = _jurisdiction(scope)
    found = case_status(definition, answers, jurisdiction)
    messages = conversation.compose(
        definition, submissions, jurisdiction, viewer_user_id=context.user_id
    )
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
                        options=[OptionOut(value=o.value, label=o.label) for o in q.options],
                        max_length=q.max_length,
                        allow_not_sure=q.allow_not_sure,
                    )
                    for q in step.questions
                ],
            )
            for step in definition.steps
        ],
        answers={key: str(value) for key, value in answers.items() if key in known},
        missing=[q.key for step in definition.steps for q in missing_questions(step, answers)],
        progress=[
            ProgressOut(key=p.key, label=p.label, status=p.status, detail=p.detail)
            for p in progress(definition, answers, jurisdiction)
        ],
        status=StatusOut(code=found.code, label=found.label),
        jurisdiction=jurisdiction_out(jurisdiction),
        not_available=list(definition.not_available),
        conversation=[_message_out(message) for message in messages],
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
    return StatusNoticeOut(
        kind=message.kind, id=message.id, tone=message.tone, title=message.title, body=message.body
    )


@router.get("/workflows/{workflow_key}/cases", response_model=list[CaseSummaryOut])
def list_workflow_cases(workflow_key: str, scope: CompanyAdminDb) -> list[CaseSummaryOut]:
    definition = _workflow(workflow_key)
    items = workflows.list_workflow_cases(scope, definition.key)
    facts = workflows.facts_by_instance(scope, [item.instance.id for item in items])
    jurisdiction = _jurisdiction(scope)
    return [_summary(item, facts[item.instance.id], jurisdiction) for item in items]


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
            return _summary(created, [], _jurisdiction(scope))
    if not _replayed_case(existing, body, definition, context):
        raise _conflict()
    response.status_code = status.HTTP_200_OK
    facts = workflows.facts_by_instance(scope, [existing.instance.id])
    return _summary(existing, facts[existing.instance.id], _jurisdiction(scope))


@router.get("/cases/{case_id}/workflow", response_model=WorkflowViewOut)
def get_case_workflow(
    case_id: UUID, scope: CompanyAdminDb, context: CompanyContext
) -> WorkflowViewOut:
    item = workflows.get_workflow_case(scope, case_id)
    if item is None:
        raise _not_found()
    return _view(scope, item, context)


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
) -> WorkflowViewOut:
    # Lock the instance first: concurrent saves of this Case run one after the
    # other, so the replay check, the revision check and the facts all read the
    # same committed state (a replay never answers with an older revision).
    item = workflows.get_workflow_case(scope, case_id, for_update=True)
    if item is None:
        raise _not_found()
    definition = _definition(item.instance)
    step = definition.step(step_key)
    if step is None:
        raise _not_found()
    accepted, errors = validate_answers(step, body.answers, today=datetime.now(UTC).date())
    if errors:
        raise RequestValidationError(
            [
                {"type": "value_error", "loc": ("body", "answers", e.key), "msg": e.message}
                for e in errors
            ]
        )

    instance_id = item.instance.id
    if workflows.find_submission(scope, instance_id, body.submission_key) is not None:
        return _view(scope, item, context)  # a retry of a save that already succeeded
    if body.expected_revision != item.instance.revision:
        raise _conflict()

    current = latest_answers(workflows.facts_by_instance(scope, [instance_id])[instance_id])
    changes = {key: value for key, value in accepted.items() if current.get(key) != value}
    if not changes:
        return _view(scope, item, context)

    revision = workflows.advance_revision(scope, instance_id, body.expected_revision)
    if revision is None:
        # Another save committed first. Same key: that save was this one.
        scope.rollback()
        if workflows.find_submission(scope, instance_id, body.submission_key) is not None:
            return _view(scope, _reload(scope, case_id), context)
        raise _conflict()
    workflows.record_submission(
        scope,
        item.instance,
        step_key=step.key,
        revision=revision,
        idempotency_key=body.submission_key,
        user_id=context.user_id,
        changes=changes,
    )
    scope.commit()
    return _view(scope, _reload(scope, case_id), context)
