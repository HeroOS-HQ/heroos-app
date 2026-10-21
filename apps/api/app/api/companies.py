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
back when the session closes.

The Blueprint read model is ``app.companies.blueprint``'s canonical company
context (M2-NEW-03): the Company's display name (``companies.name``, read
only), its business profile and company context, its jurisdiction exactly as
the workflows see it, the primary contact and the people with access (no
names or emails: HeroOS keeps none), and what still needs attention. Founder self-registration is
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
    Strict,
    StrictStr,
    StringConstraints,
    model_validator,
)

from app.auth.dependencies import CompanyContext, forbidden
from app.auth.exceptions import AuthorizationError
from app.auth.models import AuthenticatedCompanyContext
from app.companies.blueprint import (
    CompanyBlueprintView,
    CompanyPerson,
    InvalidPrimaryContact,
    load_company_blueprint,
    normalize_website_url,
    plain_text,
    save_blueprint_changes,
)
from app.companies.jurisdiction import (
    JurisdictionAssessment,
    JurisdictionReadiness,
    ReadinessReason,
)
from app.db.models.company_blueprint import (
    MAX_COMPANY_SUMMARY_LENGTH,
    MAX_HR_SUPPORT_NOTES_LENGTH,
    MAX_LICENSING_AUTHORITY_LENGTH,
    MAX_POLICY_CONTEXT_LENGTH,
)
from app.db.models.membership import ROLE_COMPANY_ADMIN
from app.repositories import cases, companies
from app.tenancy.dependencies import CompanyAdminDb, CompanyDb
from app.tenancy.scope import CompanyScope
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
PoliciesExist = Literal["yes", "no", "not_sure"]
HrSupport = Literal["none", "internal", "external", "mixed", "other"]
# app.companies.blueprint.BLUEPRINT_DETAILS
BlueprintDetail = Literal[
    "legal_name",
    "industry",
    "employee_count",
    "company_summary",
    "jurisdiction",
    "policies",
    "hr_support",
    "primary_contact",
]


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


class PersonOut(BaseModel):
    """Someone with access to the Company. HeroOS keeps no names or email addresses."""

    membership_id: UUID
    role: Role
    member_since: datetime
    is_current_user: bool
    is_primary_contact: bool


class CompletenessOut(BaseModel):
    complete: bool
    missing: list[BlueprintDetail]


class BlueprintOut(BaseModel):
    company_id: UUID
    # companies.name: the workspace's display name, read only here.
    company_name: str
    legal_name: str | None
    industry: str | None
    employee_count: int | None
    website_url: str | None
    company_summary: str | None
    licensing: LicensingOut
    jurisdiction: JurisdictionOut
    policies_exist: PoliciesExist | None
    policy_context: str | None
    hr_support: HrSupport | None
    hr_support_notes: str | None
    primary_contact: PersonOut | None
    # Everyone with active access, oldest first (the primary contact's choices).
    people: list[PersonOut]
    completeness: CompletenessOut
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
# Normalized (app.companies.blueprint.normalize_website_url): the response
# returns the stored form. The input bound only limits the work done.
WebsiteUrl = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=600),
    AfterValidator(normalize_website_url),
]
CompanySummary = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=MAX_COMPANY_SUMMARY_LENGTH),
    AfterValidator(plain_text),
]
PolicyContext = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=MAX_POLICY_CONTEXT_LENGTH),
    AfterValidator(plain_text),
]
HrSupportNotes = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=MAX_HR_SUPPORT_NOTES_LENGTH),
    AfterValidator(plain_text),
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


class BlueprintFields(BaseModel):
    """The company's own answers, validated once for every write path.

    Founder registration takes exactly these (``app.api.onboarding``); the
    administrator update adds the primary contact. Only the fields sent are
    changed; ``null`` clears. Unknown fields are refused (``extra="forbid"``):
    role, Company and the jurisdiction confirmation can never be mass-assigned.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    legal_name: LegalName | None = None
    industry: Industry | None = None
    employee_count: Annotated[int, Field(ge=0, le=10_000_000)] | None = None
    licensing: LicensingIn | None = None
    website_url: WebsiteUrl | None = None
    company_summary: CompanySummary | None = None
    policies_exist: PoliciesExist | None = None
    policy_context: PolicyContext | None = None
    hr_support: HrSupport | None = None
    hr_support_notes: HrSupportNotes | None = None


class BlueprintUpdate(BlueprintFields):
    """Administrator changes, including the primary contact.

    ``primary_contact_membership_id`` must be an active Membership of this
    Company (checked in the write transaction; the same 422 for anything else,
    another Company's Membership included).
    """

    # JSON has no UUID type: the id arrives as a string.
    primary_contact_membership_id: Annotated[UUID, Strict(False)] | None = None


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


def _person_out(person: CompanyPerson) -> PersonOut:
    return PersonOut(
        membership_id=person.membership_id,
        role=person.role,  # type: ignore[arg-type]
        member_since=person.member_since,
        is_current_user=person.is_current_user,
        is_primary_contact=person.is_primary_contact,
    )


def blueprint_out(view: CompanyBlueprintView) -> BlueprintOut:
    """The API view of the canonical context. A missing Blueprint row reads as empty."""
    context = view.context
    jurisdiction = context.jurisdiction
    return BlueprintOut(
        company_id=context.company_id,
        company_name=context.company_display_name,
        legal_name=context.legal_name,
        industry=context.industry,
        employee_count=context.employee_count,
        website_url=context.website_url,
        company_summary=context.company_summary,
        licensing=LicensingOut(
            location=jurisdiction.licensing_location,  # type: ignore[arg-type]
            authority=jurisdiction.licensing_authority,
        ),
        jurisdiction=JurisdictionOut(
            readiness=JurisdictionReadiness(jurisdiction.readiness),
            reason=ReadinessReason(jurisdiction.reason),
            employment_jurisdiction=jurisdiction.employment_jurisdiction,  # type: ignore[arg-type]
            confirmed_at=jurisdiction.confirmed_at,
            guidance_allowed=jurisdiction.guidance_allowed,
        ),
        policies_exist=context.policies_exist,  # type: ignore[arg-type]
        policy_context=context.policy_context,
        hr_support=context.hr_support,  # type: ignore[arg-type]
        hr_support_notes=context.hr_support_notes,
        primary_contact=None
        if context.primary_contact is None
        else _person_out(context.primary_contact),
        people=[_person_out(person) for person in view.people],
        completeness=CompletenessOut(
            complete=context.complete,
            missing=list(context.missing),  # type: ignore[arg-type]
        ),
        updated_at=context.updated_at,
    )


def _read_blueprint(scope: CompanyScope, context: AuthenticatedCompanyContext) -> BlueprintOut:
    try:
        return blueprint_out(load_company_blueprint(scope, context))
    except AuthorizationError:
        # The caller's own Membership ended after authorization.
        raise forbidden() from None


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
def get_blueprint(scope: CompanyDb, context: CompanyContext) -> BlueprintOut:
    return _read_blueprint(scope, context)


def blueprint_changes(update: BlueprintFields) -> dict[str, object]:
    """Repository changes for the fields actually sent (``null`` clears).

    Every field maps to the column of the same name, except the licensing
    answer (one object, two columns).
    """
    sent = update.model_fields_set
    changes: dict[str, object] = {
        field: getattr(update, field)
        for field in type(update).model_fields
        if field in sent and field != "licensing"
    }
    if "licensing" in sent:
        licensing = update.licensing
        changes["licensing_location"] = None if licensing is None else licensing.location
        changes["licensing_authority"] = None if licensing is None else licensing.authority
    return changes


def invalid_primary_contact() -> HTTPException:
    """The 422 for a primary contact outside the Company (never says why)."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[
            {
                "type": "value_error",
                "loc": ["body", "primary_contact_membership_id"],
                "msg": "invalid",
            }
        ],
    )


@router.patch("/blueprint", response_model=BlueprintOut)
def update_blueprint(
    update: BlueprintUpdate, scope: CompanyAdminDb, context: CompanyContext
) -> BlueprintOut:
    try:
        save_blueprint_changes(scope, blueprint_changes(update))
    except InvalidPrimaryContact:
        scope.rollback()
        raise invalid_primary_contact() from None
    scope.commit()
    return _read_blueprint(scope, context)


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
