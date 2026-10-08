from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.auth.models import AuthenticatedCompanyContext
from app.tenancy.context import set_tenant_context


@dataclass(frozen=True, slots=True)
class CompanyScope:
    """Database access for one authorized Company.

    Every tenant repository takes a ``CompanyScope`` and filters by
    ``company_id`` itself; PostgreSQL RLS enforces the same boundary underneath.
    Build it with ``open_company_scope`` so the application filter and the
    database tenant context always carry the same trusted Company.

    The tenant context lasts for one transaction. After ``session.commit()`` or
    ``rollback()`` tenant-private rows are invisible again until a new scope is
    opened.
    """

    session: Session
    company_id: UUID


def open_company_scope(session: Session, context: AuthenticatedCompanyContext) -> CompanyScope:
    """Scope ``session`` to the Membership-authorized Company in ``context``."""
    set_tenant_context(session, context.company_id)
    return CompanyScope(session=session, company_id=context.company_id)
