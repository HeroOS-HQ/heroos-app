"""Company Blueprint licensing and jurisdiction readiness on PostgreSQL (M1-10C).

The customer's licensing answer is written as the API runtime role (Company
repositories, RLS); the trusted confirmation as the identity-operator role
(``app.identity.companies``). Readiness is then read back as the runtime role,
exactly as a future workflow would.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.companies.jurisdiction import (
    JurisdictionNotReady,
    JurisdictionReadiness,
    ReadinessReason,
    company_jurisdiction,
    require_supported_jurisdiction,
)
from app.identity import companies, errors, service
from app.identity.errors import IdentityOperationError
from app.identity.operator import set_actor_reference
from app.repositories.company_blueprints import update_company_blueprint
from tests.tenant_isolation.conftest import TEST_REFERENCE, Tenant, Tenants, scope_for

JAFZA = "Jebel Ali Free Zone Authority"
CONFIRM_REFERENCE = "HER-233"


@contextmanager
def operator_tx(engine: Engine) -> Iterator[Session]:
    with Session(engine, autoflush=False) as session:
        set_actor_reference(session, CONFIRM_REFERENCE)
        yield session
        session.commit()


def answer(
    runtime_engine: Engine, tenant: Tenant, location: str | None, authority: str | None = None
) -> None:
    """The administrator's licensing answer, as the API writes it."""
    with Session(runtime_engine, autoflush=False) as session:
        scope = scope_for(session, tenant)
        update_company_blueprint(
            scope, {"licensing_location": location, "licensing_authority": authority}
        )
        session.commit()


def confirm(
    operator_engine: Engine,
    tenant: Tenant,
    jurisdiction: str,
    location: str,
    authority: str | None = None,
) -> service.OperationResult:
    with operator_tx(operator_engine) as session:
        return companies.confirm_jurisdiction(
            session,
            company_id=tenant.company,
            jurisdiction=jurisdiction,
            licensing_location=location,
            licensing_authority=authority,
        )


def readiness(runtime_engine: Engine, tenant: Tenant) -> tuple[str, str, str | None]:
    with Session(runtime_engine) as session:
        assessment = company_jurisdiction(scope_for(session, tenant))
    return assessment.readiness.value, assessment.reason.value, assessment.jurisdiction


def company_events(admin_engine: Engine, company: uuid.UUID) -> list[tuple[Any, ...]]:
    with admin_engine.connect() as conn:
        return [
            tuple(row)
            for row in conn.execute(
                text(
                    "SELECT event_type, jurisdiction, actor_kind, actor_reference "
                    "FROM company_events WHERE company_id = :c ORDER BY occurred_at, id"
                ),
                {"c": company},
            )
        ]


def test_seeded_blueprints_start_unconfirmed_despite_legacy_labels(
    runtime_engine: Engine, tenants: Tenants
) -> None:
    # The fixture's Blueprints carry the legacy primary_jurisdiction "DIFC":
    # a label, never a confirmation.
    for tenant in (tenants.a, tenants.b):
        assert readiness(runtime_engine, tenant) == ("unconfirmed", "licensing_not_provided", None)


@pytest.mark.parametrize(
    ("location", "authority", "reason"),
    [
        ("difc", None, "awaiting_confirmation"),
        ("other", JAFZA, "awaiting_confirmation"),
        ("other", None, "licensing_authority_missing"),
        ("not_sure", None, "licensing_not_sure"),
    ],
)
def test_licensing_answers_alone_never_resolve_a_jurisdiction(
    runtime_engine: Engine, tenants: Tenants, location: str, authority: str | None, reason: str
) -> None:
    answer(runtime_engine, tenants.a, location, authority)

    # No Federal / MOHRE catch-all for "Other", no automatic DIFC for "DIFC".
    assert readiness(runtime_engine, tenants.a) == ("unconfirmed", reason, None)
    with Session(runtime_engine) as session, pytest.raises(JurisdictionNotReady):
        require_supported_jurisdiction(scope_for(session, tenants.a))


@pytest.mark.parametrize(
    ("jurisdiction", "location", "authority", "expected"),
    [
        ("difc", "difc", None, "supported_confirmed"),
        ("uae_federal", "other", "Dubai Department of Economy and Tourism", "supported_confirmed"),
        ("adgm", "other", "Abu Dhabi Global Market", "unsupported"),
        ("other", "other", "Saudi Ministry of Investment", "unsupported"),
    ],
)
def test_operator_confirmation_establishes_readiness(
    runtime_engine: Engine,
    operator_engine: Engine,
    admin_engine: Engine,
    tenants: Tenants,
    jurisdiction: str,
    location: str,
    authority: str | None,
    expected: str,
) -> None:
    answer(runtime_engine, tenants.a, location, authority)
    result = confirm(operator_engine, tenants.a, jurisdiction, location, authority)

    assert result.outcome == service.UPDATED
    assert result.details["readiness"] == expected
    reason = "confirmed" if expected == "supported_confirmed" else "jurisdiction_not_supported"
    assert readiness(runtime_engine, tenants.a) == (expected, reason, jurisdiction)
    with Session(runtime_engine) as session:
        scope = scope_for(session, tenants.a)
        if expected == "supported_confirmed":
            assert require_supported_jurisdiction(scope) == jurisdiction
        else:
            with pytest.raises(JurisdictionNotReady) as exc_info:
                require_supported_jurisdiction(scope)
            assert exc_info.value.assessment.readiness is JurisdictionReadiness.UNSUPPORTED
    # Company B is untouched.
    assert readiness(runtime_engine, tenants.b)[0] == "unconfirmed"
    # Audited with the operator login and reference; no customer text copied.
    assert company_events(admin_engine, tenants.a.company)[-1] == (
        "jurisdiction_confirmed",
        jurisdiction,
        "operator",
        CONFIRM_REFERENCE,
    )

    # Repeating the confirmation writes nothing.
    count = len(company_events(admin_engine, tenants.a.company))
    assert confirm(operator_engine, tenants.a, jurisdiction, location, authority).outcome == (
        service.UNCHANGED
    )
    assert len(company_events(admin_engine, tenants.a.company)) == count


def test_changing_the_answer_withdraws_the_confirmation_until_reconfirmed(
    runtime_engine: Engine, operator_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    answer(runtime_engine, tenants.a, "difc")
    confirm(operator_engine, tenants.a, "difc", "difc")
    assert readiness(runtime_engine, tenants.a)[0] == "supported_confirmed"

    # The administrator changes the licensing answer: guidance stops at once,
    # without the API role touching (or being able to touch) the confirmation.
    answer(runtime_engine, tenants.a, "other", JAFZA)
    assert readiness(runtime_engine, tenants.a) == (
        "unconfirmed",
        ReadinessReason.LICENSING_CHANGED_SINCE_CONFIRMATION.value,
        None,
    )
    with admin_engine.connect() as conn:
        stored = conn.execute(
            text(
                "SELECT employment_jurisdiction, confirmed_licensing_location "
                "FROM company_blueprints WHERE company_id = :c"
            ),
            {"c": tenants.a.company},
        ).one()
    assert tuple(stored) == ("difc", "difc")

    # Confirming what was not reviewed is refused; confirming the new answer works.
    with pytest.raises(IdentityOperationError) as exc_info:
        confirm(operator_engine, tenants.a, "difc", "difc")
    assert exc_info.value.code == errors.LICENSING_MISMATCH
    confirm(operator_engine, tenants.a, "uae_federal", "other", JAFZA)
    assert readiness(runtime_engine, tenants.a) == (
        "supported_confirmed",
        "confirmed",
        "uae_federal",
    )

    # Withdrawing a confirmation is audited as well.
    with operator_tx(operator_engine) as session:
        cleared = companies.clear_jurisdiction(session, company_id=tenants.a.company)
    assert cleared.outcome == service.UPDATED
    assert readiness(runtime_engine, tenants.a) == ("unconfirmed", "awaiting_confirmation", None)
    assert [event[0] for event in company_events(admin_engine, tenants.a.company)] == [
        "company_registered",
        "jurisdiction_confirmed",
        "jurisdiction_confirmed",
        "jurisdiction_cleared",
    ]


@pytest.mark.parametrize(
    ("stored", "reviewed", "code"),
    [
        pytest.param((None, None), ("difc", None), errors.LICENSING_MISMATCH, id="no-answer"),
        pytest.param(("not_sure", None), ("difc", None), errors.LICENSING_MISMATCH, id="not-sure"),
        pytest.param(
            ("difc", None), ("not_sure", None), errors.LICENSING_UNRESOLVED, id="reviewed-unsure"
        ),
        pytest.param(
            ("other", None), ("other", None), errors.LICENSING_UNRESOLVED, id="no-authority"
        ),
        pytest.param(
            ("other", JAFZA), ("other", "JAFZA"), errors.LICENSING_MISMATCH, id="other-name"
        ),
        pytest.param(("difc", None), ("difc", "DIFC"), errors.INVALID_INPUT, id="authority-difc"),
        pytest.param(("other", JAFZA), ("other", f" {JAFZA}"), errors.INVALID_INPUT, id="padded"),
    ],
)
def test_confirmation_needs_a_definite_matching_answer(
    runtime_engine: Engine,
    operator_engine: Engine,
    admin_engine: Engine,
    tenants: Tenants,
    stored: tuple[str | None, str | None],
    reviewed: tuple[str, str | None],
    code: str,
) -> None:
    answer(runtime_engine, tenants.a, *stored)
    with pytest.raises(IdentityOperationError) as exc_info:
        confirm(operator_engine, tenants.a, "difc", *reviewed)

    assert exc_info.value.code == code
    assert readiness(runtime_engine, tenants.a)[0] == "unconfirmed"
    assert [e[0] for e in company_events(admin_engine, tenants.a.company)] == ["company_registered"]


def test_confirmation_refuses_unknown_jurisdictions_and_missing_rows(
    runtime_engine: Engine, operator_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    answer(runtime_engine, tenants.a, "difc")
    for jurisdiction in ("DIFC", "mohre", "", "uae"):
        with pytest.raises(IdentityOperationError) as exc_info:
            confirm(operator_engine, tenants.a, jurisdiction, "difc")
        assert exc_info.value.code == errors.INVALID_INPUT

    with pytest.raises(IdentityOperationError) as exc_info, operator_tx(operator_engine) as session:
        companies.confirm_jurisdiction(
            session,
            company_id=uuid.uuid4(),
            jurisdiction="difc",
            licensing_location="difc",
            licensing_authority=None,
        )
    assert exc_info.value.code == errors.COMPANY_NOT_FOUND

    with admin_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM company_blueprints WHERE company_id = :c"), {"c": tenants.b.company}
        )
    with pytest.raises(IdentityOperationError) as exc_info:
        confirm(operator_engine, tenants.b, "difc", "difc")
    assert exc_info.value.code == errors.BLUEPRINT_NOT_FOUND


def test_operator_status_reads_only_licensing_and_readiness(
    runtime_engine: Engine, operator_engine: Engine, tenants: Tenants
) -> None:
    answer(runtime_engine, tenants.a, "other", JAFZA)
    with operator_tx(operator_engine) as session:
        status = companies.jurisdiction_status(session, company_id=tenants.a.company)
    assert status.details == {
        "licensing_location": "other",
        "licensing_authority": JAFZA,
        "readiness": "unconfirmed",
        "reason": "awaiting_confirmation",
        "employment_jurisdiction": None,
    }


def test_operator_confirmation_cannot_reach_another_company(
    operator_engine: Engine, runtime_engine: Engine, tenants: Tenants
) -> None:
    answer(runtime_engine, tenants.b, "difc")
    with operator_tx(operator_engine) as session:
        session.execute(
            text("SELECT set_config('heroos.company_id', :c, true)"), {"c": str(tenants.a.company)}
        )
        result = session.execute(
            text(
                "UPDATE company_blueprints SET employment_jurisdiction = 'difc', "
                "confirmed_licensing_location = 'difc', jurisdiction_confirmed_at = now() "
                "WHERE company_id = :b"
            ),
            {"b": tenants.b.company},
        )
        assert result.rowcount == 0  # type: ignore[attr-defined]
    assert readiness(runtime_engine, tenants.b)[0] == "unconfirmed"


def test_api_role_cannot_forge_a_confirmation_through_the_orm(
    runtime_engine: Engine, tenants: Tenants
) -> None:
    # Even application code that tried would be refused by the column grants.
    with Session(runtime_engine, autoflush=False) as session:
        scope = scope_for(session, tenants.a)
        blueprint = update_company_blueprint(scope, {"licensing_location": "difc"})
        blueprint.employment_jurisdiction = "difc"
        with pytest.raises(DBAPIError) as exc_info:
            session.flush()
    assert getattr(exc_info.value.orig, "sqlstate", None) == "42501"
    assert readiness(runtime_engine, tenants.a)[0] == "unconfirmed"

    with pytest.raises(ValueError), Session(runtime_engine, autoflush=False) as session:
        update_company_blueprint(scope_for(session, tenants.a), {"employment_jurisdiction": "difc"})


def test_api_role_can_create_a_missing_blueprint_without_confirmation_columns(
    runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM company_blueprints WHERE company_id = :c"), {"c": tenants.a.company}
        )
    answer(runtime_engine, tenants.a, "not_sure")
    assert readiness(runtime_engine, tenants.a) == ("unconfirmed", "licensing_not_sure", None)


# --- database constraints, as the owner (no application validation in the way) --


@pytest.mark.parametrize(
    "assignment",
    [
        pytest.param("licensing_location = 'adgm'", id="unknown-location"),
        pytest.param(
            "licensing_location = 'difc', licensing_authority = 'DIFC'", id="authority-difc"
        ),
        pytest.param(
            "licensing_location = NULL, licensing_authority = 'X'", id="authority-no-location"
        ),
        pytest.param(
            "licensing_location = 'other', licensing_authority = ''", id="empty-authority"
        ),
        pytest.param("employment_jurisdiction = 'mohre'", id="unknown-jurisdiction"),
        pytest.param("employment_jurisdiction = 'difc'", id="confirmation-without-time"),
        pytest.param(
            "employment_jurisdiction = 'difc', jurisdiction_confirmed_at = now()",
            id="confirmation-without-basis",
        ),
        pytest.param(
            "employment_jurisdiction = 'difc', jurisdiction_confirmed_at = now(), "
            "confirmed_licensing_location = 'not_sure'",
            id="confirmed-against-not-sure",
        ),
        pytest.param(
            "employment_jurisdiction = 'difc', jurisdiction_confirmed_at = now(), "
            "confirmed_licensing_location = 'other'",
            id="confirmed-other-without-authority",
        ),
        pytest.param(
            "employment_jurisdiction = 'difc', jurisdiction_confirmed_at = now(), "
            "confirmed_licensing_location = 'difc', confirmed_licensing_authority = 'X'",
            id="confirmed-difc-with-authority",
        ),
        pytest.param("confirmed_licensing_location = 'difc'", id="basis-without-confirmation"),
        pytest.param("jurisdiction_confirmed_at = now()", id="time-without-confirmation"),
    ],
)
def test_database_rejects_inconsistent_licensing_and_confirmation(
    admin_engine: Engine, tenants: Tenants, assignment: str
) -> None:
    with admin_engine.connect() as conn, pytest.raises(IntegrityError) as exc_info:
        conn.execute(
            text(f"UPDATE company_blueprints SET {assignment} WHERE company_id = :c"),
            {"c": tenants.a.company},
        )
    assert getattr(exc_info.value.orig, "sqlstate", None) == "23514"


def test_company_events_are_append_only_even_for_the_owner(
    admin_engine: Engine, tenants: Tenants
) -> None:
    for statement in ("UPDATE company_events SET db_role = 'x'", "DELETE FROM company_events"):
        with admin_engine.connect() as conn, pytest.raises(DBAPIError) as exc_info:
            conn.execute(text(statement))
        assert "append-only" in str(exc_info.value.orig)


def test_company_events_are_tenant_isolated(admin_engine: Engine, tenants: Tenants) -> None:
    # Registration of both seeded Companies was audited, one event each, each
    # owned by its Company (tenant_isolation policy like membership_events).
    with admin_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT company_id, event_type, actor_kind, actor_reference FROM company_events")
        ).all()
    assert sorted(rows) == sorted(
        (tenant.company, "company_registered", "owner", TEST_REFERENCE)
        for tenant in (tenants.a, tenants.b)
    )
