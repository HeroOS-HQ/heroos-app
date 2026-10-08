"""Cross-Company reads and guessed resource IDs.

Each layer is tested on its own:

- the full production path: repositories + RLS, as the runtime role;
- RLS alone: unfiltered queries for the other Company's exact IDs, as the runtime role;
- the repository filter alone: repositories on an admin (RLS-bypassing) session.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Case, CaseSubject, Company, CompanyBlueprint, Membership
from app.repositories import case_subjects, cases, companies, company_blueprints
from app.tenancy.scope import CompanyScope
from tests.tenant_isolation.conftest import Tenant, Tenants, scope_for

DIRECTIONS = [pytest.param(("a", "b"), id="A-reads-B"), pytest.param(("b", "a"), id="B-reads-A")]


def _pair(tenants: Tenants, direction: tuple[str, str]) -> tuple[Tenant, Tenant]:
    viewer, other = direction
    return getattr(tenants, viewer), getattr(tenants, other)


def _assert_repositories_isolate(scope: CompanyScope, own: Tenant, other: Tenant) -> None:
    company = companies.get_company(scope)
    assert company is not None and company.id == own.company

    blueprint = company_blueprints.get_company_blueprint(scope)
    assert blueprint is not None and blueprint.id == own.blueprint

    assert [s.id for s in case_subjects.list_case_subjects(scope)] == [own.subject]
    assert [c.id for c in cases.list_cases(scope)] == [own.case]

    own_subject = case_subjects.get_case_subject(scope, own.subject)
    assert own_subject is not None and own_subject.company_id == own.company
    own_case = cases.get_case(scope, own.case)
    assert own_case is not None and own_case.company_id == own.company

    # Guessed IDs: the other Company's exact UUIDs look like missing rows.
    assert case_subjects.get_case_subject(scope, other.subject) is None
    assert cases.get_case(scope, other.case) is None
    # Other-Company IDs used for the wrong resource type find nothing either.
    assert cases.get_case(scope, other.subject) is None
    assert case_subjects.get_case_subject(scope, other.case) is None


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_runtime_repositories_isolate_companies(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, direction: tuple[str, str]
) -> None:
    own, other = _pair(tenants, direction)
    with runtime_sessions() as db:
        _assert_repositories_isolate(scope_for(db, own), own, other)


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_rls_alone_hides_guessed_ids(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, direction: tuple[str, str]
) -> None:
    own, other = _pair(tenants, direction)
    with runtime_sessions() as db:
        scope_for(db, own)
        # No company_id filter anywhere: only RLS stands between these queries
        # and the other Company's rows.
        assert db.get(Company, other.company) is None
        assert db.scalar(select(Company).where(Company.id == other.company)) is None
        assert db.scalar(select(Membership).where(Membership.id == other.membership)) is None
        assert db.scalar(select(Membership).where(Membership.user_id == other.user)) is None
        assert (
            db.scalar(select(CompanyBlueprint).where(CompanyBlueprint.id == other.blueprint))
            is None
        )
        assert db.scalar(select(CaseSubject).where(CaseSubject.id == other.subject)) is None
        assert db.scalar(select(Case).where(Case.id == other.case)) is None
        assert db.scalar(select(Case).where(Case.company_id == other.company)) is None

        # Positive control: the same unfiltered queries do return own rows.
        assert db.scalar(select(Case).where(Case.id == own.case)) is not None
        assert db.get(Company, own.company) is not None


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_repository_filter_alone_hides_guessed_ids(
    admin_sessions: sessionmaker[Session], tenants: Tenants, direction: tuple[str, str]
) -> None:
    own, other = _pair(tenants, direction)
    # The admin role bypasses RLS and sees both Companies, so only the
    # repositories' own company_id filter can produce isolation here.
    with admin_sessions() as db:
        assert db.get(Case, other.case) is not None  # really visible without the filter
        scope = CompanyScope(session=db, company_id=own.company)
        _assert_repositories_isolate(scope, own, other)
