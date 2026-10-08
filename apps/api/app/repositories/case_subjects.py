from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from app.db.models import CaseSubject
from app.tenancy.scope import CompanyScope


def create_case_subject(
    scope: CompanyScope,
    *,
    subject_type: str,
    display_name: str,
    reference: str | None = None,
) -> CaseSubject:
    subject = CaseSubject(
        company_id=scope.company_id,
        subject_type=subject_type,
        display_name=display_name,
        reference=reference,
    )
    scope.session.add(subject)
    scope.session.flush()
    return subject


def get_case_subject(scope: CompanyScope, subject_id: UUID) -> CaseSubject | None:
    return scope.session.scalar(
        select(CaseSubject).where(
            CaseSubject.company_id == scope.company_id,
            CaseSubject.id == subject_id,
        )
    )


def list_case_subjects(scope: CompanyScope) -> Sequence[CaseSubject]:
    return scope.session.scalars(
        select(CaseSubject)
        .where(CaseSubject.company_id == scope.company_id)
        .order_by(CaseSubject.created_at, CaseSubject.id)
    ).all()


def update_case_subject(
    scope: CompanyScope,
    subject_id: UUID,
    *,
    display_name: str,
    reference: str | None,
) -> CaseSubject | None:
    subject = get_case_subject(scope, subject_id)
    if subject is None:
        return None
    subject.display_name = display_name
    subject.reference = reference
    scope.session.flush()
    return subject


def delete_case_subject(scope: CompanyScope, subject_id: UUID) -> bool:
    subject = get_case_subject(scope, subject_id)
    if subject is None:
        return False
    scope.session.delete(subject)
    scope.session.flush()
    return True
