"""Jurisdiction readiness (M1-10C): the deterministic contract, without a database.

Proves the safety rules future workflows depend on: a licensing answer alone
never establishes a jurisdiction (no Federal / MOHRE catch-all, no automatic
DIFC), "not sure" and missing answers stay unresolved, a confirmation counts
only for the answer it was made against, and ADGM or any other confirmed
jurisdiction is unsupported. Real PostgreSQL behaviour is in
tests/tenant_isolation/test_company_blueprint.py.
"""

from datetime import UTC, datetime
from itertools import product
from uuid import uuid4

import pytest

from app.companies.jurisdiction import (
    SUPPORTED_JURISDICTIONS,
    JurisdictionNotReady,
    JurisdictionReadiness,
    ReadinessReason,
    assess_jurisdiction,
    require_supported_jurisdiction,
)
from app.db.models import CompanyBlueprint
from app.tenancy.scope import CompanyScope

CONFIRMED_AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
UNCONFIRMED = JurisdictionReadiness.UNCONFIRMED


def blueprint(
    location: str | None = None,
    authority: str | None = None,
    *,
    jurisdiction: str | None = None,
    confirmed_location: str | None = None,
    confirmed_authority: str | None = None,
    legacy_primary_jurisdiction: str | None = None,
) -> CompanyBlueprint:
    return CompanyBlueprint(
        company_id=uuid4(),
        primary_jurisdiction=legacy_primary_jurisdiction,
        licensing_location=location,
        licensing_authority=authority,
        employment_jurisdiction=jurisdiction,
        confirmed_licensing_location=confirmed_location,
        confirmed_licensing_authority=confirmed_authority,
        jurisdiction_confirmed_at=None if jurisdiction is None else CONFIRMED_AT,
    )


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        pytest.param(None, ReadinessReason.LICENSING_NOT_PROVIDED, id="no-blueprint"),
        pytest.param(blueprint(), ReadinessReason.LICENSING_NOT_PROVIDED, id="no-answer"),
        pytest.param(blueprint("not_sure"), ReadinessReason.LICENSING_NOT_SURE, id="not-sure"),
        pytest.param(
            blueprint("other"), ReadinessReason.LICENSING_AUTHORITY_MISSING, id="other-no-authority"
        ),
        pytest.param(
            blueprint("other", "Jebel Ali Free Zone Authority"),
            ReadinessReason.AWAITING_CONFIRMATION,
            id="other-with-authority",
        ),
        pytest.param(blueprint("difc"), ReadinessReason.AWAITING_CONFIRMATION, id="difc"),
        pytest.param(
            blueprint(legacy_primary_jurisdiction="DIFC"),
            ReadinessReason.LICENSING_NOT_PROVIDED,
            id="legacy-label-only",
        ),
        pytest.param(
            blueprint("difc", legacy_primary_jurisdiction="UAE Federal"),
            ReadinessReason.AWAITING_CONFIRMATION,
            id="legacy-label-and-answer",
        ),
    ],
)
def test_answers_without_a_confirmation_stay_unconfirmed(
    row: CompanyBlueprint | None, reason: ReadinessReason
) -> None:
    assessment = assess_jurisdiction(row)

    assert (assessment.readiness, assessment.reason) == (UNCONFIRMED, reason)
    # Never a default regime: no jurisdiction, no guidance.
    assert assessment.jurisdiction is None
    assert assessment.confirmed_at is None
    assert assessment.guidance_allowed is False


@pytest.mark.parametrize("jurisdiction", sorted(SUPPORTED_JURISDICTIONS))
@pytest.mark.parametrize(
    ("location", "authority"), [("difc", None), ("other", "Dubai Department of Economy")]
)
def test_a_current_confirmation_of_a_v1_jurisdiction_allows_guidance(
    jurisdiction: str, location: str, authority: str | None
) -> None:
    row = blueprint(
        location,
        authority,
        jurisdiction=jurisdiction,
        confirmed_location=location,
        confirmed_authority=authority,
    )
    assessment = assess_jurisdiction(row)

    assert assessment.readiness is JurisdictionReadiness.SUPPORTED_CONFIRMED
    assert assessment.reason is ReadinessReason.CONFIRMED
    assert (assessment.jurisdiction, assessment.confirmed_at) == (jurisdiction, CONFIRMED_AT)
    assert assessment.guidance_allowed is True


@pytest.mark.parametrize("jurisdiction", ["adgm", "other", "something-unexpected"])
def test_confirmed_jurisdictions_outside_v1_are_unsupported(jurisdiction: str) -> None:
    row = blueprint(
        "other",
        "Abu Dhabi Global Market",
        jurisdiction=jurisdiction,
        confirmed_location="other",
        confirmed_authority="Abu Dhabi Global Market",
    )
    assessment = assess_jurisdiction(row)

    assert assessment.readiness is JurisdictionReadiness.UNSUPPORTED
    assert assessment.reason is ReadinessReason.JURISDICTION_NOT_SUPPORTED
    assert assessment.jurisdiction == jurisdiction
    assert assessment.guidance_allowed is False


@pytest.mark.parametrize(
    ("location", "authority"),
    [
        (None, None),
        ("not_sure", None),
        ("other", None),
        ("other", "Jebel Ali Free Zone Authority"),
        ("other", "Dubai Department of Economy "),
    ],
)
def test_changing_the_licensing_answer_withdraws_the_confirmation(
    location: str | None, authority: str | None
) -> None:
    # Confirmed DIFC against "Other / Dubai Department of Economy"; the answer
    # is now different in some way.
    row = blueprint(
        location,
        authority,
        jurisdiction="difc",
        confirmed_location="other",
        confirmed_authority="Dubai Department of Economy",
    )
    assessment = assess_jurisdiction(row)

    assert (assessment.readiness, assessment.reason) == (
        UNCONFIRMED,
        ReadinessReason.LICENSING_CHANGED_SINCE_CONFIRMATION,
    )
    assert assessment.jurisdiction is None
    assert assessment.guidance_allowed is False


def test_only_supported_confirmed_ever_allows_guidance() -> None:
    # Exhaustive over every stored combination: guidance iff a current
    # confirmation of UAE Federal or DIFC.
    locations = (None, "difc", "other", "not_sure")
    authorities = (None, "Authority X")
    jurisdictions = (None, "uae_federal", "difc", "adgm", "other")
    for location, authority, jurisdiction, basis_location, basis_authority in product(
        locations, authorities, jurisdictions, locations, authorities
    ):
        row = blueprint(
            location,
            authority,
            jurisdiction=jurisdiction,
            confirmed_location=None if jurisdiction is None else basis_location,
            confirmed_authority=None if jurisdiction is None else basis_authority,
        )
        current = jurisdiction is not None and (basis_location, basis_authority) == (
            location,
            authority,
        )
        expected = current and jurisdiction in SUPPORTED_JURISDICTIONS
        assert assess_jurisdiction(row).guidance_allowed is expected, (
            location,
            authority,
            jurisdiction,
            basis_location,
            basis_authority,
        )


def test_supported_v1_scope_is_uae_federal_and_difc_only() -> None:
    assert frozenset({"uae_federal", "difc"}) == SUPPORTED_JURISDICTIONS


class _FakeScope:
    """Just enough of a CompanyScope for the gate (the repository is replaced)."""


@pytest.mark.parametrize(
    "row",
    [
        None,
        blueprint("difc"),
        blueprint(
            "other", "X", jurisdiction="adgm", confirmed_location="other", confirmed_authority="X"
        ),
    ],
)
def test_the_workflow_gate_refuses_anything_but_supported_confirmed(
    monkeypatch: pytest.MonkeyPatch, row: CompanyBlueprint | None
) -> None:
    monkeypatch.setattr("app.companies.jurisdiction.get_company_blueprint", lambda _scope: row)
    scope = CompanyScope(session=_FakeScope(), company_id=uuid4())  # type: ignore[arg-type]

    with pytest.raises(JurisdictionNotReady) as exc_info:
        require_supported_jurisdiction(scope)
    assert exc_info.value.assessment.guidance_allowed is False


def test_the_workflow_gate_returns_the_confirmed_jurisdiction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = blueprint("difc", jurisdiction="difc", confirmed_location="difc")
    monkeypatch.setattr("app.companies.jurisdiction.get_company_blueprint", lambda _scope: row)
    scope = CompanyScope(session=_FakeScope(), company_id=uuid4())  # type: ignore[arg-type]

    assert require_supported_jurisdiction(scope) == "difc"
