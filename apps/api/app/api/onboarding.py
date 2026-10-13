"""Founder self-registration and workspace discovery (M1-10C).

The only routes reachable before HeroOS knows a person:

- ``POST /company-registrations``: an authenticated identity that HeroOS has
  not provisioned may call this, and nothing else. It creates a new Company
  workspace with the caller as its first ``company_admin``
  (``app.companies.registration``). Off unless
  ``HEROOS_SELF_REGISTRATION_ENABLED`` is set (404 otherwise).
- ``GET /me/companies``: the caller's own active Company Memberships, so a
  returning founder finds their workspace. Unknown identities get the generic
  403, like every Company route.

Responses: 201 a Company was created; 200 this identity's earlier registration
(a retry or a concurrent submission; the request body is then ignored); 401 no
valid credential; 403 the identity, its User or the registered Membership is
not active; 404 registration is disabled; 422 invalid input (never echoed). The
client never chooses a Company id, user id, role or administrator.
"""

import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints
from sqlalchemy.orm import Session

from app.api.companies import BlueprintUpdate, blueprint_changes, refuse_untidy_text
from app.auth.dependencies import forbidden, get_current_user, get_verified_identity
from app.auth.exceptions import AuthorizationError
from app.auth.models import ResolvedUser, VerifiedIdentity
from app.companies.registration import (
    InvalidRegistration,
    list_identity_companies,
    register_founder_company,
)
from app.db.session import get_db
from app.observability.context import record_authorized_company
from app.repositories.company_blueprints import update_company_blueprint
from app.tenancy.scope import open_company_scope

logger = logging.getLogger(__name__)

router = APIRouter(tags=["onboarding"])

CompanyName = Annotated[
    str, StringConstraints(min_length=1, max_length=200), AfterValidator(refuse_untidy_text)
]


class CompanyRegistrationIn(BaseModel):
    """The onboarding form. ``blueprint`` takes the same fields as the
    administrator update (for example the licensing answer) and is applied in
    the same transaction as the registration."""

    model_config = ConfigDict(extra="forbid", strict=True)

    company_name: CompanyName
    blueprint: BlueprintUpdate | None = None


class CompanyRegistrationOut(BaseModel):
    outcome: Literal["created", "existing"]
    company_id: UUID
    membership_id: UUID
    role: Literal["company_admin"]


class WorkspaceOut(BaseModel):
    company_id: UUID
    name: str
    membership_id: UUID
    role: Literal["member", "company_admin"]


def require_self_registration(request: Request) -> None:
    if not request.app.state.self_registration_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.post(
    "/company-registrations",
    status_code=status.HTTP_201_CREATED,
    response_model=CompanyRegistrationOut,
    dependencies=[Depends(require_self_registration)],
)
def register_company(
    registration: CompanyRegistrationIn,
    identity: Annotated[VerifiedIdentity, Depends(get_verified_identity)],
    db: Annotated[Session, Depends(get_db)],
    response: Response,
) -> CompanyRegistrationOut:
    try:
        result = register_founder_company(db, identity, registration.company_name)
    except AuthorizationError as exc:
        logger.info("Registration denied: %s", exc.reason)
        raise forbidden() from None
    except InvalidRegistration:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[{"type": "value_error", "loc": ["body", "company_name"], "msg": "invalid"}],
        ) from None

    record_authorized_company(result.context)
    if result.created:
        if registration.blueprint is not None:
            scope = open_company_scope(db, result.context)
            update_company_blueprint(scope, blueprint_changes(registration.blueprint))
        db.commit()
        logger.info("Company registered (company_id=%s)", result.company_id)
    else:
        db.rollback()
        response.status_code = status.HTTP_200_OK
    return CompanyRegistrationOut(
        outcome=result.outcome,  # type: ignore[arg-type]
        company_id=result.company_id,
        membership_id=result.membership_id,
        role="company_admin",
    )


@router.get("/me/companies", response_model=list[WorkspaceOut])
def list_my_companies(
    _user: Annotated[ResolvedUser, Depends(get_current_user)],
    identity: Annotated[VerifiedIdentity, Depends(get_verified_identity)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WorkspaceOut]:
    return [
        WorkspaceOut(
            company_id=workspace.company_id,
            name=workspace.company_name,
            membership_id=workspace.membership_id,
            role=workspace.role,  # type: ignore[arg-type]
        )
        for workspace in list_identity_companies(db, identity)
    ]
