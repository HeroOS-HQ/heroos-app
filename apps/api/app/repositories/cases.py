from collections.abc import Collection, Sequence
from uuid import UUID

from sqlalchemy import select

from app.db.models import Case
from app.repositories import ResourceNotFoundError
from app.repositories.case_subjects import get_case_subject
from app.tenancy.scope import CompanyScope


def _require_subject(scope: CompanyScope, subject_id: UUID | None) -> None:
    # The composite (company_id, subject_id) FK also enforces this in the
    # database; checking here turns a cross-Company reference into "not found".
    if subject_id is not None and get_case_subject(scope, subject_id) is None:
        raise ResourceNotFoundError("case subject not found")


def create_case(
    scope: CompanyScope,
    *,
    case_type: str,
    title: str,
    subject_id: UUID | None = None,
) -> Case:
    _require_subject(scope, subject_id)
    case = Case(
        company_id=scope.company_id,
        case_type=case_type,
        title=title,
        subject_id=subject_id,
    )
    scope.session.add(case)
    scope.session.flush()
    return case


def get_case(scope: CompanyScope, case_id: UUID) -> Case | None:
    return scope.session.scalar(
        select(Case).where(
            Case.company_id == scope.company_id,
            Case.id == case_id,
        )
    )


def list_cases(scope: CompanyScope, *, exclude_case_types: Collection[str] = ()) -> Sequence[Case]:
    query = select(Case).where(Case.company_id == scope.company_id)
    if exclude_case_types:
        query = query.where(Case.case_type.not_in(list(exclude_case_types)))
    return scope.session.scalars(query.order_by(Case.created_at, Case.id)).all()


def update_case(
    scope: CompanyScope,
    case_id: UUID,
    *,
    case_type: str,
    title: str,
) -> Case | None:
    case = get_case(scope, case_id)
    if case is None:
        return None
    case.case_type = case_type
    case.title = title
    scope.session.flush()
    return case


def assign_case_subject(
    scope: CompanyScope,
    case_id: UUID,
    subject_id: UUID | None,
) -> Case | None:
    """Point a Case at a CaseSubject of the same Company, or clear it."""
    case = get_case(scope, case_id)
    if case is None:
        return None
    _require_subject(scope, subject_id)
    case.subject_id = subject_id
    scope.session.flush()
    return case


def delete_case(scope: CompanyScope, case_id: UUID) -> bool:
    case = get_case(scope, case_id)
    if case is None:
        return False
    scope.session.delete(case)
    scope.session.flush()
    return True
