"""Ask HeroOS's staging chat-only demo (``HEROOS_CHAT_ONLY_DEMO``) through the real application.

Same harness as test_gateway_api.py, with the AI gateway enabled and able to
answer (so a bypass is a bypass, not a gateway that happened to be off) and
the Hannah demo's provider replaced by a local fake: CI never calls a model.

Covers: the switch (off by default, refused in production); a greeting and a
disciplinary situation answered by the model with nothing created (no
conversation, Case, fact, workflow, progression or evaluation); the
conversation's recent turns reaching the model; the reply check still
applied; the workflow path closed while the demo is on; and, with the demo
off, the chat route absent and M2-NEW-08's Ask HeroOS unchanged.
"""

import logging
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.api.assistant import HannahDemo
from app.api.gateway import CHAT_ONLY_NOTICE
from app.assistant.gateway.service import DEVELOPMENT_NOTICE
from app.assistant.limits import UsageLimits
from app.assistant.persona import HANNAH_SYSTEM_INSTRUCTION
from app.assistant.provider import ChatTurn
from app.assistant.response_safety import ACTION_FALLBACK
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.core.config import Settings
from app.knowledge.bundle import KnowledgeBundle
from tests.auth.conftest import TEST_APP_CLIENT_ID, TEST_COGNITO_ISSUER, SeedData
from tests.auth.test_assistant_api import REPLY, FakeProvider
from tests.auth.test_company_api import staging_settings
from tests.auth.test_gateway_api import (  # noqa: F401  (pytest fixtures)
    chat,
    gateway_client,
    send,
)
from tests.auth.test_intake_api import confirm_jurisdiction
from tests.auth.test_workflow_api import (  # noqa: F401  (pytest fixtures)
    FORBIDDEN,
    admin_alice,
    alice,
    sessions,
)
from tests.conversations.conftest import counts, stored_sessions  # noqa: F401  (fixture)
from tests.fixtures.gateway import ScriptedProvider
from tests.knowledge.conftest import (  # noqa: F401  (pytest fixtures)
    bundle,
    bundle_file,
    compiled,
    synthetic_mapping_path,
    synthetic_sources,
)

SITUATION = (
    "[SYNTHETIC] One of my employees hasn't shown up for work for three days and isn't responding."
)
QUESTION = (
    "I'm sorry you're dealing with that. Has the employee contacted you or anyone else at the "
    "company, or given any reason for the absence?"
)
FOLLOW_UP = "No, nobody has heard from him."


@pytest.fixture
def hannah() -> FakeProvider:
    return FakeProvider()


def chat_only_client(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    provider: CognitoAccessTokenProvider,
    bundle: KnowledgeBundle,  # noqa: F811
    scripted: ScriptedProvider,
    hannah: FakeProvider | None,
    *,
    enabled: bool = True,
) -> TestClient:
    """The real application with the gateway able to answer, and the switch as given."""
    client = gateway_client(stored_sessions, provider, bundle, scripted)
    state: Any = client.app.state  # type: ignore[attr-defined]
    state.chat_only_demo = enabled
    # The Hannah demo's own switch stays off: the chat-only demo only borrows its provider.
    state.hannah_demo = HannahDemo(
        enabled=False,
        provider=hannah,
        limits=UsageLimits(account_limit=20, global_per_minute=20, global_per_day=900),
    )
    return client


@pytest.fixture
def client(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    bundle: KnowledgeBundle,  # noqa: F811
    chat: ScriptedProvider,  # noqa: F811
    hannah: FakeProvider,
) -> TestClient:
    return chat_only_client(stored_sessions, cognito_provider, bundle, chat, hannah)


def talk(
    client: TestClient,
    headers: dict[str, str],
    where: uuid.UUID,
    message: str,
    history: list[dict[str, str]] | None = None,
) -> Any:
    return client.post(
        f"/companies/{where}/assistant/chat",
        headers=headers,
        json={"message": message, "history": history or []},
    )


def nothing_created(db: sessionmaker[Session]) -> bool:
    """No conversation, Case, fact, workflow, submission, progression, evaluation or decision."""
    return set(counts(db).values()) == {0}


# --- the switch -------------------------------------------------------------------------


def test_the_switch_is_off_by_default_and_production_refuses_it() -> None:
    assert staging_settings().heroos_chat_only_demo is False
    production: dict[str, Any] = {
        "_env_file": None,
        "heroos_env": "production",
        "database_url": "postgresql+psycopg://heroos_app@db.test.invalid/heroos",
        "heroos_auth_provider": "cognito",
        "heroos_cognito_issuer": TEST_COGNITO_ISSUER,
        "heroos_cognito_app_client_id": TEST_APP_CLIENT_ID,
    }
    # The settings load at import (app.core.config), so this stops the API starting.
    with pytest.raises(ValidationError, match="HEROOS_CHAT_ONLY_DEMO"):
        Settings(**production, heroos_chat_only_demo=True)
    assert Settings(**production).heroos_chat_only_demo is False


# --- on: a plain conversation, nothing created --------------------------------------------


def test_hi_hannah_gets_the_models_reply_and_nothing_is_created(
    client: TestClient,
    chat: ScriptedProvider,  # noqa: F811
    hannah: FakeProvider,
    stored_sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    status_ = client.get(f"/companies/{seed.company_a}/assistant", headers=admin_alice)
    assert status_.status_code == 200
    assert status_.json() == {
        "available": True,
        "reason": None,
        "notice": CHAT_ONLY_NOTICE,
        "chat_only": True,
    }

    answered = talk(client, admin_alice, seed.company_a, "Hi Hannah")
    assert answered.status_code == 200
    assert answered.json()["reply"] == REPLY
    assert answered.json()["notice"] == CHAT_ONLY_NOTICE
    assert answered.headers["cache-control"] == "no-store"
    # One request to the model: the fixed instruction and the greeting, nothing else.
    assert hannah.calls == [(HANNAH_SYSTEM_INSTRUCTION, [ChatTurn("user", "Hi Hannah")])]
    assert chat.calls == []
    assert nothing_created(stored_sessions)


def test_a_disciplinary_situation_gets_a_conversational_reply_and_no_case(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    bundle: KnowledgeBundle,  # noqa: F811
    chat: ScriptedProvider,  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    # A Company whose jurisdiction is confirmed: M2-NEW-08 would open a Disciplinary Case here.
    confirm_jurisdiction(stored_sessions, seed.company_a, "uae_federal")
    hannah = FakeProvider(reply=QUESTION)
    client = chat_only_client(stored_sessions, cognito_provider, bundle, chat, hannah)

    answered = talk(client, admin_alice, seed.company_a, SITUATION)
    assert answered.status_code == 200
    assert answered.json()["reply"] == QUESTION
    assert set(answered.json()) == {"reply", "provider", "model", "notice"}
    assert hannah.calls == [(HANNAH_SYSTEM_INSTRUCTION, [ChatTurn("user", SITUATION)])]
    # No Case, CaseFacts, workflow, submission, progression, evaluation or conversation.
    assert nothing_created(stored_sessions)
    assert chat.calls == []


def test_a_follow_up_sends_the_conversation_to_the_model(
    client: TestClient,
    hannah: FakeProvider,
    stored_sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    history = [
        {"role": "user", "content": SITUATION},
        {"role": "assistant", "content": QUESTION},
    ]
    answered = talk(client, admin_alice, seed.company_a, FOLLOW_UP, history)
    assert answered.status_code == 200
    assert hannah.calls[0][1] == [
        ChatTurn("user", SITUATION),
        ChatTurn("assistant", QUESTION),
        ChatTurn("user", FOLLOW_UP),
    ]
    assert nothing_created(stored_sessions)


def test_a_reply_claiming_an_action_is_still_replaced(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    bundle: KnowledgeBundle,  # noqa: F811
    chat: ScriptedProvider,  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    claim = "Done: I've recorded a final written warning and updated the case facts."
    client = chat_only_client(
        stored_sessions, cognito_provider, bundle, chat, FakeProvider(reply=claim)
    )
    answered = talk(client, admin_alice, seed.company_a, "Issue him a written warning now.")
    assert answered.status_code == 200
    assert answered.json()["reply"] == ACTION_FALLBACK
    assert "written warning" not in answered.json()["reply"].lower()
    assert nothing_created(stored_sessions)


def test_the_workflow_path_is_closed_while_the_demo_is_on(
    client: TestClient,
    chat: ScriptedProvider,  # noqa: F811
    hannah: FakeProvider,
    stored_sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    confirm_jurisdiction(stored_sessions, seed.company_a, "uae_federal")
    assert send(client, admin_alice, seed.company_a, SITUATION).status_code == 404
    assert chat.calls == [] and hannah.calls == []
    assert nothing_created(stored_sessions)


def test_only_this_companys_administrators_can_chat(
    client: TestClient,
    hannah: FakeProvider,
    stored_sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    alice: dict[str, str],  # noqa: F811
) -> None:
    # A member (not an administrator), and no credential at all: refused before the model.
    assert talk(client, alice, seed.company_a, "Hi Hannah").status_code == 403
    assert talk(client, {}, seed.company_a, "Hi Hannah").status_code == 401
    assert hannah.calls == []
    assert nothing_created(stored_sessions)


def test_without_a_provider_key_the_demo_says_so(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    bundle: KnowledgeBundle,  # noqa: F811
    chat: ScriptedProvider,  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    client = chat_only_client(stored_sessions, cognito_provider, bundle, chat, None)
    status_ = client.get(f"/companies/{seed.company_a}/assistant", headers=admin_alice)
    assert status_.json() == {
        "available": False,
        "reason": "not_configured",
        "notice": CHAT_ONLY_NOTICE,
        "chat_only": True,
    }
    answered = talk(client, admin_alice, seed.company_a, "Hi Hannah")
    assert (answered.status_code, answered.json()) == (503, {"detail": "Not configured"})
    assert chat.calls == []


def test_nothing_the_founder_or_the_model_said_is_logged(
    client: TestClient,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    assert talk(client, admin_alice, seed.company_a, SITUATION).status_code == 200
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "Ask HeroOS chat-only demo reply (provider=fake, model=fake-model, outcome=ok" in logged
    assert SITUATION not in logged and REPLY not in logged


# --- off: M2-NEW-08 unchanged -------------------------------------------------------------


def test_off_the_chat_route_is_absent_and_ask_heroos_is_unchanged(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    bundle: KnowledgeBundle,  # noqa: F811
    chat: ScriptedProvider,  # noqa: F811
    hannah: FakeProvider,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    client = chat_only_client(
        stored_sessions, cognito_provider, bundle, chat, hannah, enabled=False
    )
    confirm_jurisdiction(stored_sessions, seed.company_a, "uae_federal")
    # The status is exactly M2-NEW-07/08's: no chat_only key.
    status_ = client.get(f"/companies/{seed.company_a}/assistant", headers=admin_alice)
    assert status_.json() == {"available": True, "reason": None, "notice": DEVELOPMENT_NOTICE}
    assert talk(client, admin_alice, seed.company_a, "Hi Hannah").status_code == 404
    assert hannah.calls == []
    # The persistent turn still opens the conversation and its Disciplinary Case.
    answered = send(client, admin_alice, seed.company_a)
    assert answered.status_code == 200
    conversation = answered.json()["conversation"]
    assert conversation["case"] is not None
    assert conversation["status"]["workflow"] == {"key": "disciplinary", "title": "Disciplinary"}
    stored = counts(stored_sessions)
    assert stored["assistant_conversations"] == 1 and stored["cases"] == 1
