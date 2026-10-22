"""Ask HeroOS (M2-NEW-05, persistent since M2-NEW-07) on real PostgreSQL, as the runtime role.

The production application (``create_app`` with staging settings), Cognito-
shaped tokens and pooled runtime connections, with the fictional knowledge
bundle and a scripted provider. Proves on PostgreSQL what SQLite can't:

- the Blueprint context is read under the caller's own Company scope;
- another Company's administrator, and a member, are refused before any model
  request; another Company's conversation is indistinguishable from none;
- no transaction is open, and so no conversation or WorkflowInstance row is
  locked, while the provider is waited on: not for a first turn, not for a
  turn on a conversation with a Case; no tenant context survives the turn;
- a first turn sent three times at once through the API is one conversation,
  one turn, two messages, one Case and one evaluation; the provider is asked
  once per request that reached it, and the retries replay.
"""

import uuid
from collections.abc import Generator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.assistant.provider import Completion
from app.auth.dependencies import get_authentication_provider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.core.config import Settings
from app.db.session import get_db
from app.knowledge.bundle import KnowledgeBundle
from app.main import create_app
from tests.auth.conftest import TEST_APP_CLIENT_ID, TEST_COGNITO_ISSUER
from tests.fixtures.gateway import ScriptedProvider, gateway, response, understanding
from tests.knowledge.conftest import (  # noqa: F401  (pytest fixtures)
    bundle,
    bundle_file,
    compiled,
    synthetic_mapping_path,
    synthetic_sources,
)
from tests.tenant_isolation.conftest import TenantDatabase, Tenants, count_rows, tenant_setting
from tests.tenant_isolation.test_api_routes import (  # noqa: F401  (pytest fixtures)
    ALICE,
    BOB,
    FORBIDDEN,
    auth,
    provider,
    signing_key,
)
from tests.tenant_isolation.test_company_roles import set_role
from tests.tenant_isolation.test_workflow_cases import _parallel

MESSAGE = "[SYNTHETIC] An employee keeps arriving late."


class Watching(ScriptedProvider):
    """Records, at each model request, how the runtime role's connections stand."""

    def __init__(self, admin_engine: Engine, runtime_role: str, *args: Any) -> None:
        super().__init__(*args)
        self.admin_engine = admin_engine
        self.runtime_role = runtime_role
        self.states: list[list[str]] = []
        self.locks: list[int] = []

    def complete_json(self, system: str, turns: Any, **kwargs: Any) -> Completion:
        with self.admin_engine.connect() as conn:
            states = conn.execute(
                text("SELECT state FROM pg_stat_activity WHERE usename = :role"),
                {"role": self.runtime_role},
            ).scalars()
            self.states.append([s or "" for s in states])
            # Row locks the runtime role holds on the conversation or the workflow instance.
            self.locks.append(
                conn.scalar(
                    text(
                        "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
                        "WHERE a.usename = :role AND l.relation IN "
                        "('assistant_conversations'::regclass, 'workflow_instances'::regclass) "
                        "AND l.mode = 'RowShareLock'"
                    ),
                    {"role": self.runtime_role},
                )
            )
        return super().complete_json(system, turns, **kwargs)


def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        heroos_env="staging",
        database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
        heroos_auth_provider="cognito",
        heroos_cognito_issuer=TEST_COGNITO_ISSUER,
        heroos_cognito_app_client_id=TEST_APP_CLIENT_ID,
    )


@pytest.fixture
def http_engine(tenant_database: TenantDatabase) -> Iterator[Engine]:
    # Several connections, so concurrent requests really run concurrently.
    engine = create_engine(
        tenant_database.runtime_url, pool_size=4, max_overflow=0, pool_pre_ping=True
    )
    yield engine
    engine.dispose()


@pytest.fixture
def http_sessions(http_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=http_engine, autoflush=False)


def watching(admin_engine: Engine, tenant_database: TenantDatabase) -> Watching:
    return Watching(
        admin_engine,
        tenant_database.runtime_role,
        understanding(pathway="less_serious", topics=["workplace_reminder"]),
        response("Thanks. Has the expected standard been explained?"),
    )


@pytest.fixture
def chat(admin_engine: Engine, tenant_database: TenantDatabase) -> Watching:
    return watching(admin_engine, tenant_database)


def client_for(
    sessions: sessionmaker[Session],
    provider: CognitoAccessTokenProvider,  # noqa: F811
    bundle: KnowledgeBundle,  # noqa: F811
    chat: ScriptedProvider,
) -> TestClient:
    app = create_app(settings())
    app.state.ai_gateway = gateway(bundle, chat)

    def _db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_authentication_provider] = lambda: provider
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


@pytest.fixture
def client(
    http_sessions: sessionmaker[Session],
    provider: CognitoAccessTokenProvider,  # noqa: F811
    bundle: KnowledgeBundle,  # noqa: F811
    chat: Watching,
) -> TestClient:
    return client_for(http_sessions, provider, bundle, chat)


def ask(
    client: TestClient,
    headers: dict[str, str],
    company: Any,
    *,
    key: str | None = None,
    conversation: str | None = None,
    revision: int = 0,
) -> Any:
    body: dict[str, Any] = {
        "message": MESSAGE,
        "turn_key": key or str(uuid.uuid4()),
        "expected_revision": revision,
    }
    if conversation is not None:
        body["conversation_id"] = conversation
    return client.post(f"/companies/{company}/assistant/messages", headers=headers, json=body)


def no_transaction_while_waiting(chat: Watching) -> None:
    assert chat.states and len(chat.states) == len(chat.locks)
    for states in chat.states:
        assert not any(state.startswith("idle in transaction") for state in states), states
        assert "active" not in states
    assert set(chat.locks) == {0}


def test_no_row_is_locked_while_the_model_answers(
    client: TestClient,
    chat: Watching,
    http_sessions: sessionmaker[Session],
    provider: CognitoAccessTokenProvider,  # noqa: F811
    bundle: KnowledgeBundle,  # noqa: F811
    admin_engine: Engine,
    admin_sessions: sessionmaker[Session],
    operator_engine: Engine,
    tenant_database: TenantDatabase,
    tenants: Tenants,
    auth: Any,  # noqa: F811
) -> None:
    set_role(operator_engine, tenants.a.company, tenants.a.membership, "company_admin")
    first = ask(client, auth(ALICE), tenants.a.company)
    assert first.status_code == 200
    no_transaction_while_waiting(chat)
    # The Company context came from the caller's own Blueprint (RLS-scoped).
    company_context = chat.phase("response")[0].data["company_context"]
    assert company_context["employment_jurisdiction"] == "not confirmed yet"
    conversation = first.json()["conversation"]
    assert conversation["case"] is not None
    # A turn on a conversation with a Case: still nothing locked while the model answers.
    again = watching(admin_engine, tenant_database)
    second = ask(
        client_for(http_sessions, provider, bundle, again),
        auth(ALICE),
        tenants.a.company,
        conversation=conversation["id"],
        revision=conversation["revision"],
    )
    assert second.status_code == 200
    no_transaction_while_waiting(again)
    with http_sessions() as db:
        assert tenant_setting(db) in (None, "")
    with admin_sessions() as db:
        assert count_rows(db, "assistant_turns") == 2
        assert count_rows(db, "assistant_messages") == 4
        assert count_rows(db, "workflow_progress_events") == 0


def test_another_companys_administrator_never_reaches_the_model(
    client: TestClient,
    chat: Watching,
    operator_engine: Engine,
    tenants: Tenants,
    auth: Any,  # noqa: F811
) -> None:
    set_role(operator_engine, tenants.b.company, tenants.b.membership, "company_admin")
    refused = ask(client, auth(BOB), tenants.a.company)
    assert (refused.status_code, refused.json()) == FORBIDDEN
    # A member (not an administrator) of the Company itself is refused too.
    member = ask(client, auth(ALICE), tenants.a.company)
    assert (member.status_code, member.json()) == FORBIDDEN
    assert chat.calls == []


def test_another_companys_conversation_is_indistinguishable_from_none(
    client: TestClient,
    chat: Watching,
    operator_engine: Engine,
    admin_sessions: sessionmaker[Session],
    tenants: Tenants,
    auth: Any,  # noqa: F811
) -> None:
    set_role(operator_engine, tenants.a.company, tenants.a.membership, "company_admin")
    set_role(operator_engine, tenants.b.company, tenants.b.membership, "company_admin")
    conversation = ask(client, auth(ALICE), tenants.a.company).json()["conversation"]["id"]
    base = f"/companies/{tenants.b.company}/assistant/conversations"
    assert client.get(f"{base}/{conversation}", headers=auth(BOB)).status_code == 404
    assert client.get(f"{base}/{conversation}/messages", headers=auth(BOB)).status_code == 404
    assert client.get(base, headers=auth(BOB)).json() == {"items": [], "next_before": None}
    calls = len(chat.calls)
    hijack = ask(client, auth(BOB), tenants.b.company, conversation=conversation, revision=1)
    assert hijack.status_code == 404
    assert len(chat.calls) == calls  # refused before any model request
    with admin_sessions() as db:
        assert count_rows(db, "assistant_turns") == 1


def test_a_first_turn_sent_three_times_at_once_through_the_api_is_one(
    client: TestClient,
    chat: Watching,
    admin_sessions: sessionmaker[Session],
    operator_engine: Engine,
    tenants: Tenants,
    auth: Any,  # noqa: F811
) -> None:
    set_role(operator_engine, tenants.a.company, tenants.a.membership, "company_admin")
    key = str(uuid.uuid4())
    responses = _parallel(
        [lambda: ask(client, auth(ALICE), tenants.a.company, key=key) for _ in range(3)]
    )
    assert [r.status_code for r in responses] == [200, 200, 200]
    bodies = [r.json() for r in responses]
    assert len({b["conversation"]["id"] for b in bodies}) == 1
    assert sorted(b["replayed"] for b in bodies) == [False, True, True]
    assert all(b["messages"] == bodies[0]["messages"] for b in bodies)
    with admin_sessions() as db:
        assert count_rows(db, "assistant_conversations") == 1
        assert count_rows(db, "assistant_turns") == 1
        assert count_rows(db, "assistant_messages") == 2
        assert count_rows(db, "assistant_turn_evaluations") == 1
        assert count_rows(db, "workflow_instances") == 1
