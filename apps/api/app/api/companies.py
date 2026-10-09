"""Company-scoped read endpoints (B4 demo).

Every route takes ``{company_id}`` and depends on ``CompanyDb``: bearer token ->
provider -> HeroOS User -> Membership -> ``AuthenticatedCompanyContext`` ->
transaction-local tenant context -> Company-scoped repositories -> PostgreSQL RLS.
See docs/architecture/authentication.md and docs/architecture/tenant-isolation.md.

Responses:

- 401 ``Not authenticated``: missing or invalid credential.
- 403 ``Forbidden``: no Membership. Identical for another Company and for a
  Company that does not exist.
- 404 ``Not found``: a resource ID that is not in the authorized Company.
  Identical for another Company's ID and for an ID that exists nowhere.

Read-only: no route commits, so each request's transaction is rolled back when
the session closes.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.repositories import cases, companies
from app.tenancy.dependencies import CompanyDb

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


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.get("", response_model=CompanyOut)
def get_company(scope: CompanyDb) -> CompanyOut:
    company = companies.get_company(scope)
    if company is None:
        raise _not_found()
    return CompanyOut.model_validate(company)


@router.get("/cases", response_model=list[CaseOut])
def list_cases(scope: CompanyDb) -> list[CaseOut]:
    return [CaseOut.model_validate(case) for case in cases.list_cases(scope)]


@router.get("/cases/{case_id}", response_model=CaseOut)
def get_case(case_id: UUID, scope: CompanyDb) -> CaseOut:
    case = cases.get_case(scope, case_id)
    if case is None:
        raise _not_found()
    return CaseOut.model_validate(case)
