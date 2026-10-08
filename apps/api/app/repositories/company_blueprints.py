from dataclasses import dataclass

from sqlalchemy import select

from app.db.models import CompanyBlueprint
from app.tenancy.scope import CompanyScope


@dataclass(frozen=True, slots=True)
class CompanyBlueprintFields:
    legal_name: str | None = None
    primary_jurisdiction: str | None = None
    industry: str | None = None
    employee_count: int | None = None


def get_company_blueprint(scope: CompanyScope) -> CompanyBlueprint | None:
    """The scope Company's Blueprint (at most one per Company)."""
    return scope.session.scalar(
        select(CompanyBlueprint).where(CompanyBlueprint.company_id == scope.company_id)
    )


def save_company_blueprint(scope: CompanyScope, fields: CompanyBlueprintFields) -> CompanyBlueprint:
    """Create the scope Company's Blueprint, or replace its fields."""
    blueprint = get_company_blueprint(scope)
    if blueprint is None:
        blueprint = CompanyBlueprint(company_id=scope.company_id)
        scope.session.add(blueprint)
    blueprint.legal_name = fields.legal_name
    blueprint.primary_jurisdiction = fields.primary_jurisdiction
    blueprint.industry = fields.industry
    blueprint.employee_count = fields.employee_count
    scope.session.flush()
    return blueprint


def delete_company_blueprint(scope: CompanyScope) -> bool:
    blueprint = get_company_blueprint(scope)
    if blueprint is None:
        return False
    scope.session.delete(blueprint)
    scope.session.flush()
    return True
