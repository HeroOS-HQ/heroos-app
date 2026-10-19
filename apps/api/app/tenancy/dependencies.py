"""FastAPI dependency for Company-scoped database access.

Routes that read or write tenant-owned data depend on ``CompanyDb``::

    @router.get("/companies/{company_id}/cases/{case_id}")
    def get_case(case_id: UUID, scope: CompanyDb) -> ...:
        case = cases.get_case(scope, case_id)

Administrator-only routes depend on ``CompanyAdminDb``, which additionally
re-checks the ``company_admin`` role inside the scoped transaction (M1-10C).
Administrator-only routes that must never write (document previews, M2-04C)
depend on ``CompanyAdminReadOnlyDb``: the same scope in a transaction that
refuses every write.

The scope is built only from ``AuthenticatedCompanyContext``, never from the
client-supplied ``company_id`` alone.
"""

import logging
from typing import Annotated

from fastapi import Depends
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.auth.dependencies import CompanyAdminContext, CompanyContext, forbidden
from app.auth.service import is_active_company_admin
from app.db.session import get_db
from app.tenancy.scope import CompanyScope, open_company_scope

logger = logging.getLogger(__name__)


def get_company_scope(
    context: CompanyContext,
    db: Annotated[Session, Depends(get_db)],
) -> CompanyScope:
    return open_company_scope(db, context)


CompanyDb = Annotated[CompanyScope, Depends(get_company_scope)]


def get_company_admin_scope(
    context: CompanyAdminContext,
    db: Annotated[Session, Depends(get_db)],
) -> CompanyScope:
    scope = open_company_scope(db, context)
    # The write runs in this transaction: confirm the role here again, so a
    # demotion or revocation between authorization and write is honoured.
    if not is_active_company_admin(db, context):
        logger.info(
            "Authorization denied: company administrator role no longer active (company_id=%s)",
            context.company_id,
        )
        db.rollback()
        raise forbidden()
    return scope


CompanyAdminDb = Annotated[CompanyScope, Depends(get_company_admin_scope)]


class ReadOnlyTransactionError(RuntimeError):
    """Something tried to write in a transaction that must not write."""


def _refuse_flush(session: Session, *_: object) -> None:
    if session.new or session.dirty or session.deleted:
        raise ReadOnlyTransactionError("this request must not write")


def make_read_only(session: Session) -> None:
    """No write can happen in the session's current transaction.

    PostgreSQL enforces it (``SET TRANSACTION READ ONLY``: any INSERT, UPDATE,
    DELETE or DDL fails; switching to read-only is allowed mid-transaction),
    and the ORM refuses to flush pending changes on any database.
    """
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SET TRANSACTION READ ONLY"))
    event.listen(session, "before_flush", _refuse_flush)


def get_company_admin_read_scope(scope: CompanyAdminDb) -> CompanyScope:
    """An administrator's scope whose transaction can't write (document previews)."""
    make_read_only(scope.session)
    return scope


CompanyAdminReadOnlyDb = Annotated[CompanyScope, Depends(get_company_admin_read_scope)]
