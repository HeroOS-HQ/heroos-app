"""Ask HeroOS's deterministic outcome (M2-NEW-06) through the real application.

Same harness as test_gateway_api.py, with the fictional execution content
installed: the outcome reaches the browser only as the server's card (kind,
title, message, one line per step), never as a rule, Condition, binding,
profile or trace; the browser can't send one; and a turn records no workflow
action (M2-NEW-07 keeps the conversation; tests/conversations).
"""

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.assistant.gateway.service import AiGateway
from app.assistant.limits import UsageLimits
from app.auth.dependencies import get_authentication_provider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.db.models import CaseFact
from app.db.session import get_db
from app.main import create_app
from tests.auth.conftest import SeedData
from tests.auth.test_company_api import staging_settings
from tests.auth.test_intake_api import confirm_jurisdiction
from tests.auth.test_workflow_api import (  # noqa: F401  (pytest fixtures)
    admin_alice,
    alice,
    bob,
    sessions,
)
from tests.conversations.conftest import counts, stored_sessions  # noqa: F401  (fixture)
from tests.fixtures.evaluation import Artifacts, codec
from tests.fixtures.gateway import ScriptedProvider, response, understanding
from tests.knowledge.conftest import (  # noqa: F401  (pytest fixtures)
    bundle_data,
    compiled,
    synthetic_mapping_path,
    synthetic_sources,
)

MESSAGE = "[SYNTHETIC] I think she took money from the till. Can I fire her today?"
OUTCOME_FIELDS = {"kind", "title", "message", "items"}


def client_for(
    sessions: sessionmaker[Session],  # noqa: F811
    provider: CognitoAccessTokenProvider,
    artifacts: Artifacts,
    chat: ScriptedProvider,
) -> TestClient:
    app = create_app(staging_settings())
    app.state.ai_gateway = AiGateway(
        enabled=True,
        provider=chat,
        approval="TEST-APPROVAL-1",
        allow_development_knowledge=True,
        limits=UsageLimits(account_limit=100, global_per_minute=100, global_per_day=1000),
        evaluation=artifacts.service(),
        continuations=codec(),
    )

    def _db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_authentication_provider] = lambda: provider
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def dismissal(turn: int = 0) -> ScriptedProvider:
    data = understanding(pathway="serious", topics=["dismissal_without_notice"])
    data["requested_actions"] = [
        {"action": "opt-dismissal", "source_turn": turn, "support_excerpt": "fire her today"}
    ]
    return ScriptedProvider(data, response("That needs looking into fairly first."))


@pytest.fixture
def artifacts(bundle_data: dict[str, Any]) -> Artifacts:  # noqa: F811
    return Artifacts(bundle_data)


def post(
    client: TestClient, headers: dict[str, str], company: Any, message: str = MESSAGE, **body: Any
) -> Any:
    request = {"message": message, "turn_key": str(uuid.uuid4()), "expected_revision": 0, **body}
    return client.post(f"/companies/{company}/assistant/messages", headers=headers, json=request)


def test_the_outcome_is_the_servers_card_and_nothing_internal(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    artifacts: Artifacts,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    confirm_jurisdiction(stored_sessions, seed.company_a, "uae_federal")
    client = client_for(stored_sessions, cognito_provider, artifacts, dismissal())
    answered = post(client, admin_alice, seed.company_a)
    assert answered.status_code == 200
    outcome = answered.json()["messages"][1]["outcome"]
    assert set(outcome) == OUTCOME_FIELDS
    assert outcome["kind"] == "expert_review"
    assert outcome["title"] == "Expert Review"
    snapshot = artifacts.snapshot()
    for private in (
        "EX-",
        "opt-",
        "rule:",
        "fictional_cap",
        "synthetic-execution",
        "synthetic-progression",
        "review_required",
        "escalate",
        "condition",
        snapshot.id,
        "provenance",
        "two_state",
        "engine",
        "heroos.conversation-evaluation",
        "continuation",
    ):
        assert private not in answered.text, private
    # The conversation is kept with its Case. Its only fact is the founder's own narrative
    # (chat-first Case); no workflow action, other fact, decision or document is.
    stored = counts(stored_sessions)
    assert stored["workflow_submissions"] == stored["case_facts"] == 1
    assert stored["workflow_progress_events"] == stored["workflow_decision_records"] == 0
    with stored_sessions() as db:
        (fact,) = db.scalars(select(CaseFact)).all()
    assert (fact.fact_key, fact.value) == ("incident.narrative", MESSAGE)


def test_a_technical_unavailability_is_not_an_hr_outcome(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    artifacts: Artifacts,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    confirm_jurisdiction(stored_sessions, seed.company_a, "uae_federal")
    artifacts.profile["workflows"][0]["knowledge_runtime_digest"] = "f" * 64
    client = client_for(stored_sessions, cognito_provider, artifacts, dismissal())
    body = post(client, admin_alice, seed.company_a).json()
    outcome = body["messages"][1]["outcome"]
    assert outcome["kind"] == "unavailable"
    assert outcome["title"] == "Checks unavailable" and outcome["items"] == []
    # Technical: never the Case's lifecycle.
    status = body["conversation"]["status"]
    assert (status["lifecycle"], status["checks"]) == ("in_progress", "unavailable")


def test_the_conversation_continues_from_the_server_not_a_browser_token(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    artifacts: Artifacts,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    """No continuation, no history: the next turn starts from the stored conversation."""
    confirm_jurisdiction(stored_sessions, seed.company_a, "uae_federal")
    first = post(
        client_for(stored_sessions, cognito_provider, artifacts, dismissal()),
        admin_alice,
        seed.company_a,
    )
    conversation = first.json()["conversation"]
    chat = dismissal(turn=1)
    answered = post(
        client_for(stored_sessions, cognito_provider, artifacts, chat),
        admin_alice,
        seed.company_a,
        "I still want to fire her today.",
        conversation_id=conversation["id"],
        expected_revision=conversation["revision"],
    )
    assert answered.status_code == 200
    assert answered.json()["messages"][1]["outcome"]["kind"] == "expert_review"
    sent = chat.phase("understanding")[0].data["founder_messages"]
    assert [m["text"] for m in sent] == [MESSAGE, "I still want to fire her today."]
