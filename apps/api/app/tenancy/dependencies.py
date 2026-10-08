"""FastAPI dependency for Company-scoped database access.

Routes that read or write tenant-owned data depend on ``CompanyDb``::

    @router.get("/companies/{company_id}/cases/{case_id}")
    def get_case(case_id: UUID, scope: CompanyDb) -> ...:
        case = cases.get_case(scope, case_id)

The scope is built only from ``AuthenticatedCompanyContext``, never from the
client-supplied ``company_id`` alone.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import CompanyContext
from app.db.session import get_db
from app.tenancy.scope import CompanyScope, open_company_scope


def get_company_scope(
    context: CompanyContext,
    db: Annotated[Session, Depends(get_db)],
) -> CompanyScope:
    return open_company_scope(db, context)


CompanyDb = Annotated[CompanyScope, Depends(get_company_scope)]
