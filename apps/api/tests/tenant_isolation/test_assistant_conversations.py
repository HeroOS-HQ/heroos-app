"""M2-NEW-07 Ask HeroOS conversations on real PostgreSQL with RLS, as the API role.

The tenant-isolation contract (tenant-isolation.md §9) for the four conversation
tables and the new submission provenance, and persisted turns through the real
service:

- isolation three ways (repositories with RLS, RLS alone, the repository filter
  alone), WITH CHECK, and Company-qualified foreign keys (a message, an
  evaluation, a Case attachment and a submission's founder message never cross a
  Company or a conversation);
- append-only for the runtime role (a conversation's own state column by
  column), nothing for the operator, and the database itself refusing unsafe
  vocabularies and shapes, a reused turn key, a second conversation for a Case and
  any cascade that would delete history;
- the service end to end: a first turn creates the conversation and its Case, a
  direct answer reaches the Case with its founder message as provenance;
- real concurrency: a first turn sent three times at once makes one
  conversation; two turns racing on one conversation commit exactly one;
- D6 is additive (existing submissions are ``structured``) and can be
  downgraded only while no conversation or assistant submission exists.
"""

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.assistant.gateway.service import AiGateway
from app.assistant.limits import UsageLimits
from app.conversations.service import (
    AskConversations,
    ConversationConflict,
    TurnRequest,
    TurnResult,
    case_request_key,
)
from app.db.models import AssistantConversation, WorkflowInstance, WorkflowSubmission
from app.repositories import assistant_conversations as conversations
from tests.evaluation.test_golden import understood
from tests.fixtures.evaluation import Artifacts, codec
from tests.fixtures.gateway import ScriptedProvider, response
from tests.knowledge.conftest import (  # noqa: F401  (pytest fixtures)
    bundle_data,
    compiled,
    synthetic_mapping_path,
    synthetic_sources,
)
from tests.tenant_isolation.conftest import (
    LegacyDatabase,
    Tenant,
    Tenants,
    count_rows,
    owners,
    run_alembic,
    scope_for,
)
from tests.tenant_isolation.migration_helpers import D5, D6, admin_scalar, b1a, upgrade
from tests.tenant_isolation.test_company_blueprint import answer, confirm
from tests.tenant_isolation.test_company_roles import set_role
from tests.tenant_isolation.test_workflow_cases import _parallel, sqlstate

TABLES = (
    "assistant_conversations",
    "assistant_turns",
    "assistant_messages",
    "assistant_turn_evaluations",
)
JSON_COLUMNS = frozenset({"checkpoint", "outcome", "record", "withdrawn_actions"})
LATE = "My employee has been late three times this month. What should I do?"
SAFE = "Thanks. HeroOS's approved approach starts with understanding what happened first."
INSUFFICIENT_PRIVILEGE = "42501"
CHECK_VIOLATION = "23514"
UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"


def insert(conn: Connection, table: str, **values: Any) -> uuid.UUID:
    """One row as the given connection (JSON columns as jsonb); returns its id."""
    values.setdefault("id", uuid.uuid4())
    names = ", ".join(values)
    params = ", ".join(f"CAST(:{k} AS jsonb)" if k in JSON_COLUMNS else f":{k}" for k in values)
    conn.execute(
        text(f"INSERT INTO {table} ({names}) VALUES ({params})"),
        {k: json.dumps(v) if k in JSON_COLUMNS and v is not None else v for k, v in values.items()},
    )
    row_id: uuid.UUID = values["id"]
    return row_id


def conversation_rows(
    conn: Connection, tenant: Tenant, *, case: uuid.UUID | None = None, key: uuid.UUID | None = None
) -> dict[str, uuid.UUID]:
    """A conversation with one turn, its two messages and its evaluation."""
    company, user = tenant.company, tenant.user
    conversation = insert(
        conn,
        "assistant_conversations",
        company_id=company,
        created_by_user_id=user,
        case_id=case,
        workflow_key=None if case is None else "disciplinary",
        revision=1,
        checkpoint={"schema": "heroos.assistant-checkpoint/1"},
    )
    turn = insert(
        conn,
        "assistant_turns",
        company_id=company,
        conversation_id=conversation,
        sequence=1,
        turn_key=key or uuid.uuid4(),
        actor_user_id=user,
    )
    common = {"company_id": company, "conversation_id": conversation, "turn_id": turn}
    founder = insert(
        conn,
        "assistant_messages",
        **common,
        sequence=1,
        role="founder",
        actor_user_id=user,
        content="[SYNTHETIC] He was late.",
    )
    heroos = insert(
        conn,
        "assistant_messages",
        **common,
        sequence=2,
        role="heroos",
        content="[SYNTHETIC] Thanks.",
        conversation_state="responded",
        outcome={"kind": "guidance", "title": "t", "message": "m", "items": []},
    )
    evaluation = insert(
        conn,
        "assistant_turn_evaluations",
        **common,
        evaluation_schema="heroos.conversation-evaluation/1",
        availability="ready",
        matter="supported",
        workflow_key="disciplinary",
        has_review_requirement=False,
        multiple_matters=False,
        snapshot_id="0123456789abcdef",
        record={"schema": "heroos.conversation-evaluation/1"},
    )
    return {
        "conversation": conversation,
        "turn": turn,
        "founder": founder,
        "heroos": heroos,
        "evaluation": evaluation,
    }


@contextmanager
def runtime_tx(runtime_engine: Engine, tenant: Tenant) -> Iterator[Connection]:
    """A runtime-role transaction bound to ``tenant`` (rolled back unless committed)."""
    with Session(runtime_engine, autoflush=False) as session:
        scope_for(session, tenant)
        yield session.connection()
        session.commit()


def refused(error: pytest.ExceptionInfo[DBAPIError]) -> str | None:
    return sqlstate(error.value)


@pytest.fixture
def seeded(admin_engine: Engine, tenants: Tenants) -> dict[str, dict[str, uuid.UUID]]:
    with admin_engine.begin() as conn:
        return {"a": conversation_rows(conn, tenants.a), "b": conversation_rows(conn, tenants.b)}


# --- isolation ----------------------------------------------------------------------------------


def test_each_company_sees_only_its_own_conversations(
    runtime_sessions: sessionmaker[Session],
    tenants: Tenants,
    seeded: dict[str, dict[str, uuid.UUID]],
) -> None:
    with runtime_sessions() as session:
        scope = scope_for(session, tenants.a)
        for table in TABLES:
            # RLS alone: an unfiltered query returns only Company A's rows.
            assert owners(session, table) == {tenants.a.company}, table
        assert count_rows(session, "assistant_messages") == 2
        # Repositories with RLS: A's own; B's are indistinguishable from missing.
        assert conversations.get_conversation(scope, seeded["a"]["conversation"]) is not None
        assert conversations.get_conversation(scope, seeded["b"]["conversation"]) is None
        assert conversations.turn_messages(scope, seeded["b"]["turn"]) == []
        assert conversations.turn_evaluation(scope, seeded["b"]["turn"]) is None


def test_the_repository_filter_alone_hides_other_companies_rows(
    admin_sessions: sessionmaker[Session],
    tenants: Tenants,
    seeded: dict[str, dict[str, uuid.UUID]],
) -> None:
    # The admin bypasses RLS: only the repositories' company filter is left.
    with admin_sessions() as session:
        scope = scope_for(session, tenants.a)
        assert conversations.get_conversation(scope, seeded["b"]["conversation"]) is None
        assert conversations.recent_messages(scope, seeded["b"]["conversation"], limit=10) == []
        assert [c.id for c in conversations.list_conversations(scope, limit=10)] == [
            seeded["a"]["conversation"]
        ]


def test_with_check_refuses_rows_for_another_company(
    runtime_engine: Engine, tenants: Tenants, seeded: dict[str, dict[str, uuid.UUID]]
) -> None:
    with pytest.raises(DBAPIError) as error, runtime_tx(runtime_engine, tenants.a) as conn:
        insert(
            conn,
            "assistant_conversations",
            company_id=tenants.b.company,
            created_by_user_id=tenants.a.user,
            checkpoint={},
        )
    assert refused(error) == INSUFFICIENT_PRIVILEGE


@pytest.mark.parametrize(
    "link",
    ["message_to_other_conversation", "case_of_other_company", "submission_message_of_other"],
)
def test_company_qualified_foreign_keys_refuse_cross_links(
    admin_engine: Engine,
    tenants: Tenants,
    seeded: dict[str, dict[str, uuid.UUID]],
    link: str,
) -> None:
    a, b = seeded["a"], seeded["b"]
    with pytest.raises(DBAPIError) as error, admin_engine.begin() as conn:
        if link == "message_to_other_conversation":
            other = conversation_rows(conn, tenants.a)
            stray = insert(
                conn,
                "assistant_turns",
                company_id=tenants.a.company,
                conversation_id=other["conversation"],
                sequence=2,
                turn_key=uuid.uuid4(),
                actor_user_id=tenants.a.user,
            )
            # A turn of conversation ``other`` under conversation ``a``.
            insert(
                conn,
                "assistant_messages",
                company_id=tenants.a.company,
                conversation_id=a["conversation"],
                turn_id=stray,
                sequence=3,
                role="founder",
                actor_user_id=tenants.a.user,
                content="x",
            )
        elif link == "case_of_other_company":
            conversation_rows(conn, tenants.a, case=tenants.b.case)
        else:
            instance = insert(
                conn,
                "workflow_instances",
                company_id=tenants.a.company,
                case_id=tenants.a.case,
                workflow_key="disciplinary",
                definition_version=2,
                revision=1,
                request_key=uuid.uuid4(),
                created_by_user_id=tenants.a.user,
            )
            insert(
                conn,
                "workflow_submissions",
                company_id=tenants.a.company,
                instance_id=instance,
                step_key="ask_heroos",
                revision=1,
                idempotency_key=uuid.uuid4(),
                submitted_by_user_id=tenants.a.user,
                origin="assistant",
                source_message_id=b["founder"],
            )
    assert refused(error) == FOREIGN_KEY_VIOLATION


# --- grants ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE assistant_turns SET sequence = 5",
        "UPDATE assistant_messages SET content = 'rewritten'",
        "UPDATE assistant_turn_evaluations SET matter = 'unclear'",
        "UPDATE assistant_conversations SET created_by_user_id = created_by_user_id",
        "UPDATE workflow_submissions SET origin = 'structured'",
        "DELETE FROM assistant_conversations",
        "DELETE FROM assistant_turns",
        "DELETE FROM assistant_messages",
        "DELETE FROM assistant_turn_evaluations",
        "TRUNCATE assistant_messages",
    ],
)
def test_the_runtime_role_only_appends(
    runtime_engine: Engine,
    tenants: Tenants,
    seeded: dict[str, dict[str, uuid.UUID]],
    statement: str,
) -> None:
    with pytest.raises(DBAPIError) as error, runtime_tx(runtime_engine, tenants.a) as conn:
        conn.execute(text(statement))
    assert refused(error) == INSUFFICIENT_PRIVILEGE


def test_a_conversation_updates_only_its_own_state(
    runtime_engine: Engine,
    admin_engine: Engine,
    tenants: Tenants,
    seeded: dict[str, dict[str, uuid.UUID]],
) -> None:
    with runtime_tx(runtime_engine, tenants.a) as conn:
        changed = conn.execute(
            text(
                "UPDATE assistant_conversations SET revision = 2, title = 'Conduct concern', "
                'checkpoint = CAST(\'{"schema": "x"}\' AS jsonb), updated_at = now()'
            )
        ).rowcount
    assert changed == 1  # Company A's only: B's row is invisible
    with admin_engine.connect() as conn:
        granted = set(
            conn.scalars(
                text(
                    "SELECT column_name FROM information_schema.column_privileges "
                    "WHERE grantee = 'heroos_app_runtime' AND privilege_type = 'UPDATE' "
                    "AND table_name = 'assistant_conversations'"
                )
            )
        )
    assert granted == {"case_id", "workflow_key", "title", "revision", "checkpoint", "updated_at"}


def test_the_operator_cannot_read_conversations(operator_engine: Engine) -> None:
    for table in TABLES:
        with pytest.raises(DBAPIError) as error, operator_engine.connect() as conn:
            conn.execute(text(f"SELECT count(*) FROM {table}"))
        assert refused(error) == INSUFFICIENT_PRIVILEGE, table


# --- what the database refuses -------------------------------------------------------------------


def _message(tenant: Tenant, ids: dict[str, uuid.UUID], **overrides: Any) -> dict[str, Any]:
    return {
        "company_id": tenant.company,
        "conversation_id": ids["conversation"],
        "turn_id": ids["turn"],
        "sequence": 3,
        "role": "heroos",
        "content": "[SYNTHETIC] reply",
        "conversation_state": "responded",
        **overrides,
    }


@pytest.mark.parametrize(
    ("table", "overrides", "expected"),
    [
        ("message", {"role": "heroos_expert"}, CHECK_VIOLATION),
        ("message", {"role": "founder", "conversation_state": None}, CHECK_VIOLATION),
        ("message", {"actor_user_id": "USER"}, CHECK_VIOLATION),
        ("message", {"conversation_state": "decided"}, CHECK_VIOLATION),
        ("message", {"content": ""}, CHECK_VIOLATION),
        ("message", {"content": "x" * 8001}, CHECK_VIOLATION),
        ("message", {"content": "bad\u0007bell"}, CHECK_VIOLATION),
        ("message", {"content": "c1\u0085control"}, CHECK_VIOLATION),
        ("message", {"sequence": 0}, CHECK_VIOLATION),
        ("message", {"sequence": 2}, UNIQUE_VIOLATION),
        ("message", {"outcome": ["not", "an", "object"]}, CHECK_VIOLATION),
        ("message", {"outcome": {"kind": "x" * 9000}}, CHECK_VIOLATION),
        ("founder", {"content": "x" * 2001}, CHECK_VIOLATION),
        ("founder", {"safe_next_step": "x"}, CHECK_VIOLATION),
        ("turn", {"sequence": 0}, CHECK_VIOLATION),
        ("turn", {"sequence": 1}, UNIQUE_VIOLATION),
        ("turn", {"turn_key": "KEY"}, UNIQUE_VIOLATION),
        ("conversation", {"checkpoint": []}, CHECK_VIOLATION),
        ("conversation", {"workflow_key": "probation"}, CHECK_VIOLATION),
        # A Case without its workflow yet is a valid conversation since D7 (chat-first Case).
        ("conversation", {"case_id": "CASE", "workflow_key": "disciplinary"}, UNIQUE_VIOLATION),
        ("conversation", {"title": "two\nlines"}, CHECK_VIOLATION),
        ("conversation", {"revision": -1}, CHECK_VIOLATION),
        ("evaluation", {"matter": "decided"}, CHECK_VIOLATION),
        ("evaluation", {"availability": "maybe"}, CHECK_VIOLATION),
        ("evaluation", {"outcome": "approved"}, CHECK_VIOLATION),
        ("evaluation", {"record": []}, CHECK_VIOLATION),
        ("evaluation", {"profile_digest": "short"}, CHECK_VIOLATION),
        ("evaluation", {"withdrawn_actions": {"opt-a": True}}, CHECK_VIOLATION),
        ("evaluation", {"withdrawn_actions": ["a", "b", "c", "d"]}, CHECK_VIOLATION),
        ("evaluation", {}, UNIQUE_VIOLATION),
    ],
)
def test_the_database_refuses_unsafe_rows(
    admin_engine: Engine,
    tenants: Tenants,
    seeded: dict[str, dict[str, uuid.UUID]],
    table: str,
    overrides: dict[str, Any],
    expected: str,
) -> None:
    a, tenant = seeded["a"], tenants.a
    values = {
        k: (
            tenant.user
            if v == "USER"
            else tenant.case
            if v == "CASE"
            else v
        )
        for k, v in overrides.items()
    }  # fmt: skip
    with admin_engine.begin() as conn:
        if values.get("case_id") == tenant.case and expected == UNIQUE_VIOLATION:
            conversation_rows(conn, tenant, case=tenant.case)
        key = uuid.uuid4()
        if values.get("turn_key") == "KEY":
            values["turn_key"] = key
            conversation_rows(conn, tenant, key=key)
    with pytest.raises(DBAPIError) as error, admin_engine.begin() as conn:
        if table == "message":
            insert(conn, "assistant_messages", **_message(tenant, a, **values))
        elif table == "founder":
            founder = {"role": "founder", "actor_user_id": tenant.user, "conversation_state": None}
            insert(conn, "assistant_messages", **_message(tenant, a, **{**founder, **values}))
        elif table == "turn":
            row = {
                "company_id": tenant.company,
                "conversation_id": a["conversation"],
                "sequence": 2,
                "turn_key": uuid.uuid4(),
                "actor_user_id": tenant.user,
            }
            insert(conn, "assistant_turns", **{**row, **values})
        elif table == "conversation":
            row = {
                "company_id": tenant.company,
                "created_by_user_id": tenant.user,
                "checkpoint": {},
                "revision": 0,
            }
            insert(conn, "assistant_conversations", **{**row, **values})
        else:
            row = {
                "company_id": tenant.company,
                "conversation_id": a["conversation"],
                "turn_id": a["turn"],
                "evaluation_schema": "heroos.conversation-evaluation/1",
                "availability": "ready",
                "matter": "supported",
                "has_review_requirement": False,
                "multiple_matters": False,
                "snapshot_id": "0123456789abcdef",
                "record": {},
            }
            insert(conn, "assistant_turn_evaluations", **{**row, **values})
    assert refused(error) == expected


def test_a_turn_key_is_unique_per_company_only(admin_engine: Engine, tenants: Tenants) -> None:
    key = uuid.uuid4()
    with admin_engine.begin() as conn:
        conversation_rows(conn, tenants.a, key=key)
        conversation_rows(conn, tenants.b, key=key)  # another Company: allowed


@pytest.mark.parametrize(
    ("origin", "message", "step"),
    [
        ("chatbot", False, "initial_facts"),
        ("assistant", False, "ask_heroos"),
        ("assistant", True, "initial_facts"),
        ("structured", True, "initial_facts"),
    ],
)
def test_a_submissions_origin_and_provenance_agree(
    admin_engine: Engine,
    tenants: Tenants,
    seeded: dict[str, dict[str, uuid.UUID]],
    origin: str,
    message: bool,
    step: str,
) -> None:
    with pytest.raises(DBAPIError) as error, admin_engine.begin() as conn:
        instance = insert(
            conn,
            "workflow_instances",
            company_id=tenants.a.company,
            case_id=tenants.a.case,
            workflow_key="disciplinary",
            definition_version=2,
            revision=1,
            request_key=uuid.uuid4(),
            created_by_user_id=tenants.a.user,
        )
        insert(
            conn,
            "workflow_submissions",
            company_id=tenants.a.company,
            instance_id=instance,
            step_key=step,
            revision=1,
            idempotency_key=uuid.uuid4(),
            submitted_by_user_id=tenants.a.user,
            origin=origin,
            source_message_id=seeded["a"]["founder"] if message else None,
        )
    assert refused(error) == CHECK_VIOLATION


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM cases WHERE id = :case",
        "DELETE FROM assistant_conversations WHERE id = :conversation",
        "DELETE FROM assistant_turns WHERE id = :turn",
    ],
)
def test_nothing_cascades_into_conversation_history(
    admin_engine: Engine, tenants: Tenants, statement: str
) -> None:
    with admin_engine.begin() as conn:
        ids = conversation_rows(conn, tenants.a, case=tenants.a.case)
    with pytest.raises(DBAPIError) as error, admin_engine.begin() as conn:
        conn.execute(text(statement), {"case": tenants.a.case, **ids})
    assert refused(error) == FOREIGN_KEY_VIOLATION


# --- the service on PostgreSQL ---------------------------------------------------------------


@pytest.fixture
def ready(runtime_engine: Engine, operator_engine: Engine, tenants: Tenants) -> Tenants:
    """Company A: alice is an administrator; its jurisdiction is confirmed."""
    set_role(operator_engine, tenants.a.company, tenants.a.membership, "company_admin")
    answer(runtime_engine, tenants.a, "other", "[SYNTHETIC] Licensing authority")
    confirm(operator_engine, tenants.a, "uae_federal", "other", "[SYNTHETIC] Licensing authority")
    return tenants


@pytest.fixture
def artifacts(bundle_data: dict[str, Any]) -> Artifacts:  # noqa: F811
    return Artifacts(bundle_data)


def late(message: str = LATE, turn: int = 0) -> dict[str, Any]:
    return understood(message, pathway="less_serious", topics=["workplace_reminder"], turn=turn)


def service(artifacts: Artifacts, understanding: Any) -> AskConversations:
    provider = ScriptedProvider(understanding, response(SAFE, ["q1"]))
    gateway = AiGateway(
        enabled=True,
        provider=provider,
        approval="TEST-APPROVAL-1",
        allow_development_knowledge=True,
        limits=UsageLimits(account_limit=100, global_per_minute=100, global_per_day=1000),
        evaluation=artifacts.service(),
        continuations=codec(),
    )
    return AskConversations(gateway, policy="disabled", rules=None)


def turn(
    runtime_sessions: sessionmaker[Session],
    tenant: Tenant,
    artifacts: Artifacts,
    message: str,
    understanding: Any,
    *,
    key: uuid.UUID | None = None,
    conversation: uuid.UUID | None = None,
    revision: int = 0,
) -> TurnResult:
    request = TurnRequest(message, key or uuid.uuid4(), conversation, revision)
    with runtime_sessions() as session:
        return service(artifacts, understanding).run_turn(session, tenant.context, request)


def test_a_persisted_conversation_on_postgresql(
    runtime_sessions: sessionmaker[Session],
    admin_sessions: sessionmaker[Session],
    ready: Tenants,
    artifacts: Artifacts,
) -> None:
    first = turn(runtime_sessions, ready.a, artifacts, LATE, late())
    second = turn(
        runtime_sessions,
        ready.a,
        artifacts,
        "Yes.",
        late("Yes.", 1),
        conversation=first.conversation_id,
        revision=1,
    )
    assert first.case_id is not None and second.case_id == first.case_id
    with admin_sessions() as session:
        conversation = session.get(AssistantConversation, first.conversation_id)
        assert conversation is not None and conversation.company_id == ready.a.company
        assert conversation.revision == 2
        instance = session.scalar(
            select(WorkflowInstance).where(WorkflowInstance.case_id == first.case_id)
        )
        assert instance is not None
        assert instance.request_key == case_request_key(first.conversation_id)
        narrative, answer = session.scalars(
            select(WorkflowSubmission).order_by(WorkflowSubmission.revision)
        ).all()
        # Each founder message is a real, same-Company reference (enforced here): the first
        # is the Case's narrative (chat-first Case), the second answers HeroOS's question.
        assert (narrative.origin, narrative.source_message_id) == ("assistant", first.founder.id)
        assert (answer.origin, answer.source_message_id) == ("assistant", second.founder.id)

        def facts(submission: WorkflowSubmission) -> list[tuple[str, object]]:
            rows = session.execute(
                text("SELECT fact_key, value FROM case_facts WHERE submission_id = :s"),
                {"s": submission.id},
            ).all()
            return [(k, v) for k, v in rows]

        assert facts(narrative) == [("incident.narrative", LATE)]
        assert facts(answer) == [("context.policy_awareness", "yes")]
        assert session.scalar(text("SELECT count(*) FROM case_subjects")) == 2  # the seeds only
        assert session.scalar(text("SELECT count(*) FROM workflow_progress_events")) == 0


def test_a_first_turn_sent_three_times_at_once_makes_one_conversation(
    runtime_sessions: sessionmaker[Session],
    admin_engine: Engine,
    ready: Tenants,
    artifacts: Artifacts,
) -> None:
    key = uuid.uuid4()
    results = _parallel(
        [
            lambda: turn(runtime_sessions, ready.a, artifacts, LATE, late(), key=key)
            for _ in range(3)
        ]
    )
    assert len({r.conversation_id for r in results}) == 1
    assert len({r.case_id for r in results}) == 1
    assert sorted(r.replayed for r in results) == [False, True, True]
    with admin_engine.connect() as conn:
        for table, expected in (
            ("assistant_conversations", 1),
            ("assistant_turns", 1),
            ("assistant_messages", 2),
            ("workflow_instances", 1),
        ):
            assert conn.scalar(text(f"SELECT count(*) FROM {table}")) == expected, table


def test_two_turns_racing_on_one_conversation_commit_exactly_one(
    runtime_sessions: sessionmaker[Session],
    admin_engine: Engine,
    ready: Tenants,
    artifacts: Artifacts,
) -> None:
    first = turn(runtime_sessions, ready.a, artifacts, LATE, late())

    def racing(message: str) -> Any:
        try:
            return turn(
                runtime_sessions,
                ready.a,
                artifacts,
                message,
                late(message, 1),
                conversation=first.conversation_id,
                revision=1,
            )
        except ConversationConflict as conflict:
            return conflict

    results = _parallel([lambda: racing("Yes."), lambda: racing("He was late again.")])
    assert sum(isinstance(r, ConversationConflict) for r in results) == 1
    with admin_engine.connect() as conn:
        assert conn.scalar(text("SELECT revision FROM assistant_conversations")) == 2
        assert conn.scalar(text("SELECT count(*) FROM assistant_turns")) == 2
        assert conn.scalar(text("SELECT count(*) FROM assistant_messages")) == 4


# --- the migration -------------------------------------------------------------------------------


def test_d6_is_additive_and_downgrades_only_while_empty(legacy_db: LegacyDatabase) -> None:
    b1a(legacy_db)
    upgrade(legacy_db, D5)
    ids = {"company": legacy_db.company_a, "user": legacy_db.alice}
    engine = create_engine(legacy_db.admin_url)
    try:
        with engine.begin() as conn:
            case = conn.scalar(
                text(
                    "INSERT INTO cases (id, company_id, case_type, title) VALUES "
                    "(gen_random_uuid(), :company, 'disciplinary', '[SYNTHETIC] D6') RETURNING id"
                ),
                ids,
            )
            instance = insert(
                conn,
                "workflow_instances",
                company_id=legacy_db.company_a,
                case_id=case,
                workflow_key="disciplinary",
                definition_version=2,
                revision=1,
                request_key=uuid.uuid4(),
                created_by_user_id=legacy_db.alice,
            )
            insert(
                conn,
                "workflow_submissions",
                company_id=legacy_db.company_a,
                instance_id=instance,
                step_key="initial_facts",
                revision=1,
                idempotency_key=uuid.uuid4(),
                submitted_by_user_id=legacy_db.alice,
            )
        upgrade(legacy_db, D6)
        assert admin_scalar(legacy_db, "SELECT heroos_schema_contract()") == 9
        # Every existing submission was saved through a form.
        assert (
            admin_scalar(
                legacy_db,
                "SELECT count(*) FROM workflow_submissions "
                "WHERE origin = 'structured' AND source_message_id IS NULL",
            )
            == 1
        )
        # No conversation yet: reversible to D5 (contract 8), then re-applied.
        down = run_alembic(legacy_db.admin_url, "downgrade", D5)
        assert down.returncode == 0, down.stderr
        assert admin_scalar(legacy_db, "SELECT heroos_schema_contract()") == 8
        assert admin_scalar(legacy_db, "SELECT to_regclass('public.assistant_turns')") is None
        upgrade(legacy_db, D6)
        with engine.begin() as conn:
            insert(
                conn,
                "assistant_conversations",
                company_id=legacy_db.company_a,
                created_by_user_id=legacy_db.alice,
                checkpoint={},
            )
    finally:
        engine.dispose()
    refused_down = run_alembic(legacy_db.admin_url, "downgrade", D5)
    assert refused_down.returncode != 0
    assert "Ask HeroOS conversations exist" in refused_down.stderr
    assert admin_scalar(legacy_db, "SELECT version_num FROM alembic_version") == D6
    assert admin_scalar(legacy_db, "SELECT heroos_schema_contract()") == 9
