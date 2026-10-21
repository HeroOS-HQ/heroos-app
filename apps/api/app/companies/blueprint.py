"""The Company Blueprint as one canonical company context (M2-NEW-03).

The Blueprint is the company context HeroOS works with. Onboarding creates its
first answers (``app.api.onboarding``), the Blueprint page completes and
maintains them (``PATCH /companies/{id}/blueprint``), and HeroOS AI
(M2-NEW-05) reads them only through ``load_company_blueprint_context``: never
from database columns of its own choosing, and never by re-deriving what a
field means.

One writable source per field:

- **Company display name**: ``companies.name`` (set at registration). Projected
  here, never copied into the Blueprint.
- **Business profile and company context**: ``company_blueprints``, written by
  Company administrators: legal name, industry, number of employees, website,
  summary, whether HR policies exist and notes about them, how HR is handled
  and the primary contact.
- **Licensing answer**: ``company_blueprints.licensing_*`` (administrators).
- **Employment jurisdiction**: the platform operator's confirmation, read only
  through ``app.companies.jurisdiction`` (the API role cannot write it). HeroOS
  never infers it, and nothing here changes it.
- **People**: active Memberships of active Users. HeroOS holds no names or
  email addresses (ADR-008), so a person is their Membership, role and the
  date they joined; the current user is the authenticated Membership.

The website is stored only: nothing in HeroOS fetches, crawls or reads it.
Policy documents are not stored (retention undecided, PRIV-004): only whether
policies exist and short notes about them.

The context carries no credential, token, identity-provider subject or
issuer, binding id, audit field or infrastructure detail, and it is a domain
object, not a prompt.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import select

from app.auth.exceptions import AuthorizationError
from app.auth.models import AuthenticatedCompanyContext
from app.companies.jurisdiction import assess_jurisdiction
from app.db.models import CompanyBlueprint, Membership, User
from app.db.models.company_blueprint import (
    LICENSING_NOT_SURE,
    LICENSING_OTHER,
    MAX_WEBSITE_URL_LENGTH,
    POLICIES_NOT_SURE,
)
from app.db.models.membership import MEMBERSHIP_ACTIVE
from app.db.models.user import USER_ACTIVE
from app.repositories.companies import get_company
from app.repositories.company_blueprints import get_company_blueprint, update_company_blueprint
from app.tenancy.scope import CompanyScope

# --- shared validation (Blueprint update and founder registration) ---------------
# Fixed messages: a submitted value is never echoed.

WEBSITE_SCHEMES: Final = ("https", "http")
# A scheme as RFC 3986 spells it, at the very start.
_SCHEME: Final = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*):")
# A DNS label (letters, digits, inner hyphens) and a top-level domain that is
# alphabetic or an IDNA A-label: an IP address or a single-label host such as
# "localhost" is never a company website.
_LABEL: Final = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)")
_TOP_LABEL: Final = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}")
# Path, query and fragment: visible ASCII except the backslash (which browsers
# read as "/"). Anything else must be percent-encoded.
_REST: Final = re.compile(r"[!-\[\]-~]*")
_TEXT_LINE_CHARACTERS: Final = frozenset("\n\t")


def normalize_website_url(value: str) -> str:
    """The company website as HeroOS stores it, or ``ValueError``.

    ``http`` or ``https`` only (``https`` is assumed when no scheme is given);
    the scheme and host lowercased; a lone trailing "/" dropped. Refused: any
    other scheme (``javascript:``, ``data:``, ``file:``, ``mailto:``...),
    credentials, a port, an IP address or single-label host, spaces, control
    or non-ASCII characters, and anything longer than 500 characters once
    normalized. Mirrored by the web app (``normalizeWebsiteUrl``) with the
    shared cases in ``tests/fixtures/website_urls.json``.
    """
    text = value.strip()
    if text == "":
        raise ValueError("must not be empty")
    if not text.isascii() or any(not c.isprintable() or c.isspace() for c in text):
        raise ValueError("must be a web address without spaces or special characters")
    scheme = _SCHEME.match(text)
    if scheme is None:
        name, rest = WEBSITE_SCHEMES[0], text
    else:
        after = text[scheme.end() :]
        name = scheme.group(1).lower()
        if name not in WEBSITE_SCHEMES or not after.startswith("//"):
            raise ValueError("must be an http or https web address")
        rest = after[2:]
    end = next((index for index, c in enumerate(rest) if c in "/?#"), len(rest))
    host, remainder = rest[:end].lower(), rest[end:]
    labels = host.split(".")
    if (
        len(host) > 253
        or len(labels) < 2
        or not all(_LABEL.fullmatch(label) for label in labels)
        or not _TOP_LABEL.fullmatch(labels[-1])
    ):
        raise ValueError("must name a website domain, such as example.com")
    if not _REST.fullmatch(remainder):
        raise ValueError("must be a web address without spaces or special characters")
    url = f"{name}://{host}{'' if remainder == '/' else remainder}"
    if len(url) > MAX_WEBSITE_URL_LENGTH:
        raise ValueError("must be at most 500 characters")
    return url


def plain_text(value: str) -> str:
    """Free text stored exactly as sent: line breaks and tabs allowed, nothing else invisible."""
    if value.strip() == "":
        raise ValueError("must not be empty")
    if value != value.strip():
        raise ValueError("must not start or end with whitespace")
    if any(not c.isprintable() and c not in _TEXT_LINE_CHARACTERS for c in value):
        raise ValueError("must not contain control characters")
    return value


# --- the canonical context ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompanyPerson:
    """Someone with active access to the Company. No name or email: HeroOS keeps none."""

    membership_id: UUID
    user_id: UUID
    role: str
    member_since: datetime
    is_current_user: bool
    is_primary_contact: bool


@dataclass(frozen=True, slots=True)
class JurisdictionContext:
    """The Company's jurisdiction exactly as the deterministic workflows see it.

    ``employment_jurisdiction`` is present only while the operator's
    confirmation is current; ``guidance_allowed`` only for a supported one. The
    licensing answer is the customer's statement and establishes nothing.
    """

    readiness: str
    reason: str
    employment_jurisdiction: str | None
    confirmed_at: datetime | None
    guidance_allowed: bool
    licensing_location: str | None
    licensing_authority: str | None


@dataclass(frozen=True, slots=True)
class CompanyBlueprintContext:
    """The one company context future HeroOS AI consumes (M2-NEW-05).

    ``primary_contact`` is the Company's main contact; ``current_user`` is
    whoever is making this request. They may be different people.
    ``missing`` lists the details that need attention (``BLUEPRINT_DETAILS``).
    """

    company_id: UUID
    company_display_name: str
    legal_name: str | None
    industry: str | None
    employee_count: int | None
    website_url: str | None
    company_summary: str | None
    jurisdiction: JurisdictionContext
    policies_exist: str | None
    policy_context: str | None
    hr_support: str | None
    hr_support_notes: str | None
    primary_contact: CompanyPerson | None
    current_user: CompanyPerson
    updated_at: datetime | None
    missing: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing


@dataclass(frozen=True, slots=True)
class CompanyBlueprintView:
    """The context plus everyone with access (the Blueprint page's contact choices)."""

    context: CompanyBlueprintContext
    people: tuple[CompanyPerson, ...]


# Details HeroOS relies on, in page order. The website, policy notes and HR
# notes are optional context and never "need attention".
BLUEPRINT_DETAILS: Final = (
    "legal_name",
    "industry",
    "employee_count",
    "company_summary",
    "jurisdiction",
    "policies",
    "hr_support",
    "primary_contact",
)


def missing_details(
    blueprint: CompanyBlueprint, primary_contact: CompanyPerson | None
) -> tuple[str, ...]:
    """What still needs attention: subtle completeness, never a score."""
    location = blueprint.licensing_location
    missing = {
        "legal_name": blueprint.legal_name is None,
        "industry": blueprint.industry is None,
        "employee_count": blueprint.employee_count is None,
        "company_summary": blueprint.company_summary is None,
        "jurisdiction": location is None
        or location == LICENSING_NOT_SURE
        or (location == LICENSING_OTHER and blueprint.licensing_authority is None),
        "policies": blueprint.policies_exist is None
        or blueprint.policies_exist == POLICIES_NOT_SURE,
        "hr_support": blueprint.hr_support is None,
        "primary_contact": primary_contact is None,
    }
    return tuple(detail for detail in BLUEPRINT_DETAILS if missing[detail])


def company_people(
    scope: CompanyScope, *, current_membership_id: UUID, primary_contact_id: UUID | None
) -> tuple[CompanyPerson, ...]:
    """Active Memberships of active Users in the scope's Company, oldest first.

    Revoked Memberships and suspended Users are left out (RLS hides them from
    the API role too).
    """
    rows = scope.session.execute(
        select(Membership.id, Membership.user_id, Membership.role, Membership.created_at)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.company_id == scope.company_id,
            Membership.status == MEMBERSHIP_ACTIVE,
            User.status == USER_ACTIVE,
        )
        .order_by(Membership.created_at, Membership.id)
    ).all()
    return tuple(
        CompanyPerson(
            membership_id=row.id,
            user_id=row.user_id,
            role=row.role,
            member_since=row.created_at,
            is_current_user=row.id == current_membership_id,
            is_primary_contact=row.id == primary_contact_id,
        )
        for row in rows
    )


def load_company_blueprint(
    scope: CompanyScope, context: AuthenticatedCompanyContext
) -> CompanyBlueprintView:
    """The scope Company's Blueprint as seen by ``context``'s user.

    Raises ``AuthorizationError`` if the caller's own Membership is no longer
    active (revoked since the request was authorized).
    """
    company = get_company(scope)
    if company is None:
        raise AuthorizationError("company not visible in its own scope")
    stored = get_company_blueprint(scope)
    # A Company without a Blueprint row reads as an empty one (never added to the session).
    blueprint = stored if stored is not None else CompanyBlueprint(company_id=company.id)
    people = company_people(
        scope,
        current_membership_id=context.membership_id,
        primary_contact_id=blueprint.primary_contact_membership_id,
    )
    current = next((person for person in people if person.is_current_user), None)
    if current is None:
        raise AuthorizationError("membership no longer active")
    primary = next((person for person in people if person.is_primary_contact), None)
    assessment = assess_jurisdiction(stored)
    return CompanyBlueprintView(
        context=CompanyBlueprintContext(
            company_id=company.id,
            company_display_name=company.name,
            legal_name=blueprint.legal_name,
            industry=blueprint.industry,
            employee_count=blueprint.employee_count,
            website_url=blueprint.website_url,
            company_summary=blueprint.company_summary,
            jurisdiction=JurisdictionContext(
                readiness=assessment.readiness.value,
                reason=assessment.reason.value,
                employment_jurisdiction=assessment.jurisdiction,
                confirmed_at=assessment.confirmed_at,
                guidance_allowed=assessment.guidance_allowed,
                licensing_location=blueprint.licensing_location,
                licensing_authority=blueprint.licensing_authority,
            ),
            policies_exist=blueprint.policies_exist,
            policy_context=blueprint.policy_context,
            hr_support=blueprint.hr_support,
            hr_support_notes=blueprint.hr_support_notes,
            primary_contact=primary,
            current_user=current,
            updated_at=None if stored is None else stored.updated_at,
            missing=missing_details(blueprint, primary),
        ),
        people=people,
    )


def load_company_blueprint_context(
    scope: CompanyScope, context: AuthenticatedCompanyContext
) -> CompanyBlueprintContext:
    """The canonical company context for HeroOS (M2-NEW-05 reads this, nothing else)."""
    return load_company_blueprint(scope, context).context


# --- the one write path --------------------------------------------------------------


class InvalidPrimaryContact(ValueError):
    """The primary contact is not an active Membership of this Company.

    Identical for another Company's Membership, a revoked one and an id that
    exists nowhere: nothing about other Companies is disclosed.
    """


def is_company_member(scope: CompanyScope, membership_id: UUID) -> bool:
    """An active Membership of an active User in the scope's Company (this transaction)."""
    found = scope.session.scalar(
        select(Membership.id)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.id == membership_id,
            Membership.company_id == scope.company_id,
            Membership.status == MEMBERSHIP_ACTIVE,
            User.status == USER_ACTIVE,
        )
    )
    return found is not None


def save_blueprint_changes(scope: CompanyScope, changes: Mapping[str, object]) -> CompanyBlueprint:
    """Apply validated Blueprint changes: the only way onboarding and the Blueprint page write.

    A new primary contact must be an active Membership of the same Company
    (``InvalidPrimaryContact`` otherwise; the database's Company-qualified
    foreign key refuses another Company's Membership again). ``None`` clears it.
    """
    contact = changes.get("primary_contact_membership_id")
    if contact is not None and (
        not isinstance(contact, UUID) or not is_company_member(scope, contact)
    ):
        raise InvalidPrimaryContact("primary contact is not a member of this company")
    return update_company_blueprint(scope, changes)
