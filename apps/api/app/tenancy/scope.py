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

    The tenant context lasts for one transaction. After a plain
    ``session.commit()`` or ``rollback()`` tenant-private rows are invisible again
    (including ORM refreshes of already-loaded objects). Use ``commit()`` below to
    keep working in the same Company.
    """

    session: Session
    company_id: UUID

    def commit(self) -> None:
        """Commit, then bind the next transaction to the same Company."""
        self.session.commit()
        set_tenant_context(self.session, self.company_id)

    def rollback(self) -> None:
        """Roll back, then bind the next transaction to the same Company."""
        self.session.rollback()
        set_tenant_context(self.session, self.company_id)


def open_company_scope(session: Session, context: AuthenticatedCompanyContext) -> CompanyScope:
    """Scope ``session`` to the Membership-authorized Company in ``context``."""
    set_tenant_context(session, context.company_id)
    return CompanyScope(session=session, company_id=context.company_id)
