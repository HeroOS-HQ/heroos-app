"""M2-04 employer decision records on real PostgreSQL with RLS, as the API role.

The tenant-isolation contract (tenant-isolation.md §9) for
``workflow_decision_records``, and the decision routes through the real
application:

- isolation three ways (repositories with RLS, RLS alone, the repository filter
  alone), WITH CHECK, and Company-qualified foreign keys: a correction can only
  supersede a record of the same chain, Case and Company;
- append-only for the runtime role, nothing for the operator, and the database
  itself refusing unsafe categories, malformed records, a second successor
  (no branch), a self-reference and, even for the owner, turning a first record
  into a correction (no cycle);
- real concurrency: corrections of one record racing apply exactly one; the
  same request sent at once is applied once; a record and an answer save
  racing for one revision apply exactly one;
- text is stored exactly as entered and the record writes nothing else;
- another Company's administrator can neither read nor correct a record;
- D4 can be downgraded only while no record exists.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.repositories import workflows
from app.tenancy.scope import CompanyScope
from tests.tenant_isolation.conftest import (
    LegacyDatabase,
    Tenants,
    count_rows,
    owners,
    run_alembic,
    scope_for,
)
from tests.tenant_isolation.migration_helpers import D3, D4, admin_scalar, b1a, upgrade
from tests.tenant_isolation.test_company_blueprint import answer, confirm
from tests.tenant_isolation.test_company_roles import set_role
from tests.tenant_isolation.test_workflow_cases import (  # noqa: F401  (pytest fixtures)
    ALICE,
    BOB,
    CONFLICT,
    NOT_FOUND,
    _parallel,
    auth,
    provider,
    signing_key,
    sqlstate,
)
from tests.tenant_isolation.test_workflow_progression import (  # noqa: F401  (pytest fixture)
    recorded_case,
    rules_client,
)

TABLE = "workflow_decision_records"
SUMMARY = "[SYNTHETIC] Manager reviewed the shift handover logs"
EXPLANATION = "[SYNTHETIC] Compared two weeks of logs.\n\tNo other issue found."
COLUMNS = (
    "id, company_id, instance_id, chain_id, supersedes_id, relation, category, summary, "
    "explanation, occurred_on, decision_maker, decision_maker_role, evidence_status, evidence, "
    "change_reason, revision, request_key, recorded_by_user_id, definition_version, "
    "intake_status, progression_status"
)


# A JSON array of 11 evidence references, built in SQL.
ELEVEN_ITEMS = (
    "(SELECT jsonb_agg(jsonb_build_object('kind', 'policy', 'description', i)) "
    "FROM generate_series(1, 11) i)"
)


def _record_sql(**overrides: str) -> str:
    """An INSERT of one first record; ``overrides`` replace column expressions."""
    values = {
        "id": ":id",
        "company_id": ":company",
        "instance_id": ":instance",
        "chain_id": ":id",
        "supersedes_id": "NULL",
        "relation": "'original'",
        "category": "'meeting_recorded'",
        "summary": "'[SYNTHETIC] A meeting took place'",
        "explanation": "'[SYNTHETIC] Explanation'",
        "occurred_on": "DATE '2026-10-12'",
        "decision_maker": "'recorder'",
        "decision_maker_role": "NULL",
        "evidence_status": "'none'",
        "evidence": "'[]'",
        "change_reason": "NULL",
        "revision": ":revision",
        "request_key": "gen_random_uuid()",
        "recorded_by_user_id": ":user",
        "definition_version": "2",
        "intake_status": "'intake_recorded'",
        "progression_status": "'unavailable'",
        **overrides,
    }
    return f"INSERT INTO {TABLE} ({COLUMNS}) VALUES ({', '.join(values.values())})"


def body(revision: int, **overrides: Any) -> dict[str, Any]:
    return {
        "expected_revision": revision,
        "request_key": str(uuid.uuid4()),
        "category": "internal_review_completed",
        "summary": SUMMARY,
        "explanation": EXPLANATION,
        "occurred_on": "2026-10-12",
        "decision_maker": "other",
        "decision_maker_role": "[SYNTHETIC] Operations lead",
        "evidence_status": "held",
        "evidence": [{"kind": "meeting_note", "description": "[SYNTHETIC] Notes",
                      "reference": "HR-2026-014"}],
        **overrides,
    }  # fmt: skip


def record(client: TestClient, company: uuid.UUID, case_id: str, headers: Any, data: Any) -> Any:
    path = f"/companies/{company}/cases/{case_id}/decisions"
    return client.post(path, headers=headers, json=data)


def correct(
    client: TestClient, company: uuid.UUID, case_id: str, record_id: str, headers: Any, data: Any
) -> Any:
    return client.post(
        f"/companies/{company}/cases/{case_id}/decisions/{record_id}/corrections",
        headers=headers,
        json={**data, "relation": "correction", "change_reason": "[SYNTHETIC] Wrong date."},
    )


@pytest.fixture
def decided(
    rules_client: TestClient,  # noqa: F811
    tenants: Tenants,
    auth: Callable[[str], dict[str, str]],  # noqa: F811
    runtime_engine: Engine,
    operator_engine: Engine,
) -> dict[str, Any]:
    """Per Company: a recorded Case with a record and its correction (and a second Case in A)."""
    authority = "[SYNTHETIC] Licensing authority"
    created: dict[str, Any] = {}
    set_role(operator_engine, tenants.b.company, tenants.b.membership, "company_admin")
    for label, tenant, subject in (("a", tenants.a, ALICE), ("b", tenants.b, BOB)):
        answer(runtime_engine, tenant, "other", authority)
        confirm(operator_engine, tenant, "uae_federal", "other", authority)
        case_id, revision = recorded_case(rules_client, tenant.company, auth(subject))
        first = record(rules_client, tenant.company, case_id, auth(subject), body(revision))
        assert first.status_code == 200, first.json()
        original = first.json()["decisions"]["saved"]
        later = body(first.json()["workflow"]["revision"], occurred_on="2026-10-13")
        fixed = correct(rules_client, tenant.company, case_id, original, auth(subject), later)
        assert fixed.status_code == 200, fixed.json()
        with Session(runtime_engine, autoflush=False) as db:
            scope_for(db, tenant)
            instance = db.scalar(
                text("SELECT id FROM workflow_instances WHERE case_id = :c"), {"c": case_id}
            )
        created[label] = {
            "case": case_id,
            "instance": instance,
            "original": uuid.UUID(original),
            "current": uuid.UUID(fixed.json()["decisions"]["saved"]),
            "revision": fixed.json()["workflow"]["revision"],
        }
    other_case = rules_client.post(
        f"/companies/{tenants.a.company}/workflows/disciplinary/cases",
        headers=auth(ALICE),
        json={"title": "[SYNTHETIC] Another case", "request_key": str(uuid.uuid4())},
    ).json()["id"]
    with Session(runtime_engine, autoflush=False) as db:
        scope_for(db, tenants.a)
        created["a_other_instance"] = db.scalar(
            text("SELECT id FROM workflow_instances WHERE case_id = :c"), {"c": other_case}
        )
    return created


def _params(tenants: Tenants, decided: dict[str, Any], label: str = "a") -> dict[str, Any]:
    tenant = tenants.a if label == "a" else tenants.b
    return {
        "id": uuid.uuid4(),
        "company": tenant.company,
        "instance": decided[label]["instance"],
        "user": tenant.user,
        "revision": 900,
        "a_original": decided["a"]["original"],
        "a_current": decided["a"]["current"],
        "b_current": decided["b"]["current"],
    }


# --- isolation, three ways ---------------------------------------------------------------


def test_repositories_see_only_their_own_records(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, decided: dict[str, Any]
) -> None:
    for own, other, tenant in (("a", "b", tenants.a), ("b", "a", tenants.b)):
        with runtime_sessions() as db:
            scope = scope_for(db, tenant)
            mine = workflows.decision_records(scope, decided[own]["instance"])
            assert [r.relation for r in mine] == ["original", "correction"]
            assert workflows.decision_records(scope, decided[other]["instance"]) == []
            assert (
                workflows.get_decision_record(
                    scope, decided[other]["instance"], decided[other]["current"]
                )
                is None
            )
            # Not even through the own instance id.
            assert (
                workflows.get_decision_record(
                    scope, decided[own]["instance"], decided[other]["current"]
                )
                is None
            )


def test_rls_alone_hides_other_companies_records(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, decided: dict[str, Any]
) -> None:
    with runtime_sessions() as db:
        assert count_rows(db, TABLE) == 0  # no tenant context: nothing
        scope_for(db, tenants.a)
        assert owners(db, TABLE) == {tenants.a.company}
        assert count_rows(db, TABLE) == 2


def test_the_repository_filter_alone_hides_other_companies_records(
    admin_sessions: sessionmaker[Session], tenants: Tenants, decided: dict[str, Any]
) -> None:
    # The admin role bypasses RLS: only the repository filter protects here.
    with admin_sessions() as db:
        scope = CompanyScope(session=db, company_id=tenants.a.company)
        assert workflows.decision_records(scope, decided["b"]["instance"]) == []
        assert len(workflows.decision_records(scope, decided["a"]["instance"])) == 2
        assert workflows.decision_successor(
            scope, decided["b"]["instance"], decided["b"]["original"]
        ) is None  # fmt: skip


def test_rls_with_check_refuses_records_for_another_company(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, decided: dict[str, Any]
) -> None:
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        with pytest.raises(DBAPIError) as caught:
            db.execute(text(_record_sql()), _params(tenants, decided, "b"))
        assert sqlstate(caught.value) == "42501"


@pytest.mark.parametrize(
    "overrides",
    [
        # Own Company id, another Company's instance.
        {"instance_id": ":other_instance"},
        # Superseding another Company's record from an own Case.
        {
            "supersedes_id": ":b_current",
            "chain_id": ":b_current",
            "relation": "'correction'",
            "change_reason": "'x'",
        },
        # Superseding a record of another Case of the same Company.
        {
            "instance_id": ":a_other_instance",
            "supersedes_id": ":a_current",
            "chain_id": ":a_original",
            "relation": "'correction'",
            "change_reason": "'x'",
        },
        # Superseding an own record while claiming another chain.
        {
            "supersedes_id": ":a_current",
            "chain_id": "gen_random_uuid()",
            "relation": "'correction'",
            "change_reason": "'x'",
        },
        # A record that doesn't exist.
        {
            "supersedes_id": "gen_random_uuid()",
            "chain_id": ":a_original",
            "relation": "'correction'",
            "change_reason": "'x'",
        },
    ],  # fmt: skip
)
def test_company_qualified_foreign_keys_refuse_cross_case_and_cross_company_links(
    runtime_sessions: sessionmaker[Session],
    tenants: Tenants,
    decided: dict[str, Any],
    overrides: dict[str, str],
) -> None:
    params = {
        **_params(tenants, decided),
        "other_instance": decided["b"]["instance"],
        "a_other_instance": decided["a_other_instance"],
    }
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        with pytest.raises(DBAPIError) as caught:
            db.execute(text(_record_sql(**overrides)), params)
        assert sqlstate(caught.value) == "23503"


# --- append-only, and the database's own refusals ----------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        f"UPDATE {TABLE} SET summary = 'rewritten'",
        f"UPDATE {TABLE} SET category = 'other_note'",
        f"UPDATE {TABLE} SET supersedes_id = NULL",
        f"DELETE FROM {TABLE}",
        f"TRUNCATE {TABLE}",
    ],
)
def test_runtime_role_can_only_append_records(
    runtime_sessions: sessionmaker[Session],
    tenants: Tenants,
    decided: dict[str, Any],
    statement: str,
) -> None:
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        with pytest.raises(DBAPIError) as caught:
            db.execute(text(statement))
        assert sqlstate(caught.value) == "42501"


def test_the_operator_cannot_read_records(operator_engine: Engine, decided: dict[str, Any]) -> None:
    with operator_engine.connect() as conn, pytest.raises(DBAPIError) as caught:
        conn.execute(text(f"SELECT count(*) FROM {TABLE}"))
    assert sqlstate(caught.value) == "42501"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        # Unsafe categories don't exist in the vocabulary.
        ({"category": "'formal_warning_issued'"}, "23514"),
        ({"category": "'employment_terminated'"}, "23514"),
        ({"category": "'specialist_review_approved'"}, "23514"),
        ({"relation": "'approval'"}, "23514"),
        # A first record starts its own chain and carries no change reason.
        ({"chain_id": "gen_random_uuid()"}, "23514"),
        ({"change_reason": "'x'"}, "23514"),
        # A correction says why and never points at itself.
        ({"relation": "'correction'"}, "23514"),
        ({"supersedes_id": ":id", "relation": "'correction'", "change_reason": "'x'"}, "23514"),
        # The named decision-maker: a role exactly when someone else is responsible.
        ({"decision_maker": "'other'"}, "23514"),
        ({"decision_maker_role": "'Lead'"}, "23514"),
        ({"decision_maker": "'ceo'", "decision_maker_role": "'x'"}, "23514"),
        # Held evidence is referenced; otherwise none is listed.
        ({"evidence_status": "'held'"}, "23514"),
        ({"evidence": """'[{"kind": "policy", "description": "x"}]'"""}, "23514"),
        ({"evidence": "'{}'"}, "23514"),
        (
            {
                "evidence_status": "'held'",
                "evidence": ELEVEN_ITEMS,
            },
            "23514",
        ),
        (
            {
                "evidence_status": "'held'",
                "evidence": "jsonb_build_array(jsonb_build_object('d', repeat('x', 9000)))",
            },
            "23514",
        ),
        # Text bounds and no control characters.
        ({"summary": "''"}, "23514"),
        ({"summary": "'a' || chr(10) || 'b'"}, "23514"),
        ({"summary": "'a' || chr(7)"}, "23514"),
        ({"summary": "repeat('x', 201)"}, "22001"),
        ({"explanation": "''"}, "23514"),
        ({"explanation": "repeat('x', 4001)"}, "23514"),
        ({"explanation": "'a' || chr(13) || 'b'"}, "23514"),
        # Dates: no typo decades ago, nothing after tomorrow (UTC).
        ({"occurred_on": "DATE '1989-12-31'"}, "23514"),
        ({"occurred_on": "CURRENT_DATE + 3"}, "23514"),
        ({"intake_status": "'cleared'"}, "23514"),
        ({"progression_status": "'approved'"}, "23514"),
        ({"revision": "0"}, "23514"),
    ],  # fmt: skip
)
def test_the_database_refuses_malformed_records(
    runtime_sessions: sessionmaker[Session],
    tenants: Tenants,
    decided: dict[str, Any],
    overrides: dict[str, str],
    code: str,
) -> None:
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        with pytest.raises(DBAPIError) as caught:
            db.execute(text(_record_sql(**overrides)), _params(tenants, decided))
        assert sqlstate(caught.value) == code


def test_a_record_is_superseded_once_and_keys_and_revisions_are_unique(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, decided: dict[str, Any]
) -> None:
    params = _params(tenants, decided)
    second_line = {
        "supersedes_id": ":a_original",
        "chain_id": ":a_original",
        "relation": "'clarification'",
        "change_reason": "'x'",
    }
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        # The original was already corrected: a second successor is refused.
        with pytest.raises(DBAPIError) as caught:
            db.execute(text(_record_sql(**second_line)), params)
        assert sqlstate(caught.value) == "23505"
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        key = db.scalar(text(f"SELECT request_key FROM {TABLE} LIMIT 1"))
        with pytest.raises(DBAPIError) as caught:
            db.execute(text(_record_sql(request_key=f"'{key}'::uuid")), params)
        assert sqlstate(caught.value) == "23505"
    with runtime_sessions() as db:
        scope_for(db, tenants.a)
        with pytest.raises(DBAPIError) as caught:
            db.execute(text(_record_sql()), {**params, "revision": decided["a"]["revision"]})
        assert sqlstate(caught.value) == "23505"


def test_even_the_owner_cannot_turn_a_first_record_into_a_cycle(
    admin_engine: Engine, decided: dict[str, Any]
) -> None:
    # Make the original supersede its own correction (A -> B -> A): the shape
    # and the chain key refuse it, whatever the owner's privileges.
    with admin_engine.connect() as conn, pytest.raises(DBAPIError) as caught:
        conn.execute(
            text(
                f"UPDATE {TABLE} SET supersedes_id = :current, relation = 'correction', "
                "change_reason = 'x' WHERE id = :original"
            ),
            {"current": decided["a"]["current"], "original": decided["a"]["original"]},
        )
    assert sqlstate(caught.value) == "23514"


def test_text_is_stored_exactly_and_nothing_else_is_written(
    admin_engine: Engine, decided: dict[str, Any]
) -> None:
    with admin_engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT summary, explanation, evidence::text, recorded_by_user_id "
                f"FROM {TABLE} WHERE instance_id = :i ORDER BY revision"
            ),
            {"i": decided["a"]["instance"]},
        ).all()
        progress = conn.scalar(
            text("SELECT count(*) FROM workflow_progress_events WHERE instance_id = :i"),
            {"i": decided["a"]["instance"]},
        )
    assert [(r[0], r[1]) for r in rows] == [(SUMMARY, EXPLANATION)] * 2
    assert "HR-2026-014" in rows[0][2]
    # Recording never touched progression: only the intake's events (none).
    assert progress == 0


# --- concurrency (real PostgreSQL row locks) ----------------------------------------------


def test_concurrent_corrections_are_serialized(
    rules_client: TestClient,  # noqa: F811
    tenants: Tenants,
    auth: Callable[[str], dict[str, str]],  # noqa: F811
    decided: dict[str, Any],
    admin_sessions: sessionmaker[Session],
) -> None:
    company, case_id = tenants.a.company, decided["a"]["case"]
    current, revision = str(decided["a"]["current"]), decided["a"]["revision"]
    # Different corrections of one record racing: exactly one is recorded.
    raced = _parallel(
        [
            lambda i=i: correct(
                rules_client,
                company,
                case_id,
                current,
                auth(ALICE),
                body(revision, summary=f"[SYNTHETIC] Version {i}"),
            )  # fmt: skip
            for i in range(3)
        ]
    )
    assert sorted(r.status_code for r in raced) == [200, 409, 409]
    winner = next(r for r in raced if r.status_code == 200).json()
    revision = winner["workflow"]["revision"]
    # The same request sent three times at once: applied once, the same answer.
    same = body(revision, summary="[SYNTHETIC] Retried")
    newest = winner["decisions"]["saved"]
    retried = _parallel(
        [lambda: correct(rules_client, company, case_id, newest, auth(ALICE), same)] * 3
    )
    assert [r.status_code for r in retried] == [200, 200, 200]
    assert len({r.json()["decisions"]["saved"] for r in retried}) == 1
    assert {r.json()["workflow"]["revision"] for r in retried} == {revision + 1}
    revision += 1
    # A record and an answer save racing for one revision: exactly one applies.
    mixed = _parallel(
        [
            lambda: record(rules_client, company, case_id, auth(ALICE), body(revision)),
            lambda: rules_client.put(
                f"/companies/{company}/cases/{case_id}/workflow/steps/initial_facts/answers",
                headers=auth(ALICE),
                json={
                    "expected_revision": revision,
                    "submission_key": str(uuid.uuid4()),
                    "answers": {"incident.history": "not_sure"},
                },
            ),
        ]
    )
    assert sorted(r.status_code for r in mixed) == [200, 409]
    with admin_sessions() as db:
        chain = db.execute(
            text(
                f"SELECT relation, supersedes_id FROM {TABLE} WHERE chain_id = :c ORDER BY revision"
            ),
            {"c": decided["a"]["original"]},
        ).all()
    # One line: original -> correction -> the race winner -> the retried request.
    assert [row[0] for row in chain] == ["original", "correction", "correction", "correction"]
    assert len({row[1] for row in chain}) == 4


def test_another_companys_administrator_can_neither_read_nor_correct(
    rules_client: TestClient,  # noqa: F811
    tenants: Tenants,
    auth: Callable[[str], dict[str, str]],  # noqa: F811
    decided: dict[str, Any],
    admin_sessions: sessionmaker[Session],
) -> None:
    case_id, current = decided["a"]["case"], str(decided["a"]["current"])
    b = tenants.b.company
    for response in (
        rules_client.get(f"/companies/{b}/cases/{case_id}/decisions", headers=auth(BOB)),
        rules_client.get(f"/companies/{b}/cases/{case_id}/history", headers=auth(BOB)),
        correct(rules_client, b, case_id, current, auth(BOB), body(decided["a"]["revision"])),
        # Bob's own Case can't reach A's record either.
        correct(
            rules_client,
            b,
            decided["b"]["case"],
            current,
            auth(BOB),
            body(decided["b"]["revision"]),
        ),  # fmt: skip
    ):
        assert (response.status_code, response.json()) == NOT_FOUND
    with admin_sessions() as db:
        assert db.scalar(text(f"SELECT count(*) FROM {TABLE}")) == 4
    # A stale correction from A's own administrator is refused too.
    stale = correct(rules_client, tenants.a.company, case_id, current, auth(ALICE),
                    body(decided["a"]["revision"] - 1))  # fmt: skip
    assert (stale.status_code, stale.json()) == CONFLICT


# --- the migration ---------------------------------------------------------------------


def test_d4_downgrades_only_while_no_record_exists(legacy_db: LegacyDatabase) -> None:
    b1a(legacy_db)
    upgrade(legacy_db, D4)
    assert admin_scalar(legacy_db, "SELECT heroos_schema_contract()") == 7
    # Empty: reversible to D3 (contract 6), then re-applied.
    down = run_alembic(legacy_db.admin_url, "downgrade", D3)
    assert down.returncode == 0, down.stderr
    assert admin_scalar(legacy_db, "SELECT heroos_schema_contract()") == 6
    upgrade(legacy_db, D4)
    engine = create_engine(legacy_db.admin_url)
    try:
        with engine.begin() as conn:
            ids = {"company": legacy_db.company_a, "user": legacy_db.alice}
            case = conn.scalar(
                text(
                    "INSERT INTO cases (id, company_id, case_type, title) VALUES "
                    "(gen_random_uuid(), :company, 'disciplinary', '[SYNTHETIC] D4') RETURNING id"
                ),
                ids,
            )
            instance = conn.scalar(
                text(
                    "INSERT INTO workflow_instances (id, company_id, case_id, workflow_key, "
                    "definition_version, revision, request_key, created_by_user_id) VALUES "
                    "(gen_random_uuid(), :company, :case, 'disciplinary', 2, 1, "
                    "gen_random_uuid(), :user) RETURNING id"
                ),
                {**ids, "case": case},
            )
            values = {**ids, "id": uuid.uuid4(), "instance": instance, "revision": 1}
            conn.execute(text(_record_sql()), values)
    finally:
        engine.dispose()
    refused = run_alembic(legacy_db.admin_url, "downgrade", D3)
    assert refused.returncode != 0
    assert "workflow decision records exist" in refused.stderr
    assert admin_scalar(legacy_db, "SELECT version_num FROM alembic_version") == D4
    assert admin_scalar(legacy_db, f"SELECT count(*) FROM {TABLE}") == 1
    assert admin_scalar(legacy_db, "SELECT heroos_schema_contract()") == 7
