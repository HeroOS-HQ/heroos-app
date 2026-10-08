from sqlalchemy import select

from app.db.models import Company
from app.tenancy.scope import CompanyScope


def get_company(scope: CompanyScope) -> Company | None:
    """The scope's own Company. No other Company is addressable."""
    return scope.session.scalar(select(Company).where(Company.id == scope.company_id))


def rename_company(scope: CompanyScope, name: str) -> Company | None:
    company = get_company(scope)
    if company is None:
        return None
    company.name = name
    scope.session.flush()
    return company
