"""Jurisdiction readiness: may jurisdiction-specific guidance use this Company's context?

The single contract future workflows use before applying any jurisdiction-
dependent rule (M1-10C). It is deterministic and never infers a jurisdiction:

- The customer's licensing answer (DIFC / Other + authority / Not sure) is
  information. It establishes nothing on its own, whatever it says: HeroOS has
  no approved mapping from a licensing authority to an employment-law regime,
  so "Other" never means UAE Federal / MOHRE and "DIFC" never means DIFC law.
- A jurisdiction counts only when a trusted process confirmed it (the platform
  operator, ``confirm-jurisdiction``) and the customer's current licensing
  answer still equals the one it was confirmed against. Changing the answer
  withdraws the confirmation without anyone having to clear it.
- Only UAE Federal / MOHRE and DIFC are supported in V1. A confirmed ADGM or
  other jurisdiction is UNSUPPORTED: refused clearly, never guided.

``SUPPORTED_CONFIRMED`` is the only readiness that allows jurisdiction-specific
guidance (``guidance_allowed``). Registration and workspace access do not
depend on it. Company-level readiness is not Case-level applicability: a
workflow must still establish case-specific facts (for example where the
employee works) before applying a rule.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from app.db.models import CompanyBlueprint
from app.db.models.company_blueprint import (
    JURISDICTION_DIFC,
    JURISDICTION_UAE_FEDERAL,
    LICENSING_NOT_SURE,
    LICENSING_OTHER,
)
from app.repositories.company_blueprints import get_company_blueprint
from app.tenancy.scope import CompanyScope

# V1 scope (README, v1-system-architecture.md). Anything else is unsupported.
SUPPORTED_JURISDICTIONS: Final = frozenset({JURISDICTION_UAE_FEDERAL, JURISDICTION_DIFC})


class JurisdictionReadiness(StrEnum):
    SUPPORTED_CONFIRMED = "supported_confirmed"
    UNCONFIRMED = "unconfirmed"
    UNSUPPORTED = "unsupported"


class ReadinessReason(StrEnum):
    """Why the readiness is what it is; stable codes for the onboarding UI."""

    CONFIRMED = "confirmed"
    JURISDICTION_NOT_SUPPORTED = "jurisdiction_not_supported"
    LICENSING_NOT_PROVIDED = "licensing_not_provided"
    LICENSING_NOT_SURE = "licensing_not_sure"
    LICENSING_AUTHORITY_MISSING = "licensing_authority_missing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    LICENSING_CHANGED_SINCE_CONFIRMATION = "licensing_changed_since_confirmation"


@dataclass(frozen=True, slots=True)
class JurisdictionAssessment:
    readiness: JurisdictionReadiness
    reason: ReadinessReason
    # The confirmed jurisdiction, only while its confirmation is current.
    jurisdiction: str | None = None
    confirmed_at: datetime | None = None

    @property
    def guidance_allowed(self) -> bool:
        return self.readiness is JurisdictionReadiness.SUPPORTED_CONFIRMED


def assess_jurisdiction(blueprint: CompanyBlueprint | None) -> JurisdictionAssessment:
    """Readiness of one Company's Blueprint. Pure: reads only the given row."""
    unconfirmed = JurisdictionReadiness.UNCONFIRMED
    if blueprint is None:
        return JurisdictionAssessment(unconfirmed, ReadinessReason.LICENSING_NOT_PROVIDED)

    location = blueprint.licensing_location
    authority = blueprint.licensing_authority
    confirmed = blueprint.employment_jurisdiction
    if confirmed is not None:
        basis = (blueprint.confirmed_licensing_location, blueprint.confirmed_licensing_authority)
        if basis != (location, authority):
            # The answer the confirmation relied on is no longer the answer.
            return JurisdictionAssessment(
                unconfirmed, ReadinessReason.LICENSING_CHANGED_SINCE_CONFIRMATION
            )
        if confirmed in SUPPORTED_JURISDICTIONS:
            return JurisdictionAssessment(
                JurisdictionReadiness.SUPPORTED_CONFIRMED,
                ReadinessReason.CONFIRMED,
                confirmed,
                blueprint.jurisdiction_confirmed_at,
            )
        return JurisdictionAssessment(
            JurisdictionReadiness.UNSUPPORTED,
            ReadinessReason.JURISDICTION_NOT_SUPPORTED,
            confirmed,
            blueprint.jurisdiction_confirmed_at,
        )

    if location is None:
        return JurisdictionAssessment(unconfirmed, ReadinessReason.LICENSING_NOT_PROVIDED)
    if location == LICENSING_NOT_SURE:
        return JurisdictionAssessment(unconfirmed, ReadinessReason.LICENSING_NOT_SURE)
    if location == LICENSING_OTHER and authority is None:
        return JurisdictionAssessment(unconfirmed, ReadinessReason.LICENSING_AUTHORITY_MISSING)
    return JurisdictionAssessment(unconfirmed, ReadinessReason.AWAITING_CONFIRMATION)


def company_jurisdiction(scope: CompanyScope) -> JurisdictionAssessment:
    """Readiness of the scope's own Company."""
    return assess_jurisdiction(get_company_blueprint(scope))


class JurisdictionNotReady(Exception):
    """Jurisdiction-specific guidance must not run: block, clarify or escalate."""

    def __init__(self, assessment: JurisdictionAssessment) -> None:
        super().__init__(f"{assessment.readiness}: {assessment.reason}")
        self.assessment = assessment


def require_supported_jurisdiction(scope: CompanyScope) -> str:
    """The confirmed V1 jurisdiction of the scope's Company, or ``JurisdictionNotReady``.

    The gate for future jurisdiction-dependent workflow steps. There is no
    fallback: an unconfirmed or unsupported Company never gets a default regime.
    """
    assessment = company_jurisdiction(scope)
    if not assessment.guidance_allowed or assessment.jurisdiction is None:
        raise JurisdictionNotReady(assessment)
    return assessment.jurisdiction
