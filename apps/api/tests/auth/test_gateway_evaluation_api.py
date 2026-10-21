"""Ask HeroOS's deterministic outcome (M2-NEW-06) through the real application.

Same harness as test_gateway_api.py, with the fictional execution content
installed: the outcome reaches the browser only as the server's card (kind,
title, message, one line per step), never as a rule, Condition, binding,
profile or trace; the browser can't send one; and a turn writes nothing.
"""

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.assistant.gateway.service import AiGateway
from app.assistant.limits import UsageLimits
from app.auth.dependencies import get_authentication_provider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.db.session import get_db
from app.main import create_app
from tests.auth.conftest import SeedData
from tests.auth.test_assistant_api import counts
from tests.auth.test_company_api import staging_settings
from tests.auth.test_intake_api import confirm_jurisdiction
from tests.auth.test_workflow_api import (  # noqa: F401  (pytest fixtures)
    admin_alice,
    alice,
    bob,
    sessions,
)
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


def test_the_outcome_is_the_servers_card_and_nothing_internal(
    sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    artifacts: Artifacts,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    confirm_jurisdiction(sessions, seed.company_a, "uae_federal")
    client = client_for(sessions, cognito_provider, artifacts, dismissal())
    before = counts(sessions)
    answered = client.post(
        f"/companies/{seed.company_a}/assistant/messages",
        headers=admin_alice,
        json={"message": MESSAGE},
    )
    assert answered.status_code == 200
    body = answered.json()
    assert set(body["outcome"]) == OUTCOME_FIELDS
    assert body["outcome"]["kind"] == "expert_review"
    assert body["outcome"]["title"] == "Expert Review"
    assert body["continuation"].startswith("e1.")
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
    ):
        assert private not in answered.text, private
    # Nothing was created or changed: no Case, fact, workflow, event, decision or document.
    assert counts(sessions) == before


def test_a_technical_unavailability_is_not_an_hr_outcome(
    sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    artifacts: Artifacts,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    confirm_jurisdiction(sessions, seed.company_a, "uae_federal")
    artifacts.profile["workflows"][0]["knowledge_runtime_digest"] = "f" * 64
    client = client_for(sessions, cognito_provider, artifacts, dismissal())
    body = client.post(
        f"/companies/{seed.company_a}/assistant/messages",
        headers=admin_alice,
        json={"message": MESSAGE},
    ).json()
    assert body["outcome"]["kind"] == "unavailable"
    assert body["outcome"]["title"] == "Checks unavailable" and body["outcome"]["items"] == []


def test_an_earlier_token_is_lost_state_never_an_error(
    sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    artifacts: Artifacts,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    """A token from before a deploy (or forged) grants nothing and breaks nothing."""
    confirm_jurisdiction(sessions, seed.company_a, "uae_federal")
    client = client_for(sessions, cognito_provider, artifacts, dismissal(turn=1))
    answered = client.post(
        f"/companies/{seed.company_a}/assistant/messages",
        headers=admin_alice,
        json={
            "message": MESSAGE,
            "continuation": "eyJ2IjoxLCJ0IjpbM119.xNc7X0hBpSOKTehKXpgdlw",
            "history": [
                {"role": "user", "content": "Earlier."},
                {"role": "assistant", "content": "Earlier reply."},
            ],
        },
    )
    assert answered.status_code == 200
    assert answered.json()["outcome"]["kind"] == "expert_review"
    assert answered.json()["continuation"].startswith("e1.")
