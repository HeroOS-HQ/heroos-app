"""Company-scoped endpoints (B4 demo; Company roles and Blueprint in M1-10C).

Every route takes ``{company_id}`` and depends on ``CompanyDb`` (any active
member) or ``CompanyAdminDb`` (an active ``company_admin``): bearer token ->
provider -> HeroOS User -> Membership (and its role) ->
``AuthenticatedCompanyContext`` -> transaction-local tenant context ->
Company-scoped repositories -> PostgreSQL RLS. See
docs/architecture/authentication.md and docs/architecture/tenant-isolation.md.

Responses:

- 401 ``Not authenticated``: missing or invalid credential.
- 403 ``Forbidden``: no Membership, or a member calling an administrator-only
  route. Identical for another Company and for a Company that does not exist.
- 404 ``Not found``: a resource ID that is not in the authorized Company.
  Identical for another Company's ID and for an ID that exists nowhere.
- 422: invalid input, including any field the route does not accept (role,
  Company or jurisdiction confirmation fields are never accepted). Submitted
  values are never echoed.

Case records of restricted types (Disciplinary, ``app.workflows.access``) are
for Company administrators only: a member's list leaves them out and a member
reading one gets the same 404 as for a missing record.

Only ``PATCH /blueprint`` commits; every other request's transaction is rolled
back when the session closes. Founder self-registration is
``app.api.onboarding``; role assignment has no HTTP route (trusted operator
operation, docs/operations/company-registration.md).
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.auth.dependencies import CompanyContext
from app.companies.jurisdiction import (
    JurisdictionAssessment,
    JurisdictionReadiness,
    ReadinessReason,
    assess_jurisdiction,
)
from app.db.models import CompanyBlueprint
from app.db.models.company_blueprint import MAX_LICENSING_AUTHORITY_LENGTH
from app.db.models.membership import ROLE_COMPANY_ADMIN
from app.repositories import cases, companies
from app.repositories.company_blueprints import get_company_blueprint, update_company_blueprint
from app.tenancy.dependencies import CompanyAdminDb, CompanyDb
from app.workflows.access import hidden_case_types, may_access_case_type

router = APIRouter(prefix="/companies/{company_id}", tags=["companies"])


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    subject_id: UUID | None
    case_type: str
    title: str
    created_at: datetime
    updated_at: datetime


Role = Literal["member", "company_admin"]
LicensingLocation = Literal["difc", "other", "not_sure"]
EmploymentJurisdiction = Literal["uae_federal", "difc", "adgm", "other"]


class MembershipOut(BaseModel):
    """The caller's own access to this Company."""

    company_id: UUID
    membership_id: UUID
    role: Role
    can_update_blueprint: bool


class LicensingOut(BaseModel):
    location: LicensingLocation | None
    authority: str | None


class JurisdictionOut(BaseModel):
    readiness: JurisdictionReadiness
    reason: ReadinessReason
    # Present only while a confirmation is current (supported or unsupported).
    employment_jurisdiction: EmploymentJurisdiction | None
    confirmed_at: datetime | None
    guidance_allowed: bool


class BlueprintOut(BaseModel):
    company_id: UUID
    legal_name: str | None
    industry: str | None
    employee_count: int | None
    licensing: LicensingOut
    jurisdiction: JurisdictionOut
    updated_at: datetime | None


def refuse_untidy_text(value: str) -> str:
    # Validated, never normalized: the client sends exactly what is stored.
    if value != value.strip() or not value.isprintable():
        raise ValueError("must not have surrounding whitespace or control characters")
    return value


LegalName = Annotated[
    str, StringConstraints(min_length=1, max_length=200), AfterValidator(refuse_untidy_text)
]
Industry = Annotated[
    str, StringConstraints(min_length=1, max_length=120), AfterValidator(refuse_untidy_text)
]
LicensingAuthority = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_LICENSING_AUTHORITY_LENGTH),
    AfterValidator(refuse_untidy_text),
]


class LicensingIn(BaseModel):
    """The onboarding licensing answer, replaced as a whole.

    ``location``: ``difc``, ``other`` or ``not_sure`` (``null`` withdraws the
    answer). ``authority`` is the licensing authority's name, only with
    ``other``; ``other`` without it stays unresolved. There is no approved
    authority list yet, so the name is free text and is never interpreted.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    location: LicensingLocation | None
    authority: LicensingAuthority | None = None

    @model_validator(mode="after")
    def _authority_only_with_other(self) -> "LicensingIn":
        if self.authority is not None and self.location != "other":
            raise ValueError("authority is accepted only with location 'other'")
        return self


class BlueprintUpdate(BaseModel):
    """Administrator changes. Only the fields sent are changed; ``null`` clears.

    Unknown fields are refused (``extra="forbid"``): role, Company and the
    jurisdiction confirmation can never be mass-assigned.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    legal_name: LegalName | None = None
    industry: Industry | None = None
    employee_count: Annotated[int, Field(ge=0, le=10_000_000)] | None = None
    licensing: LicensingIn | None = None


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def jurisdiction_out(assessment: JurisdictionAssessment) -> JurisdictionOut:
    """The API view of a jurisdiction assessment (also used by workflow Cases)."""
    return JurisdictionOut(
        readiness=assessment.readiness,
        reason=assessment.reason,
        employment_jurisdiction=assessment.jurisdiction,  # type: ignore[arg-type]
        confirmed_at=assessment.confirmed_at,
        guidance_allowed=assessment.guidance_allowed,
    )


def _blueprint_out(company_id: UUID, blueprint: CompanyBlueprint | None) -> BlueprintOut:
    """Every authorized Company has a Blueprint view; a missing row reads as empty."""
    jurisdiction = jurisdiction_out(assess_jurisdiction(blueprint))
    if blueprint is None:
        return BlueprintOut(
            company_id=company_id,
            legal_name=None,
            industry=None,
            employee_count=None,
            licensing=LicensingOut(location=None, authority=None),
            jurisdiction=jurisdiction,
            updated_at=None,
        )
    return BlueprintOut(
        company_id=blueprint.company_id,
        legal_name=blueprint.legal_name,
        industry=blueprint.industry,
        employee_count=blueprint.employee_count,
        licensing=LicensingOut(
            location=blueprint.licensing_location,  # type: ignore[arg-type]
            authority=blueprint.licensing_authority,
        ),
        jurisdiction=jurisdiction,
        updated_at=blueprint.updated_at,
    )


@router.get("", response_model=CompanyOut)
def get_company(scope: CompanyDb) -> CompanyOut:
    company = companies.get_company(scope)
    if company is None:
        raise _not_found()
    return CompanyOut.model_validate(company)


@router.get("/membership", response_model=MembershipOut)
def get_own_membership(context: CompanyContext) -> MembershipOut:
    """Role facts for the onboarding UI; authorization stays server-side."""
    is_admin = context.role == ROLE_COMPANY_ADMIN
    return MembershipOut(
        company_id=context.company_id,
        membership_id=context.membership_id,
        role=context.role,  # type: ignore[arg-type]
        can_update_blueprint=is_admin,
    )


@router.get("/blueprint", response_model=BlueprintOut)
def get_blueprint(scope: CompanyDb) -> BlueprintOut:
    return _blueprint_out(scope.company_id, get_company_blueprint(scope))


def blueprint_changes(update: BlueprintUpdate) -> dict[str, object]:
    """Repository changes for the fields actually sent (``null`` clears)."""
    sent = update.model_fields_set
    changes: dict[str, object] = {
        field: getattr(update, field)
        for field in ("legal_name", "industry", "employee_count")
        if field in sent
    }
    if "licensing" in sent:
        licensing = update.licensing
        changes["licensing_location"] = None if licensing is None else licensing.location
        changes["licensing_authority"] = None if licensing is None else licensing.authority
    return changes


@router.patch("/blueprint", response_model=BlueprintOut)
def update_blueprint(update: BlueprintUpdate, scope: CompanyAdminDb) -> BlueprintOut:
    blueprint = update_company_blueprint(scope, blueprint_changes(update))
    scope.commit()
    return _blueprint_out(scope.company_id, blueprint)


@router.get("/cases", response_model=list[CaseOut])
def list_cases(scope: CompanyDb, context: CompanyContext) -> list[CaseOut]:
    # Disciplinary records are administrator-only (app.workflows.access).
    hidden = hidden_case_types(context.role)
    return [
        CaseOut.model_validate(case) for case in cases.list_cases(scope, exclude_case_types=hidden)
    ]


@router.get("/cases/{case_id}", response_model=CaseOut)
def get_case(case_id: UUID, scope: CompanyDb, context: CompanyContext) -> CaseOut:
    case = cases.get_case(scope, case_id)
    # A restricted record reads exactly like a missing one for a member.
    if case is None or not may_access_case_type(context.role, case.case_type):
        raise _not_found()
    return CaseOut.model_validate(case)
