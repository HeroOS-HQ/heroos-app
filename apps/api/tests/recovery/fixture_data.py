"""Deterministic synthetic data for the backup/restore verification.

Fixed UUIDs and values, so the restored database can be checked against known
content as well as against the source. Entirely synthetic: no real Company,
person or HR content.

Seeds the disposable source database (``make backup-restore-check``)::

    RECOVERY_TEST_SOURCE_URL=... uv run python -m tests.recovery.fixture_data
"""

import os
import re
import sys
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db.models import (
    Case,
    CaseSubject,
    Company,
    CompanyBlueprint,
    Membership,
    User,
    UserIdentity,
)

SOURCE_URL_ENV = "RECOVERY_TEST_SOURCE_URL"
SAFE_SOURCE_DATABASE = re.compile(r"[a-z0-9_]+_backup_source_test")

COMPANY_A = UUID("a0000000-0000-4000-8000-00000000000a")
COMPANY_B = UUID("b0000000-0000-4000-8000-00000000000b")
USER_A = UUID("a1000000-0000-4000-8000-00000000000a")
USER_B = UUID("b1000000-0000-4000-8000-00000000000b")
MEMBERSHIP_A = UUID("a2000000-0000-4000-8000-00000000000a")
MEMBERSHIP_B = UUID("b2000000-0000-4000-8000-00000000000b")
BLUEPRINT_A = UUID("a3000000-0000-4000-8000-00000000000a")
BLUEPRINT_B = UUID("b3000000-0000-4000-8000-00000000000b")
SUBJECT_A = UUID("a4000000-0000-4000-8000-00000000000a")
SUBJECT_B = UUID("b4000000-0000-4000-8000-00000000000b")
CASE_A = UUID("a5000000-0000-4000-8000-00000000000a")
CASE_B = UUID("b5000000-0000-4000-8000-00000000000b")
IDENTITY_A = UUID("a6000000-0000-4000-8000-00000000000a")
IDENTITY_B = UUID("b6000000-0000-4000-8000-00000000000b")
ISSUER = "urn:heroos:recovery-test"
# Seeding is attributed like any change (the audit triggers require it).
REFERENCE = "HER-230"

# Expected tenant-owned rows per Company after restore: {table: {company: ids}}.
EXPECTED_ROWS: dict[str, dict[UUID, set[UUID]]] = {
    "companies": {COMPANY_A: {COMPANY_A}, COMPANY_B: {COMPANY_B}},
    "memberships": {COMPANY_A: {MEMBERSHIP_A}, COMPANY_B: {MEMBERSHIP_B}},
    "company_blueprints": {COMPANY_A: {BLUEPRINT_A}, COMPANY_B: {BLUEPRINT_B}},
    "case_subjects": {COMPANY_A: {SUBJECT_A}, COMPANY_B: {SUBJECT_B}},
    "cases": {COMPANY_A: {CASE_A}, COMPANY_B: {CASE_B}},
}


def build() -> list[object]:
    rows: list[object] = []
    for label, company, user, identity, membership, blueprint, subject, case in (
        ("A", COMPANY_A, USER_A, IDENTITY_A, MEMBERSHIP_A, BLUEPRINT_A, SUBJECT_A, CASE_A),
        ("B", COMPANY_B, USER_B, IDENTITY_B, MEMBERSHIP_B, BLUEPRINT_B, SUBJECT_B, CASE_B),
    ):
        rows.append(Company(id=company, name=f"Recovery Synthetic Company {label}"))
        rows.append(User(id=user))
        rows.append(
            UserIdentity(
                id=identity,
                user_id=user,
                issuer=ISSUER,
                subject=f"recovery-synthetic-subject-{label.lower()}",
            )
        )
        rows.append(Membership(id=membership, company_id=company, user_id=user))
        rows.append(
            CompanyBlueprint(
                id=blueprint,
                company_id=company,
                legal_name=f"Recovery Synthetic {label} LLC",
                primary_jurisdiction="DIFC",
            )
        )
        rows.append(
            CaseSubject(
                id=subject,
                company_id=company,
                subject_type="employee",
                display_name=f"Synthetic Subject {label}",
            )
        )
        rows.append(
            Case(
                id=case,
                company_id=company,
                subject_id=subject,
                case_type="disciplinary",
                title=f"Synthetic Recovery Case {label}",
            )
        )
    return rows


def seed(admin_url: str) -> None:
    """Insert the dataset as the migration/admin role (owner; bypasses RLS)."""
    database = make_url(admin_url).database or ""
    if not SAFE_SOURCE_DATABASE.fullmatch(database):
        raise SystemExit(f"refusing to seed {database!r}: must match *_backup_source_test")
    engine = create_engine(admin_url)
    try:
        with Session(engine) as session:
            session.execute(
                text("SELECT set_config('heroos.actor_reference', :ref, true)"), {"ref": REFERENCE}
            )
            # Parents first: flush in dependency order.
            for row in build():
                session.add(row)
                session.flush()
            session.commit()
    finally:
        engine.dispose()


if __name__ == "__main__":
    url = os.environ.get(SOURCE_URL_ENV)
    if not url:
        print(f"{SOURCE_URL_ENV} is required", file=sys.stderr)
        raise SystemExit(2)
    seed(url)
    print("Seeded synthetic recovery dataset (2 Companies).")
