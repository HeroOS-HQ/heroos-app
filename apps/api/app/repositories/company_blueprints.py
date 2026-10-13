from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select

from app.db.models import CompanyBlueprint
from app.tenancy.scope import CompanyScope

# Blueprint fields a Company administrator may change through the API
# (M1-10C). The jurisdiction confirmation is not among them: the API role has
# no privilege on those columns, and the legacy primary_jurisdiction is frozen.
CUSTOMER_FIELDS: Final = frozenset(
    {"legal_name", "industry", "employee_count", "licensing_location", "licensing_authority"}
)


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


def update_company_blueprint(
    scope: CompanyScope, changes: Mapping[str, object]
) -> CompanyBlueprint:
    """Apply customer-supplied ``changes`` to the scope Company's Blueprint.

    Only ``CUSTOMER_FIELDS``; anything else raises ``ValueError`` before any
    SQL. Creates the Blueprint if the Company has none. Values must already be
    validated (``app.api.companies.BlueprintUpdate``); the database CHECK
    constraints enforce the licensing rules again.
    """
    unexpected = set(changes) - CUSTOMER_FIELDS
    if unexpected:
        raise ValueError(f"not customer-editable Blueprint fields: {sorted(unexpected)}")
    blueprint = get_company_blueprint(scope)
    if blueprint is None:
        blueprint = CompanyBlueprint(company_id=scope.company_id)
        scope.session.add(blueprint)
    for name, value in changes.items():
        setattr(blueprint, name, value)
    scope.session.flush()
    return blueprint


def delete_company_blueprint(scope: CompanyScope) -> bool:
    blueprint = get_company_blueprint(scope)
    if blueprint is None:
        return False
    scope.session.delete(blueprint)
    scope.session.flush()
    return True
