"""Ask HeroOS's AI gateway (M2-NEW-05) on real PostgreSQL with RLS, as the runtime role.

The production application (``create_app`` with staging settings), Cognito-
shaped tokens and one pooled runtime connection, with the fictional knowledge
bundle and a scripted provider. Proves on PostgreSQL what SQLite can't:

- the Blueprint context is read under the caller's own Company scope;
- another Company's administrator is refused before any model request;
- no transaction is open while the provider is waited on (the connection is
  released first), and no tenant context survives the turn;
- a turn writes nothing.
"""

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

TABLES = ("cases", "case_facts", "workflow_instances", "workflow_submissions")


class Watching(ScriptedProvider):
    """Records, at each model request, how the runtime role's connections stand."""

    def __init__(self, admin_engine: Engine, runtime_role: str, *args: Any) -> None:
        super().__init__(*args)
        self.admin_engine = admin_engine
        self.runtime_role = runtime_role
        self.states: list[list[str]] = []

    def complete_json(self, system: str, turns: Any, **kwargs: Any) -> Completion:
        with self.admin_engine.connect() as conn:
            states = conn.execute(
                text("SELECT state FROM pg_stat_activity WHERE usename = :role"),
                {"role": self.runtime_role},
            ).scalars()
            self.states.append([s or "" for s in states])
        return super().complete_json(system, turns, **kwargs)


@pytest.fixture
def http_sessions(tenant_database: TenantDatabase) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        tenant_database.runtime_url, pool_size=1, max_overflow=0, pool_pre_ping=True
    )
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


@pytest.fixture
def chat(admin_engine: Engine, tenant_database: TenantDatabase) -> Watching:
    return Watching(
        admin_engine,
        tenant_database.runtime_role,
        understanding(pathway="less_serious", topics=["workplace_reminder"]),
        response("Thanks. Has the expected standard been explained?"),
    )


@pytest.fixture
def client(
    http_sessions: sessionmaker[Session],
    provider: CognitoAccessTokenProvider,  # noqa: F811
    bundle: KnowledgeBundle,  # noqa: F811
    chat: Watching,
) -> TestClient:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        heroos_env="staging",
        database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
        heroos_auth_provider="cognito",
        heroos_cognito_issuer=TEST_COGNITO_ISSUER,
        heroos_cognito_app_client_id=TEST_APP_CLIENT_ID,
    )
    app = create_app(settings)
    app.state.ai_gateway = gateway(bundle, chat)

    def _db() -> Generator[Session, None, None]:
        with http_sessions() as db:
            yield db

    app.dependency_overrides[get_authentication_provider] = lambda: provider
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def ask(client: TestClient, headers: dict[str, str], company: Any) -> Any:
    return client.post(
        f"/companies/{company}/assistant/messages",
        headers=headers,
        json={"message": "[SYNTHETIC] An employee keeps arriving late."},
    )


def test_a_turn_holds_no_transaction_while_the_model_answers(
    client: TestClient,
    chat: Watching,
    http_sessions: sessionmaker[Session],
    admin_sessions: sessionmaker[Session],
    operator_engine: Engine,
    tenants: Tenants,
    auth: Any,  # noqa: F811
) -> None:
    set_role(operator_engine, tenants.a.company, tenants.a.membership, "company_admin")
    with admin_sessions() as db:
        before = {table: count_rows(db, table) for table in TABLES}
    answered = ask(client, auth(ALICE), tenants.a.company)
    assert answered.status_code == 200
    # Two model requests; at each, the runtime connection was idle (released), never in a
    # transaction (which would hold locks and the pool while the provider answers).
    assert len(chat.states) == 2
    for states in chat.states:
        assert not any(state.startswith("idle in transaction") for state in states), states
        assert "active" not in states
    # The Company context came from the caller's own Blueprint (RLS-scoped).
    company_context = chat.phase("response")[0].data["company_context"]
    assert company_context["employment_jurisdiction"] == "not confirmed yet"
    with http_sessions() as db:
        assert tenant_setting(db) in (None, "")
    with admin_sessions() as db:
        assert {table: count_rows(db, table) for table in TABLES} == before


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
