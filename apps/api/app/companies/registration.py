"""Self-service founder registration and workspace discovery (M1-10C).

A founder signs up at the identity provider (account, password, email
verification are the provider's job), then asks HeroOS for a Company workspace.
HeroOS turns the *verified* identity into a new Company, its empty Blueprint
and the founder's ``company_admin`` Membership in one transaction, through the
API role's only identity-creating capability, the database function
``heroos_register_company`` (migration ``3f6c2a9d81b4``):

- The issuer and subject come from the verified credential, never from the
  request body. No user id, Company id, role or administrator is accepted
  from the client.
- The function always creates a *new* Company with a server-generated id; it
  can never attach anyone to an existing Company.
- One self-service registration per person (User): a retry, a concurrent
  submission or another binding of the same person returns the same Company
  (``existing``) instead of a second one.
- A revoked binding, a suspended User or a revoked registered Membership is
  refused like any other denial.
- Nothing here verifies who legally owns a company: registration creates a
  workspace for the person who signed in, not a legal claim.

``heroos_identity_companies`` lists the caller's own active Memberships across
Companies, which RLS otherwise hides by design (workspace discovery).
"""

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.auth.exceptions import AuthorizationError
from app.auth.models import AuthenticatedCompanyContext, VerifiedIdentity
from app.db.models.membership import ROLE_COMPANY_ADMIN

CREATED: Final = "created"
EXISTING: Final = "existing"

# SQLSTATEs raised by heroos_register_company.
_REFUSED: Final = "42501"
_INVALID_NAME: Final = "22023"


class InvalidRegistration(ValueError):
    """The database refused the Company name (the API validates it first)."""


@dataclass(frozen=True, slots=True)
class FounderRegistration:
    outcome: str
    company_id: UUID
    user_id: UUID
    identity_id: UUID
    membership_id: UUID

    @property
    def created(self) -> bool:
        return self.outcome == CREATED

    @property
    def context(self) -> AuthenticatedCompanyContext:
        """The founder's trusted context in the registered Company.

        Every value comes from the row the database function wrote or found for
        this verified identity, exactly as a Membership lookup would produce it.
        """
        return AuthenticatedCompanyContext(
            user_id=self.user_id,
            company_id=self.company_id,
            membership_id=self.membership_id,
            identity_id=self.identity_id,
            role=ROLE_COMPANY_ADMIN,
        )


def _require_well_formed(identity: VerifiedIdentity) -> None:
    # Bound exactly as verified, never normalized (ADR-008); the database
    # function checks the same again.
    subject = identity.subject
    if not subject or subject != subject.strip() or not subject.isprintable():
        raise AuthorizationError("registration refused: malformed verified subject")


def register_founder_company(
    db: Session, identity: VerifiedIdentity, company_name: str
) -> FounderRegistration:
    """Register a new Company for ``identity``, or return its earlier registration.

    Runs in the caller's transaction and never commits: the caller commits once
    (together with any initial Blueprint answers), so everything is created
    together or not at all. On refusal the transaction is rolled back.
    """
    _require_well_formed(identity)
    try:
        row = db.execute(
            text(
                "SELECT outcome, company_id, user_id, identity_id, membership_id "
                "FROM public.heroos_register_company(:issuer, :subject, :name)"
            ),
            {"issuer": identity.issuer, "subject": identity.subject, "name": company_name},
        ).one()
    except DBAPIError as exc:
        state = getattr(exc.orig, "sqlstate", None)
        db.rollback()
        if state == _REFUSED:
            raise AuthorizationError(
                "registration refused: identity, User or registered Membership not active"
            ) from None
        if state == _INVALID_NAME:
            raise InvalidRegistration("company name refused") from None
        raise
    return FounderRegistration(
        outcome=row.outcome,
        company_id=row.company_id,
        user_id=row.user_id,
        identity_id=row.identity_id,
        membership_id=row.membership_id,
    )


@dataclass(frozen=True, slots=True)
class Workspace:
    company_id: UUID
    company_name: str
    membership_id: UUID
    role: str


def list_identity_companies(db: Session, identity: VerifiedIdentity) -> list[Workspace]:
    """The identity's active Memberships (active binding and User only)."""
    rows = db.execute(
        text(
            "SELECT company_id, company_name, membership_id, role "
            "FROM public.heroos_identity_companies(:issuer, :subject)"
        ),
        {"issuer": identity.issuer, "subject": identity.subject},
    ).all()
    return [
        Workspace(
            company_id=row.company_id,
            company_name=row.company_name,
            membership_id=row.membership_id,
            role=row.role,
        )
        for row in rows
    ]
