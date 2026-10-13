"""Company registration and jurisdiction confirmation for platform operators (M1-10C).

Trusted operations, used only by ``scripts/manage_identities.py`` with an
identity-operator database login; no HTTP route reaches them. Like
``app.identity.service``, each function runs inside the caller's transaction and
never commits: the CLI sets the change reference first and commits once, so a
Company, its Blueprint, its first administrator and their audit events exist
together or not at all.

The database enforces the same boundaries for the operator role: it may insert
a Company's id and name (not read the name back), an empty Blueprint, and write
only the jurisdiction confirmation columns, all under the tenant policy (one
Company per transaction). It still cannot read the business profile or any HR
data.
"""

from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.orm import Session

from app.companies.jurisdiction import assess_jurisdiction
from app.db.models import Company, CompanyBlueprint, Membership, User, UserIdentity
from app.db.models.company_blueprint import (
    EMPLOYMENT_JURISDICTIONS,
    LICENSING_DIFC,
    LICENSING_OTHER,
)
from app.db.models.membership import MEMBERSHIP_ACTIVE, ROLE_COMPANY_ADMIN
from app.db.models.user import USER_ACTIVE
from app.db.models.user_identity import IDENTITY_ACTIVE
from app.identity import errors
from app.identity.errors import IdentityOperationError
from app.identity.operator import open_operator_company_scope
from app.identity.service import (
    CREATED,
    UNCHANGED,
    UPDATED,
    OperationResult,
    _identity_by_key,
    _membership_for_user,
    _require_active_user,
)
from app.identity.validation import (
    validate_choice,
    validate_company_name,
    validate_issuer,
    validate_licensing_authority,
    validate_subject,
)
from app.tenancy.context import TenantContextError, set_tenant_context

_COMPANIES = Company.metadata.tables["companies"]
_BLUEPRINTS = CompanyBlueprint.metadata.tables["company_blueprints"]


def _company_exists(session: Session, company_id: UUID) -> bool:
    # Column-level SELECT (id) under the tenant policy already in context.
    found = session.scalar(text("SELECT id FROM companies WHERE id = :id"), {"id": company_id})
    return found is not None


def _is_current_admin(
    session: Session, company_id: UUID, identity: UserIdentity
) -> Membership | None:
    """The identity's active administrator Membership of the Company, if any."""
    user = session.get(User, identity.user_id)
    membership = _membership_for_user(session, company_id, identity.user_id)
    if (
        membership is not None
        and membership.status == MEMBERSHIP_ACTIVE
        and membership.role == ROLE_COMPANY_ADMIN
        and identity.status == IDENTITY_ACTIVE
        and user is not None
        and user.status == USER_ACTIVE
    ):
        return membership
    return None


def register_company(
    session: Session,
    *,
    company_id: UUID,
    name: str,
    issuer: str,
    subject: str,
    existing_user: bool = False,
) -> OperationResult:
    """Create a Company, its empty Blueprint and its first Company administrator.

    The operator chooses ``company_id`` once (recorded in the change issue) and
    re-uses it on every retry, so the stable UUID makes registration
    idempotent: a retry after success reports ``unchanged`` when exactly this
    identity is already the Company's active administrator, and is refused
    (``company_exists``) otherwise. Nothing here relies on the name; names are
    not unique and never establish ownership.

    The administrator is the external identity the operator verified out of
    band (subject on standard input), never something a browser claimed:

    - ``existing_user=False``: a person new to HeroOS. Refused
      (``identity_exists_use_grant``) if the identity is already bound, so a typo
      can never merge two people.
    - ``existing_user=True``: an active User found by an active binding (for
      example a founder registering a second Company).
    """
    name = validate_company_name(name)
    issuer = validate_issuer(issuer)
    subject = validate_subject(subject)
    try:
        # Validates the UUID (never nil) and binds this transaction to it.
        set_tenant_context(session, company_id)
    except TenantContextError:
        raise IdentityOperationError(errors.INVALID_INPUT) from None

    identity = _identity_by_key(session, issuer, subject)
    if _company_exists(session, company_id):
        current = None if identity is None else _is_current_admin(session, company_id, identity)
        if identity is None or current is None:
            raise IdentityOperationError(errors.COMPANY_EXISTS)
        return OperationResult(
            UNCHANGED,
            {
                "company_id": company_id,
                "user_id": identity.user_id,
                "identity_id": identity.id,
                "membership_id": current.id,
            },
        )

    if existing_user:
        if identity is None:
            raise IdentityOperationError(errors.IDENTITY_NOT_FOUND)
        if identity.status != IDENTITY_ACTIVE:
            raise IdentityOperationError(errors.IDENTITY_REVOKED)
        user_id = _require_active_user(session, identity.user_id).id
    else:
        if identity is not None:
            raise IdentityOperationError(errors.IDENTITY_EXISTS)
        user = User()
        session.add(user)
        session.flush()
        identity = UserIdentity(user_id=user.id, issuer=issuer, subject=subject)
        session.add(identity)
        session.flush()
        user_id = user.id

    # Core inserts without RETURNING: the operator may insert these columns but
    # not read the Company's name or the Blueprint's other columns back.
    session.execute(insert(_COMPANIES).values(id=company_id, name=name))
    blueprint_id = uuid4()
    session.execute(insert(_BLUEPRINTS).values(id=blueprint_id, company_id=company_id))
    membership = Membership(company_id=company_id, user_id=user_id, role=ROLE_COMPANY_ADMIN)
    session.add(membership)
    session.flush()
    return OperationResult(
        CREATED,
        {
            "company_id": company_id,
            "blueprint_id": blueprint_id,
            "user_id": user_id,
            "identity_id": identity.id,
            "membership_id": membership.id,
        },
    )


# --- jurisdiction confirmation ---------------------------------------------------

_CONFIRMATION_FACTS = (
    _BLUEPRINTS.c.licensing_location,
    _BLUEPRINTS.c.licensing_authority,
    _BLUEPRINTS.c.employment_jurisdiction,
    _BLUEPRINTS.c.confirmed_licensing_location,
    _BLUEPRINTS.c.confirmed_licensing_authority,
    _BLUEPRINTS.c.jurisdiction_confirmed_at,
)


def _confirmation_facts(session: Session, company_id: UUID) -> CompanyBlueprint:
    """The licensing answer and confirmation only (no business profile).

    Returned as a transient, never-added ``CompanyBlueprint`` so the same
    ``assess_jurisdiction`` contract applies.
    """
    row = session.execute(
        select(*_CONFIRMATION_FACTS).where(_BLUEPRINTS.c.company_id == company_id)
    ).one_or_none()
    if row is None:
        raise IdentityOperationError(errors.BLUEPRINT_NOT_FOUND)
    return CompanyBlueprint(company_id=company_id, **row._asdict())


def _readiness_details(facts: CompanyBlueprint) -> dict[str, str | None]:
    assessment = assess_jurisdiction(facts)
    return {
        "readiness": assessment.readiness.value,
        "reason": assessment.reason.value,
        "employment_jurisdiction": assessment.jurisdiction,
    }


def jurisdiction_status(session: Session, *, company_id: UUID) -> OperationResult:
    """Read-only: the customer's licensing answer and the current readiness."""
    open_operator_company_scope(session, company_id)
    facts = _confirmation_facts(session, company_id)
    return OperationResult(
        UNCHANGED,
        {"company_id": company_id},
        {
            "licensing_location": facts.licensing_location,
            "licensing_authority": facts.licensing_authority,
            **_readiness_details(facts),
        },
    )


def confirm_jurisdiction(
    session: Session,
    *,
    company_id: UUID,
    jurisdiction: str,
    licensing_location: str,
    licensing_authority: str | None,
) -> OperationResult:
    """Record the Company-level employment jurisdiction a trusted review established.

    The operator states the licensing answer they reviewed. It must be a
    definite answer (DIFC, or Other with its authority; never "not sure" or
    missing) and must equal the customer's current answer, which is stored with
    the confirmation. If the customer later changes the answer, readiness falls
    back to unconfirmed by itself (``app.companies.jurisdiction``).

    Which evidence justifies a confirmation is a business and legal rule that
    JJ has not approved yet; this records the decision, it does not make it.
    """
    jurisdiction = validate_choice(jurisdiction, EMPLOYMENT_JURISDICTIONS)
    if licensing_location not in (LICENSING_DIFC, LICENSING_OTHER):
        raise IdentityOperationError(errors.LICENSING_UNRESOLVED)
    if licensing_location == LICENSING_OTHER:
        if licensing_authority is None:
            raise IdentityOperationError(errors.LICENSING_UNRESOLVED)
        licensing_authority = validate_licensing_authority(licensing_authority)
    elif licensing_authority is not None:
        raise IdentityOperationError(errors.INVALID_INPUT)

    open_operator_company_scope(session, company_id)
    facts = _confirmation_facts(session, company_id)
    reviewed = (licensing_location, licensing_authority)
    if (facts.licensing_location, facts.licensing_authority) != reviewed:
        raise IdentityOperationError(errors.LICENSING_MISMATCH)
    if (
        facts.employment_jurisdiction == jurisdiction
        and (facts.confirmed_licensing_location, facts.confirmed_licensing_authority) == reviewed
    ):
        return OperationResult(UNCHANGED, {"company_id": company_id}, _readiness_details(facts))

    session.execute(
        update(_BLUEPRINTS)
        .where(_BLUEPRINTS.c.company_id == company_id)
        .values(
            employment_jurisdiction=jurisdiction,
            confirmed_licensing_location=licensing_location,
            confirmed_licensing_authority=licensing_authority,
            jurisdiction_confirmed_at=func.now(),
            updated_at=func.now(),
        )
    )
    return OperationResult(
        UPDATED,
        {"company_id": company_id},
        _readiness_details(_confirmation_facts(session, company_id)),
    )


def clear_jurisdiction(session: Session, *, company_id: UUID) -> OperationResult:
    """Withdraw a confirmation (for example one made in error). Audited."""
    open_operator_company_scope(session, company_id)
    facts = _confirmation_facts(session, company_id)
    if facts.employment_jurisdiction is None:
        return OperationResult(UNCHANGED, {"company_id": company_id}, _readiness_details(facts))
    session.execute(
        update(_BLUEPRINTS)
        .where(_BLUEPRINTS.c.company_id == company_id)
        .values(
            employment_jurisdiction=None,
            confirmed_licensing_location=None,
            confirmed_licensing_authority=None,
            jurisdiction_confirmed_at=None,
            updated_at=func.now(),
        )
    )
    return OperationResult(
        UPDATED,
        {"company_id": company_id},
        _readiness_details(_confirmation_facts(session, company_id)),
    )
