"""Persisted Ask HeroOS turns on SQLite stand-ins (RLS, grants and races: tests/tenant_isolation).

The gateway is real (M2-NEW-05/06) on the fictional knowledge and execution
content; only the provider is scripted, so every test fixes what the model
proposes and proves what the server stores.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.assistant.gateway.service import AiGateway
from app.assistant.limits import UsageLimits
from app.auth.models import AuthenticatedCompanyContext
from app.conversations.service import AskConversations, TurnRequest, TurnResult
from app.db.base import Base
from app.db.models import (
    AssistantConversation,
    AssistantMessage,
    AssistantTurn,
    AssistantTurnEvaluation,
    Case,
    CaseFact,
    Membership,
    User,
    UserIdentity,
    WorkflowDecisionRecord,
    WorkflowEvaluation,
    WorkflowInstance,
    WorkflowProgressEvent,
    WorkflowSubmission,
)
from app.workflows.progression.bundle import RuleBundle
from tests.auth.conftest import (  # noqa: F401  (pytest fixtures)
    SeedData,
    _isolate_auth_environment,
    cognito_provider,
    jwk_client,
    jwks,
    make_cognito_token,
    seed,
    session_factory,
    signing_key,
)
from tests.auth.test_company_admin_api import make_admin
from tests.auth.test_intake_api import confirm_jurisdiction
from tests.auth.test_workflow_api import sessions  # noqa: F401  (pytest fixture)
from tests.fixtures.evaluation import Artifacts, codec
from tests.fixtures.gateway import ScriptedProvider, response
from tests.knowledge.conftest import (  # noqa: F401  (pytest fixtures)
    bundle_data,
    compiled,
    synthetic_mapping_path,
    synthetic_sources,
)

SAFE = "Thanks. HeroOS's approved approach starts with understanding what happened first."
# SAFE asks nothing, so when a deterministic check needs the policy answer the server asks
# it in its own words (and only then does it count as asked).
SAFE_ASKING_POLICY = f"{SAFE} Could you tell me more about this: standard explained?"
ASSISTANT_TABLES = (AssistantConversation, AssistantTurn, AssistantMessage, AssistantTurnEvaluation)
COUNTED = (
    *ASSISTANT_TABLES,
    Case,
    WorkflowInstance,
    WorkflowSubmission,
    CaseFact,
    WorkflowEvaluation,
    WorkflowProgressEvent,
    WorkflowDecisionRecord,
)
UNSET: Any = object()


@pytest.fixture
def stored_sessions(sessions: sessionmaker[Session]) -> sessionmaker[Session]:  # noqa: F811
    """The workflow tables plus the conversation tables (nothing seeded beyond Companies)."""
    engine = sessions.kw["bind"]
    Base.metadata.create_all(engine, tables=[model.__table__ for model in ASSISTANT_TABLES])
    with sessions() as session:
        # SQLite stand-in for the case_subjects table (never written: no CaseSubject is created).
        session.execute(
            text(
                "CREATE TABLE case_subjects (id CHAR(32) PRIMARY KEY, "
                "company_id CHAR(32) NOT NULL, subject_type VARCHAR(40) NOT NULL, "
                "display_name VARCHAR(200) NOT NULL, "
                "reference VARCHAR(100), created_at DATETIME, updated_at DATETIME)"
            )
        )
        session.commit()
    return sessions


@pytest.fixture
def db(stored_sessions: sessionmaker[Session], seed: SeedData) -> sessionmaker[Session]:  # noqa: F811
    """Company A: alice is an administrator and the jurisdiction is confirmed (UAE Federal)."""
    make_admin(stored_sessions, seed.company_a, seed.alice)
    confirm_jurisdiction(stored_sessions, seed.company_a, "uae_federal")
    return stored_sessions


@pytest.fixture
def artifacts(bundle_data: dict[str, Any]) -> Artifacts:  # noqa: F811
    return Artifacts(bundle_data)


@pytest.fixture
def alice_context(seed: SeedData) -> AuthenticatedCompanyContext:  # noqa: F811
    return AuthenticatedCompanyContext(
        user_id=seed.alice,
        company_id=seed.company_a,
        membership_id=seed.alice_membership_a,
        identity_id=seed.alice_identity,
    )


def add_admin(db: sessionmaker[Session], company: uuid.UUID) -> AuthenticatedCompanyContext:
    """Another active administrator of ``company``."""
    with db() as session:
        user = User()
        session.add(user)
        session.flush()
        identity = UserIdentity(user_id=user.id, issuer="urn:heroos:test", subject=str(user.id))
        membership = Membership(company_id=company, user_id=user.id, role="company_admin")
        session.add_all([identity, membership])
        session.commit()
        return AuthenticatedCompanyContext(
            user_id=user.id,
            company_id=company,
            membership_id=membership.id,
            identity_id=identity.id,
        )


def gateway(artifacts_service: Any, provider: ScriptedProvider) -> AiGateway:
    return AiGateway(
        enabled=True,
        provider=provider,
        approval="TEST-APPROVAL-1",
        allow_development_knowledge=True,
        limits=UsageLimits(account_limit=100, global_per_minute=100, global_per_day=1000),
        evaluation=artifacts_service,
        continuations=codec(),
    )


class Founder:
    """One administrator's persisted Ask HeroOS conversation (the provider is scripted)."""

    def __init__(
        self,
        db: sessionmaker[Session],
        artifacts: Artifacts,
        context: AuthenticatedCompanyContext,
        *,
        rules: RuleBundle | None = None,
    ) -> None:
        self.db = db
        self.evaluation = artifacts.service()
        self.context = context
        self.rules = rules
        self.conversation_id: uuid.UUID | None = None
        self.revision = 0
        self.provider: ScriptedProvider | None = None
        self.turns = 0

    def service(self, provider: ScriptedProvider) -> AskConversations:
        return AskConversations(
            gateway(self.evaluation, provider), policy="disabled", rules=self.rules
        )

    def say(
        self,
        message: str,
        understanding: Any,
        reply: Any = None,
        *,
        turn_key: uuid.UUID | None = None,
        conversation_id: Any = UNSET,
        revision: int | None = None,
    ) -> TurnResult:
        self.provider = ScriptedProvider(understanding, reply or response(SAFE, ["q1"]))
        target = self.conversation_id if conversation_id is UNSET else conversation_id
        request = TurnRequest(
            message,
            turn_key or uuid.uuid4(),
            target,
            (self.revision if target is not None else 0) if revision is None else revision,
        )
        with self.db() as session:
            result = self.service(self.provider).run_turn(session, self.context, request)
        self.conversation_id = result.conversation_id
        self.revision = result.sequence
        if not result.replayed:
            self.turns += 1
        return result


def counts(db: sessionmaker[Session]) -> dict[str, int]:
    with db() as session:
        return {
            model.__tablename__: session.scalar(select(func.count()).select_from(model)) or 0
            for model in COUNTED
        }
