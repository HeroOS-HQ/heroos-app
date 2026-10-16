"""Company-scoped persistence of workflow Cases, submissions, facts and evaluations.

Every function takes a ``CompanyScope`` and filters by ``scope.company_id``;
PostgreSQL RLS enforces the same boundary underneath. Repositories flush but
never commit (tenant-isolation.md §2). There is no update or delete of facts,
submissions or evaluations: they are append-only, and the only instance update
is the optimistic-concurrency revision bump.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import Select, func, select, update

from app.db.models import (
    Case,
    CaseFact,
    WorkflowEvaluation,
    WorkflowInstance,
    WorkflowSubmission,
)
from app.tenancy.scope import CompanyScope
from app.workflows.conversation import SubmissionRecord
from app.workflows.definition import WorkflowDefinition
from app.workflows.history import EvaluationRecord
from app.workflows.intake import EarlierEscalation, HoldReason, IntakeEvaluation
from app.workflows.progress import FactRecord


@dataclass(frozen=True, slots=True)
class WorkflowCase:
    case: Case
    instance: WorkflowInstance


def create_workflow_case(
    scope: CompanyScope,
    definition: WorkflowDefinition,
    *,
    title: str,
    request_key: UUID,
    user_id: UUID,
) -> WorkflowCase:
    """A new Case with its workflow instance. Raises IntegrityError on a reused key."""
    case = Case(company_id=scope.company_id, case_type=definition.case_type, title=title)
    scope.session.add(case)
    scope.session.flush()
    instance = WorkflowInstance(
        company_id=scope.company_id,
        case_id=case.id,
        workflow_key=definition.key,
        definition_version=definition.version,
        revision=0,
        request_key=request_key,
        created_by_user_id=user_id,
    )
    scope.session.add(instance)
    scope.session.flush()
    return WorkflowCase(case, instance)


def _cases_query(scope: CompanyScope) -> Select[Case, WorkflowInstance]:
    return (
        select(Case, WorkflowInstance)
        .join(
            WorkflowInstance,
            (WorkflowInstance.company_id == Case.company_id)
            & (WorkflowInstance.case_id == Case.id),
        )
        .where(Case.company_id == scope.company_id, WorkflowInstance.company_id == scope.company_id)
    )


def find_by_request_key(scope: CompanyScope, request_key: UUID) -> WorkflowCase | None:
    row = scope.session.execute(
        _cases_query(scope).where(WorkflowInstance.request_key == request_key)
    ).first()
    return None if row is None else WorkflowCase(row[0], row[1])


def get_workflow_case(
    scope: CompanyScope, case_id: UUID, *, for_update: bool = False
) -> WorkflowCase | None:
    """The workflow Case, optionally locking its instance row for this transaction.

    ``for_update`` serializes writers of one Case: a concurrent save waits for
    the lock, then reads the committed revision, submissions and facts, so
    everything one request reads is mutually consistent. Only the instance row
    is locked (``FOR UPDATE OF workflow_instances``), never the Case.
    """
    query = _cases_query(scope).where(Case.id == case_id)
    if for_update:
        query = query.with_for_update(of=WorkflowInstance)
    row = scope.session.execute(query).first()
    return None if row is None else WorkflowCase(row[0], row[1])


def list_workflow_cases(scope: CompanyScope, workflow_key: str) -> list[WorkflowCase]:
    """Most recently active first."""
    rows = scope.session.execute(
        _cases_query(scope)
        .where(WorkflowInstance.workflow_key == workflow_key)
        .order_by(WorkflowInstance.updated_at.desc(), Case.id)
    ).all()
    return [WorkflowCase(case, instance) for case, instance in rows]


def facts_by_instance(
    scope: CompanyScope, instance_ids: Sequence[UUID]
) -> dict[UUID, list[FactRecord]]:
    """Every stored fact of the given instances, in revision order."""
    result: dict[UUID, list[FactRecord]] = {instance_id: [] for instance_id in instance_ids}
    if not instance_ids:
        return result
    rows = scope.session.execute(
        select(CaseFact.instance_id, WorkflowSubmission.revision, CaseFact.fact_key, CaseFact.value)
        .join(
            WorkflowSubmission,
            (WorkflowSubmission.company_id == CaseFact.company_id)
            & (WorkflowSubmission.id == CaseFact.submission_id),
        )
        .where(
            CaseFact.company_id == scope.company_id,
            WorkflowSubmission.company_id == scope.company_id,
            CaseFact.instance_id.in_(instance_ids),
        )
        .order_by(WorkflowSubmission.revision, CaseFact.fact_key)
    ).all()
    for instance_id, revision, key, value in rows:
        result[instance_id].append(FactRecord(revision, key, value))
    return result


def submissions(scope: CompanyScope, instance_id: UUID) -> list[SubmissionRecord]:
    """The instance's saved answer groups with their facts, oldest first."""
    rows = scope.session.scalars(
        select(WorkflowSubmission)
        .where(
            WorkflowSubmission.company_id == scope.company_id,
            WorkflowSubmission.instance_id == instance_id,
        )
        .order_by(WorkflowSubmission.revision)
    ).all()
    facts = scope.session.execute(
        select(CaseFact.submission_id, CaseFact.fact_key, CaseFact.value).where(
            CaseFact.company_id == scope.company_id, CaseFact.instance_id == instance_id
        )
    ).all()
    by_submission: dict[UUID, dict[str, object]] = {}
    for submission_id, key, value in facts:
        by_submission.setdefault(submission_id, {})[key] = value
    return [
        SubmissionRecord(
            id=row.id,
            step_key=row.step_key,
            revision=row.revision,
            submitted_at=row.submitted_at,
            submitted_by_user_id=row.submitted_by_user_id,
            facts=by_submission.get(row.id, {}),
        )
        for row in rows
    ]


def find_submission(
    scope: CompanyScope, instance_id: UUID, idempotency_key: UUID
) -> WorkflowSubmission | None:
    return scope.session.scalar(
        select(WorkflowSubmission).where(
            WorkflowSubmission.company_id == scope.company_id,
            WorkflowSubmission.instance_id == instance_id,
            WorkflowSubmission.idempotency_key == idempotency_key,
        )
    )


def advance_revision(scope: CompanyScope, instance_id: UUID, expected: int) -> int | None:
    """Compare-and-set the instance revision; the new revision, or None if stale.

    One atomic UPDATE: a concurrent writer holding the same expected revision
    waits for the row lock, then finds the revision changed and gets None.
    """
    new_revision = scope.session.execute(
        update(WorkflowInstance)
        .where(
            WorkflowInstance.company_id == scope.company_id,
            WorkflowInstance.id == instance_id,
            WorkflowInstance.revision == expected,
        )
        .values(revision=WorkflowInstance.revision + 1, updated_at=func.now())
        .returning(WorkflowInstance.revision)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    return new_revision


def record_submission(
    scope: CompanyScope,
    instance: WorkflowInstance,
    *,
    step_key: str,
    revision: int,
    idempotency_key: UUID,
    user_id: UUID,
    changes: Mapping[str, object],
) -> WorkflowSubmission:
    """Append one answer group and its facts (call after ``advance_revision``)."""
    submission = WorkflowSubmission(
        company_id=scope.company_id,
        instance_id=instance.id,
        step_key=step_key,
        revision=revision,
        idempotency_key=idempotency_key,
        submitted_by_user_id=user_id,
    )
    scope.session.add(submission)
    scope.session.flush()
    scope.session.add_all(
        CaseFact(
            company_id=scope.company_id,
            instance_id=instance.id,
            submission_id=submission.id,
            fact_key=key,
            value=value,
        )
        for key, value in changes.items()
    )
    scope.session.flush()
    return submission


def record_evaluation(
    scope: CompanyScope,
    submission: WorkflowSubmission,
    evaluation: IntakeEvaluation,
    results: Sequence[Mapping[str, object]],
) -> WorkflowEvaluation:
    """Append the intake evaluation a submission produced (same transaction)."""
    row = WorkflowEvaluation(
        company_id=scope.company_id,
        instance_id=submission.instance_id,
        submission_id=submission.id,
        definition_version=evaluation.definition_version,
        ruleset_version=evaluation.ruleset_version,
        ruleset_digest=evaluation.ruleset_digest,
        status=evaluation.status,
        hold=None if evaluation.hold is None else evaluation.hold.kind,
        hold_reason=None if evaluation.hold is None else evaluation.hold.reason,
        jurisdiction=evaluation.jurisdiction.jurisdiction,
        screening=evaluation.screening,
        results=list(results),
    )
    scope.session.add(row)
    scope.session.flush()
    return row


def evaluations(scope: CompanyScope, instance_id: UUID) -> dict[UUID, EvaluationRecord]:
    """The instance's stored evaluations by submission id."""
    rows = scope.session.scalars(
        select(WorkflowEvaluation).where(
            WorkflowEvaluation.company_id == scope.company_id,
            WorkflowEvaluation.instance_id == instance_id,
        )
    ).all()
    return {
        row.submission_id: EvaluationRecord(
            submission_id=row.submission_id,
            status=row.status,
            hold=row.hold,
            hold_reason=row.hold_reason,
            jurisdiction=row.jurisdiction,
            screening=row.screening,
            results=list(row.results),
        )
        for row in rows
    }


def first_escalations(
    scope: CompanyScope, instance_ids: Sequence[UUID]
) -> dict[UUID, EarlierEscalation]:
    """Per instance, the first stored evaluation that held it for specialist review.

    Escalations are never released by changed answers (app.workflows.intake),
    so every later evaluation and read keeps the Case held from this one on.
    """
    if not instance_ids:
        return {}
    rows = scope.session.execute(
        select(
            WorkflowEvaluation.instance_id,
            WorkflowEvaluation.hold_reason,
            WorkflowEvaluation.evaluated_at,
        )
        .join(
            WorkflowSubmission,
            (WorkflowSubmission.company_id == WorkflowEvaluation.company_id)
            & (WorkflowSubmission.id == WorkflowEvaluation.submission_id),
        )
        .where(
            WorkflowEvaluation.company_id == scope.company_id,
            WorkflowSubmission.company_id == scope.company_id,
            WorkflowEvaluation.instance_id.in_(instance_ids),
            WorkflowEvaluation.hold == "specialist_review",
        )
        .order_by(WorkflowSubmission.revision)
    ).all()
    first: dict[UUID, EarlierEscalation] = {}
    for instance_id, reason, evaluated_at in rows:
        if instance_id not in first:
            # The CHECK constraint ties a specialist_review hold to a reason code.
            first[instance_id] = EarlierEscalation(cast(HoldReason, reason), evaluated_at)
    return first
