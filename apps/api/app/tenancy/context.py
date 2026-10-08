"""Transaction-local PostgreSQL tenant context.

Row-Level Security policies compare each tenant-owned row with
``heroos_current_company_id()``, which reads the ``heroos.company_id`` setting.
This module is the only application code that sets it.

The setting is always written with ``set_config(..., is_local => true)``, the
function form of ``SET LOCAL``: it lasts until the current transaction commits or
rolls back and then disappears, so a pooled connection never carries one
request's Company into the next. A plain session-level ``SET`` must never be used.

With no setting, RLS matches no rows: tenant-private data is invisible and every
write is rejected.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

TENANT_CONTEXT_SETTING = "heroos.company_id"


class TenantContextError(Exception):
    """A tenant context could not be established safely."""


def set_tenant_context(session: Session, company_id: UUID) -> None:
    """Bind the session's current transaction to ``company_id``.

    Starts a transaction if none is active. A transaction serves exactly one
    Company: re-binding it to a different Company raises.

    ``company_id`` must come from trusted context (``AuthenticatedCompanyContext``)
    or, during Membership authorization only, from the requested Company whose
    Membership is being checked. Setting the context is not authorization.
    """
    # Validated before any SQL: only a real, non-nil UUID ever reaches PostgreSQL.
    if not isinstance(company_id, UUID) or company_id.int == 0:
        raise TenantContextError("tenant context requires a non-nil Company UUID")
    value = str(company_id)

    current = get_tenant_context(session)
    if current is not None and current != company_id:
        raise TenantContextError("transaction is already bound to a different Company")

    # Final argument true = transaction-local. Name and value are bound
    # parameters, never interpolated SQL.
    session.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": TENANT_CONTEXT_SETTING, "value": value},
    )


def get_tenant_context(session: Session) -> UUID | None:
    """The Company the current transaction is bound to, or ``None``."""
    value = session.scalar(
        text("SELECT current_setting(:name, true)"), {"name": TENANT_CONTEXT_SETTING}
    )
    # Unset is NULL before first use in a session and '' after a transaction-local
    # value has been reset.
    if not value:
        return None
    return UUID(value)
