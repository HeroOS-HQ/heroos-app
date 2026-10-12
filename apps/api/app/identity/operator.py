"""Operator session helpers: attribution and the one-Company operator scope.

``open_operator_company_scope`` is the only source of a ``CompanyScope`` outside
an authenticated request. It exists for Membership changes by a platform
operator: one Company, one transaction, under the same Row-Level Security as the
API. It is not a worker or system context (background execution is ADR-009) and
it is imported only by the operator CLI (enforced by
``tests/test_import_boundaries.py``).
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.identity.errors import COMPANY_NOT_FOUND, IdentityOperationError
from app.identity.validation import validate_actor_reference
from app.tenancy.context import TenantContextError, set_tenant_context
from app.tenancy.scope import CompanyScope

ACTOR_REFERENCE_SETTING = "heroos.actor_reference"


def set_actor_reference(session: Session, reference: str) -> None:
    """Attribute this transaction's changes to a change reference (issue key).

    Transaction-local, like the tenant context. The audit triggers reject any
    identity or Membership change without a valid reference.
    """
    session.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": ACTOR_REFERENCE_SETTING, "value": validate_actor_reference(reference)},
    )


def open_operator_company_scope(session: Session, company_id: UUID) -> CompanyScope:
    """Bind this transaction to an existing Company chosen by the operator."""
    try:
        set_tenant_context(session, company_id)
    except TenantContextError:
        raise IdentityOperationError(COMPANY_NOT_FOUND) from None
    # Column-level SELECT (id) under the tenant_isolation policy: the Company is
    # visible only if it exists and is the one in context.
    found = session.scalar(text("SELECT id FROM companies WHERE id = :id"), {"id": company_id})
    if found is None:
        raise IdentityOperationError(COMPANY_NOT_FOUND)
    return CompanyScope(session=session, company_id=company_id)
