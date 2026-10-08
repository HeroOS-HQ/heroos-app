"""Cross-Company create, update, delete and re-parenting.

As in the read tests, the full runtime path, RLS alone and the repository
filter alone are each proven. Ground truth is always re-read as admin.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Case, CaseSubject, Company, CompanyBlueprint, Membership
from app.repositories import ResourceNotFoundError, case_subjects, cases, companies
from app.repositories import company_blueprints as blueprints
from app.repositories.company_blueprints import CompanyBlueprintFields
from app.tenancy.scope import CompanyScope
from tests.tenant_isolation.conftest import TENANT_TABLES, Tenant, Tenants, count_rows, scope_for

RLS_VIOLATION = "42501"
FOREIGN_KEY_VIOLATION = "23503"


def _sqlstate(exc: DBAPIError) -> str | None:
    return getattr(exc.orig, "sqlstate", None)


def _snapshot(admin_sessions: sessionmaker[Session], tenant: Tenant) -> dict[str, Any]:
    with admin_sessions() as db:
        return {
            "company": db.scalar(
                text("SELECT name FROM companies WHERE id = :id"), {"id": tenant.company}
            ),
            "blueprint": db.execute(
                text("SELECT company_id, legal_name FROM company_blueprints WHERE id = :id"),
                {"id": tenant.blueprint},
            ).one(),
            "subject": db.execute(
                text("SELECT company_id, display_name FROM case_subjects WHERE id = :id"),
                {"id": tenant.subject},
            ).one(),
            "case": db.execute(
                text("SELECT company_id, subject_id, title FROM cases WHERE id = :id"),
                {"id": tenant.case},
            ).one(),
            "membership": db.execute(
                text("SELECT company_id, user_id FROM memberships WHERE id = :id"),
                {"id": tenant.membership},
            ).one(),
        }


# --- Create ------------------------------------------------------------------


def test_repositories_always_create_in_scope_company(
    runtime_sessions: sessionmaker[Session],
    admin_sessions: sessionmaker[Session],
    tenants: Tenants,
) -> None:
    with runtime_sessions() as db:
        scope = scope_for(db, tenants.a)
        subject = case_subjects.create_case_subject(
            scope, subject_type="candidate", display_name="New A"
        )
        case = cases.create_case(scope, case_type="probation", title="New A", subject_id=subject.id)
        ids = (subject.id, case.id)
        db.commit()

    with admin_sessions() as db:
        assert db.get(CaseSubject, ids[0]).company_id == tenants.a.company  # type: ignore[union-attr]
        assert db.get(Case, ids[1]).company_id == tenants.a.company  # type: ignore[union-attr]


def _new_rows_owned_by(tenants: Tenants, owner: Tenant) -> dict[str, Callable[[], object]]:
    return {
        "companies": lambda: Company(id=uuid.uuid4(), name="Forged"),
        "memberships": lambda: Membership(company_id=owner.company, user_id=tenants.carol),
        "company_blueprints": lambda: CompanyBlueprint(company_id=owner.company),
        "case_subjects": lambda: CaseSubject(
            company_id=owner.company, subject_type="employee", display_name="Forged"
        ),
        "cases": lambda: Case(company_id=owner.company, case_type="probation", title="Forged"),
    }


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_rls_rejects_rows_created_for_another_company(
    runtime_sessions: sessionmaker[Session],
    admin_sessions: sessionmaker[Session],
    tenants: Tenants,
    table: str,
) -> None:
    # Company A context inserting a row owned by Company B (for companies: any
    # Company other than A). WITH CHECK rejects it before any constraint.
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        db.add(_new_rows_owned_by(tenants, tenants.b)[table]())
        with pytest.raises(DBAPIError) as exc_info:
            db.flush()

    assert _sqlstate(exc_info.value) == RLS_VIOLATION
    assert "row-level security" in str(exc_info.value.orig)
    with admin_sessions() as db:
        assert count_rows(db, table) == 2


def test_case_cannot_reference_another_companys_subject(
    runtime_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    with runtime_sessions() as db:
        scope = scope_for(db, tenants.a)
        with pytest.raises(ResourceNotFoundError):
            cases.create_case(scope, case_type="probation", title="x", subject_id=tenants.b.subject)
        with pytest.raises(ResourceNotFoundError):
            cases.assign_case_subject(scope, tenants.a.case, tenants.b.subject)


# --- Update / delete through repositories ------------------------------------


def _attempt_cross_company_mutations(scope: CompanyScope, other: Tenant) -> None:
    assert cases.update_case(scope, other.case, case_type="x", title="tampered") is None
    assert cases.assign_case_subject(scope, other.case, None) is None
    assert cases.delete_case(scope, other.case) is False
    assert (
        case_subjects.update_case_subject(
            scope, other.subject, display_name="tampered", reference=None
        )
        is None
    )
    assert case_subjects.delete_case_subject(scope, other.subject) is False


@pytest.mark.parametrize("direction", [("a", "b"), ("b", "a")], ids=["A-to-B", "B-to-A"])
def test_runtime_repositories_cannot_mutate_another_company(
    runtime_sessions: sessionmaker[Session],
    admin_sessions: sessionmaker[Session],
    tenants: Tenants,
    direction: tuple[str, str],
) -> None:
    own, other = (getattr(tenants, name) for name in direction)
    before = _snapshot(admin_sessions, other)

    with runtime_sessions() as db:
        scope = scope_for(db, own)
        _attempt_cross_company_mutations(scope, other)
        # Company and Blueprint operations can only address the scope's own rows.
        companies.rename_company(scope, "Renamed own")
        blueprints.save_company_blueprint(scope, CompanyBlueprintFields(legal_name="Own LLC"))
        db.commit()

    assert _snapshot(admin_sessions, other) == before


def test_repository_filter_alone_blocks_cross_company_mutations(
    admin_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    # Admin bypasses RLS: only the repositories' company_id filter protects B.
    before = _snapshot(admin_sessions, tenants.b)
    with admin_sessions() as db:
        scope = CompanyScope(session=db, company_id=tenants.a.company)
        _attempt_cross_company_mutations(scope, tenants.b)
        assert blueprints.delete_company_blueprint(scope) is True  # A's, not B's
        db.commit()

    assert _snapshot(admin_sessions, tenants.b) == before


# --- Update / delete with RLS alone ------------------------------------------

CROSS_COMPANY_STATEMENTS = [
    "UPDATE companies SET name = 'tampered' WHERE id = :company",
    "UPDATE memberships SET user_id = user_id WHERE id = :membership",
    "UPDATE company_blueprints SET legal_name = 'tampered' WHERE id = :blueprint",
    "UPDATE case_subjects SET display_name = 'tampered' WHERE id = :subject",
    "UPDATE cases SET title = 'tampered' WHERE id = :case",
    "DELETE FROM cases WHERE id = :case",
    "DELETE FROM case_subjects WHERE id = :subject",
    "DELETE FROM company_blueprints WHERE id = :blueprint",
    "DELETE FROM memberships WHERE id = :membership",
    "DELETE FROM companies WHERE id = :company",
]


@pytest.mark.parametrize("statement", CROSS_COMPANY_STATEMENTS)
def test_rls_alone_blocks_update_and_delete_of_guessed_ids(
    runtime_sessions: sessionmaker[Session],
    admin_sessions: sessionmaker[Session],
    tenants: Tenants,
    statement: str,
) -> None:
    b = tenants.b
    params = {
        "company": b.company,
        "membership": b.membership,
        "blueprint": b.blueprint,
        "subject": b.subject,
        "case": b.case,
    }
    before = _snapshot(admin_sessions, b)

    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        result = db.execute(text(statement), params)
        assert result.rowcount == 0  # type: ignore[attr-defined]
        db.commit()

    assert _snapshot(admin_sessions, b) == before


# --- Re-parenting ------------------------------------------------------------

REPARENT_STATEMENTS = [
    pytest.param("UPDATE cases SET company_id = :target WHERE id = :case", id="case"),
    pytest.param("UPDATE case_subjects SET company_id = :target WHERE id = :subject", id="subject"),
    pytest.param(
        "UPDATE company_blueprints SET company_id = :target WHERE id = :blueprint", id="blueprint"
    ),
    pytest.param(
        "UPDATE memberships SET company_id = :target WHERE id = :membership", id="membership"
    ),
    pytest.param("UPDATE companies SET id = :target WHERE id = :company", id="company"),
]


@pytest.mark.parametrize("statement", REPARENT_STATEMENTS)
def test_rls_with_check_blocks_moving_rows_to_another_company(
    runtime_sessions: sessionmaker[Session],
    admin_sessions: sessionmaker[Session],
    tenants: Tenants,
    statement: str,
) -> None:
    a = tenants.a
    params = {
        "target": tenants.b.company,
        "company": a.company,
        "membership": a.membership,
        "blueprint": a.blueprint,
        "subject": a.subject,
        "case": a.case,
    }
    before = _snapshot(admin_sessions, a)

    with runtime_sessions() as db:
        scope_for(db, a)
        with pytest.raises(DBAPIError) as exc_info:
            db.execute(text(statement), params)

    assert _sqlstate(exc_info.value) == RLS_VIOLATION
    assert _snapshot(admin_sessions, a) == before


def test_orm_company_id_change_is_rejected(
    runtime_sessions: sessionmaker[Session], admin_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    with runtime_sessions() as db:
        scope = scope_for(db, tenants.a)
        case = cases.get_case(scope, tenants.a.case)
        assert case is not None
        case.company_id = tenants.b.company
        with pytest.raises(DBAPIError) as exc_info:
            db.flush()

    assert _sqlstate(exc_info.value) == RLS_VIOLATION
    with admin_sessions() as db:
        assert db.get(Case, tenants.a.case).company_id == tenants.a.company  # type: ignore[union-attr]


def test_case_cannot_be_pointed_at_another_companys_subject_in_the_database(
    runtime_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    # The subject row is invisible under RLS, but the composite
    # (company_id, subject_id) foreign key is what rejects the reference.
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        with pytest.raises(DBAPIError) as exc_info:
            db.execute(
                text("UPDATE cases SET subject_id = :subject WHERE id = :case"),
                {"subject": tenants.b.subject, "case": tenants.a.case},
            )

    assert _sqlstate(exc_info.value) == FOREIGN_KEY_VIOLATION


# --- Same-Company writes still work ------------------------------------------


def test_same_company_create_update_delete_succeed(
    runtime_sessions: sessionmaker[Session], admin_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    a = tenants.a
    with runtime_sessions() as db:
        scope = scope_for(db, a)
        assert companies.rename_company(scope, "Company A Renamed") is not None
        blueprint = blueprints.save_company_blueprint(
            scope, CompanyBlueprintFields(legal_name="A Holdings", employee_count=12)
        )
        assert blueprint.id == a.blueprint
        subject = case_subjects.create_case_subject(
            scope, subject_type="candidate", display_name="Candidate A"
        )
        assert case_subjects.update_case_subject(
            scope, a.subject, display_name="Employee A2", reference="E-1"
        )
        assert cases.update_case(scope, a.case, case_type="probation", title="Updated A")
        assert cases.assign_case_subject(scope, a.case, subject.id)
        new_case = cases.create_case(scope, case_type="recruitment", title="Hire")
        assert cases.delete_case(scope, new_case.id) is True
        scope.commit()

        # Still scoped to A after the commit: committed objects refresh normally.
        assert subject.display_name == "Candidate A"
        assert blueprints.delete_company_blueprint(scope) is True
        assert case_subjects.delete_case_subject(scope, subject.id) is True
        scope.commit()

    with admin_sessions() as db:
        assert db.get(Company, a.company).name == "Company A Renamed"  # type: ignore[union-attr]
        assert db.get(CompanyBlueprint, a.blueprint) is None
        assert db.get(CaseSubject, a.subject).display_name == "Employee A2"  # type: ignore[union-attr]
        case = db.get(Case, a.case)
        assert case is not None
        assert (case.title, case.case_type) == ("Updated A", "probation")
        # Deleting the subject nulled only subject_id; ownership is intact.
        assert case.subject_id is None
        assert case.company_id == a.company
        # Company B untouched.
        assert count_rows(db, "company_blueprints") == 1


# --- WITH CHECK on its own ---------------------------------------------------
# ORM inserts use RETURNING and the UPDATEs above have a WHERE clause; in both
# cases PostgreSQL also applies the policy's USING expression to the new row.
# These statement shapes leave WITH CHECK as the only barrier (found by
# mutation testing with WITH CHECK (true)).

PLAIN_INSERTS = {
    "companies": "INSERT INTO companies (id, name) VALUES (gen_random_uuid(), 'Forged')",
    "memberships": (
        "INSERT INTO memberships (id, company_id, user_id) "
        "VALUES (gen_random_uuid(), :target, :carol)"
    ),
    "company_blueprints": (
        "INSERT INTO company_blueprints (id, company_id) VALUES (gen_random_uuid(), :target)"
    ),
    "case_subjects": (
        "INSERT INTO case_subjects (id, company_id, subject_type, display_name) "
        "VALUES (gen_random_uuid(), :target, 'employee', 'Forged')"
    ),
    "cases": (
        "INSERT INTO cases (id, company_id, case_type, title) "
        "VALUES (gen_random_uuid(), :target, 'probation', 'Forged')"
    ),
}

UNQUALIFIED_REPARENTS = {
    "companies": "UPDATE companies SET id = gen_random_uuid()",
    "memberships": "UPDATE memberships SET company_id = :target",
    "company_blueprints": "UPDATE company_blueprints SET company_id = :target",
    "case_subjects": "UPDATE case_subjects SET company_id = :target",
    "cases": "UPDATE cases SET company_id = :target",
}


@pytest.mark.parametrize("table", TENANT_TABLES)
@pytest.mark.parametrize("kind", ["insert-without-returning", "update-without-where"])
def test_with_check_alone_blocks_other_company_rows(
    runtime_sessions: sessionmaker[Session],
    admin_sessions: sessionmaker[Session],
    tenants: Tenants,
    table: str,
    kind: str,
) -> None:
    statement = (PLAIN_INSERTS if kind == "insert-without-returning" else UNQUALIFIED_REPARENTS)[
        table
    ]
    before = _snapshot(admin_sessions, tenants.a)

    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        with pytest.raises(DBAPIError) as exc_info:
            db.execute(text(statement), {"target": tenants.b.company, "carol": tenants.carol})

    assert _sqlstate(exc_info.value) == RLS_VIOLATION
    assert _snapshot(admin_sessions, tenants.a) == before
    with admin_sessions() as db:
        assert count_rows(db, table) == 2
