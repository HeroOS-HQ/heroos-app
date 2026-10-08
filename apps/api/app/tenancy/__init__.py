"""Tenant isolation: Company-scoped data access over PostgreSQL Row-Level Security.

See docs/architecture/tenant-isolation.md.
"""

from app.tenancy.context import (
    TENANT_CONTEXT_SETTING,
    TenantContextError,
    get_tenant_context,
    set_tenant_context,
)
from app.tenancy.scope import CompanyScope, open_company_scope

__all__ = [
    "TENANT_CONTEXT_SETTING",
    "CompanyScope",
    "TenantContextError",
    "get_tenant_context",
    "open_company_scope",
    "set_tenant_context",
]
