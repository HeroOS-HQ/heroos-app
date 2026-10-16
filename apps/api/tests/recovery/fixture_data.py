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
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db.models import (
    Case,
    CaseFact,
    CaseSubject,
    Company,
    CompanyBlueprint,
    CompanyRegistration,
    Membership,
    User,
    UserIdentity,
    WorkflowEvaluation,
    WorkflowInstance,
    WorkflowSubmission,
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
REGISTRATION_A = UUID("a7000000-0000-4000-8000-00000000000a")
# M2-01 workflow state a restore must keep: each Case runs the Disciplinary
# workflow with one saved answer group and one (synthetic) fact.
INSTANCE_A = UUID("a8000000-0000-4000-8000-00000000000a")
INSTANCE_B = UUID("b8000000-0000-4000-8000-00000000000b")
REQUEST_KEY_A = UUID("a9000000-0000-4000-8000-00000000000a")
REQUEST_KEY_B = UUID("b9000000-0000-4000-8000-00000000000b")
SUBMISSION_A = UUID("aa000000-0000-4000-8000-00000000000a")
SUBMISSION_B = UUID("ba000000-0000-4000-8000-00000000000b")
SUBMISSION_KEY_A = UUID("ab000000-0000-4000-8000-00000000000a")
SUBMISSION_KEY_B = UUID("bb000000-0000-4000-8000-00000000000b")
FACT_A = UUID("ac000000-0000-4000-8000-00000000000a")
FACT_B = UUID("bc000000-0000-4000-8000-00000000000b")
EVALUATION_A = UUID("ad000000-0000-4000-8000-00000000000a")
EVALUATION_B = UUID("bd000000-0000-4000-8000-00000000000b")
# A synthetic intake evaluation trace (M2-02): codes and enumerated answers only.
EVALUATION_RESULTS = [
    {
        "rule": "case_jurisdiction",
        "order": 1,
        "applies_in": [],
        "provisional": False,
        "enforced": True,
        "outcome": "fired",
        "action": "block",
        "reason": "company_unconfirmed",
        "shown": True,
        "inputs": {"company.readiness": "unconfirmed"},
    }
]
ISSUER = "urn:heroos:recovery-test"
# M1-10C state a restore must keep: A has an administrator and a current DIFC
# confirmation; B is a member-only Company with an unconfirmed "Other" answer.
CONFIRMED_AT = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)
AUTHORITY_B = "Synthetic Free Zone Authority"
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
        rows.append(
            Membership(
                id=membership,
                company_id=company,
                user_id=user,
                role="company_admin" if label == "A" else "member",
            )
        )
        if label == "A":
            # Company A was self-registered by its founder.
            rows.append(
                CompanyRegistration(
                    id=REGISTRATION_A,
                    identity_id=identity,
                    user_id=user,
                    company_id=company,
                    membership_id=membership,
                )
            )
        licensing: dict[str, object] = (
            {
                "licensing_location": "difc",
                "employment_jurisdiction": "difc",
                "confirmed_licensing_location": "difc",
                "jurisdiction_confirmed_at": CONFIRMED_AT,
            }
            if label == "A"
            else {"licensing_location": "other", "licensing_authority": AUTHORITY_B}
        )
        rows.append(
            CompanyBlueprint(
                id=blueprint,
                company_id=company,
                legal_name=f"Recovery Synthetic {label} LLC",
                primary_jurisdiction="DIFC",
                **licensing,
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
        instance, request_key, submission, submission_key, fact, evaluation = (
            (INSTANCE_A, REQUEST_KEY_A, SUBMISSION_A, SUBMISSION_KEY_A, FACT_A, EVALUATION_A)
            if label == "A"
            else (INSTANCE_B, REQUEST_KEY_B, SUBMISSION_B, SUBMISSION_KEY_B, FACT_B, EVALUATION_B)
        )
        rows.append(
            WorkflowInstance(
                id=instance,
                company_id=company,
                case_id=case,
                workflow_key="disciplinary",
                definition_version=1,
                revision=1,
                request_key=request_key,
                created_by_user_id=user,
            )
        )
        rows.append(
            WorkflowSubmission(
                id=submission,
                company_id=company,
                instance_id=instance,
                step_key="initial_facts",
                revision=1,
                idempotency_key=submission_key,
                submitted_by_user_id=user,
            )
        )
        rows.append(
            CaseFact(
                id=fact,
                company_id=company,
                instance_id=instance,
                submission_id=submission,
                fact_key="incident.history",
                value="new",
            )
        )
        rows.append(
            WorkflowEvaluation(
                id=evaluation,
                company_id=company,
                instance_id=instance,
                submission_id=submission,
                definition_version=2,
                ruleset_version="disciplinary-intake.1",
                ruleset_digest="0" * 64,
                status="awaiting_jurisdiction",
                hold="jurisdiction",
                hold_reason="company_jurisdiction_unconfirmed",
                jurisdiction=None,
                screening="not_applicable",
                results=EVALUATION_RESULTS,
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
