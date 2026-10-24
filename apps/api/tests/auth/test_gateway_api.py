"""Ask HeroOS's AI gateway (M2-NEW-05, persistent since M2-NEW-07) through the real application.

Same harness as test_assistant_api.py (``create_app`` with staging settings,
Cognito tokens verified by the production provider, in-memory SQLite from
the real models) with the fictional knowledge bundle and a scripted provider:
CI never calls a model.

Covers: authentication, the administrator role and tenant isolation before
any model request; the canonical Blueprint as the only company context; a
browser that can send nothing but its words, its turn key, the conversation
and the revision it saw (no history, facts, workflow, jurisdiction, Case,
outcome, evaluation or continuation); the switch and every prerequisite;
failures as fixed codes that store nothing; the response carrying nothing
internal; nothing logged. Persistence itself: tests/conversations.
"""

import logging
import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.assistant.gateway.service import DEVELOPMENT_NOTICE, OUTSIDE_HR
from app.assistant.limits import UsageLimits
from app.assistant.provider import AssistantError
from app.auth.dependencies import get_authentication_provider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.db.session import get_db
from app.knowledge.bundle import KnowledgeBundle
from app.main import create_app
from tests.auth.conftest import SeedData
from tests.auth.test_company_admin_api import make_admin
from tests.auth.test_company_api import staging_settings
from tests.auth.test_intake_api import confirm_jurisdiction
from tests.auth.test_workflow_api import (  # noqa: F401  (pytest fixtures)
    FORBIDDEN,
    admin_alice,
    alice,
    bob,
    sessions,
)
from tests.conversations.conftest import counts, stored_sessions  # noqa: F401  (fixture)
from tests.fixtures.gateway import (
    ScriptedProvider,
    gateway,
    response,
    understanding,
)
from tests.knowledge.conftest import (  # noqa: F401  (pytest fixtures)
    bundle,
    bundle_file,
    compiled,
    synthetic_mapping_path,
    synthetic_sources,
)

MESSAGE = "[SYNTHETIC] Sam Example has been late three times this month. What should I do?"
REPLY = "Thanks for explaining. Has the expected standard been explained to Sam?"
TURN_FIELDS = {"conversation", "messages", "replayed"}
CONVERSATION_FIELDS = {"id", "title", "case", "created_at", "updated_at", "revision", "status"}
MESSAGE_FIELDS = {
    "sequence", "author", "text", "safe_next_step", "conversation_state", "outcome", "created_at",
}  # fmt: skip
STATUS_FIELDS = {"lifecycle", "workflow", "attention", "checks", "latest_outcome", "position"}
# M2-NEW-08: the Case's formal position, as its employer recorded it (labels; never the AI's).
POSITION_FIELDS = {"state", "label", "pathway", "stage", "stage_in_progress", "held_steps"}
# Every key the browser may ever see in a turn's response (anything else is internal).
PUBLIC_KEYS = (
    TURN_FIELDS | CONVERSATION_FIELDS | MESSAGE_FIELDS | STATUS_FIELDS | POSITION_FIELDS
    | {"key", "kind", "message", "items", "needs_information", "jurisdiction", "expert_review",
       "active", "scope", "actions", "service_available",
       # Chat-first Case: what HeroOS noted for the Case record (labels only).
       "noted", "label", "answer"}
)  # fmt: skip


def gateway_client(
    sessions: sessionmaker[Session],  # noqa: F811
    provider: CognitoAccessTokenProvider,
    bundle: KnowledgeBundle | None,  # noqa: F811
    chat: ScriptedProvider | None,
    **kwargs: Any,
) -> TestClient:
    app = create_app(staging_settings())
    app.state.ai_gateway = gateway(bundle, chat, **kwargs)

    def _db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_authentication_provider] = lambda: provider
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


@pytest.fixture
def chat() -> ScriptedProvider:
    return ScriptedProvider(
        understanding(pathway="less_serious", topics=["workplace_reminder"]),
        response(REPLY, ["q1"]),
    )


@pytest.fixture
def client(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    bundle: KnowledgeBundle,  # noqa: F811
    chat: ScriptedProvider,
) -> TestClient:
    return gateway_client(stored_sessions, cognito_provider, bundle, chat)


def url(company: uuid.UUID, *, status: bool = False) -> str:
    return f"/companies/{company}/assistant" + ("" if status else "/messages")


def send(
    client: TestClient,
    headers: dict[str, str],
    where: uuid.UUID,
    message: str = MESSAGE,
    **body: Any,
) -> Any:
    """A first message (a new conversation) unless ``body`` says otherwise."""
    request = {"message": message, "turn_key": str(uuid.uuid4()), "expected_revision": 0, **body}
    return client.post(url(where), headers=headers, json=request)


def keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


def nothing_stored(db: sessionmaker[Session]) -> bool:
    return set(counts(db).values()) == {0}


# --- access, before any model request ---------------------------------------------------


def test_an_administrator_asks_and_the_conversation_is_kept(
    client: TestClient,
    chat: ScriptedProvider,
    stored_sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    confirm_jurisdiction(stored_sessions, seed.company_a, "uae_federal")
    status_ = client.get(url(seed.company_a, status=True), headers=admin_alice)
    assert status_.status_code == 200
    assert status_.json() == {"available": True, "reason": None, "notice": DEVELOPMENT_NOTICE}

    answered = send(client, admin_alice, seed.company_a)
    assert answered.status_code == 200
    body = answered.json()
    assert set(body) == TURN_FIELDS and body["replayed"] is False
    conversation = body["conversation"]
    assert set(conversation) == CONVERSATION_FIELDS
    assert conversation["revision"] == 1
    founder, heroos = body["messages"]
    assert set(founder) == set(heroos) == MESSAGE_FIELDS
    assert (founder["author"], founder["text"], founder["sequence"]) == ("you", MESSAGE, 1)
    assert (heroos["author"], heroos["text"], heroos["sequence"]) == ("heroos", REPLY, 2)
    assert heroos["conversation_state"] == "responded" and heroos["safe_next_step"] is None
    # Knowledge without an execution profile: the checks can't run, which is never an HR outcome.
    assert heroos["outcome"]["kind"] == "unavailable"
    assert answered.headers["cache-control"] == "no-store"
    assert len(chat.calls) == 2
    stored = counts(stored_sessions)
    assert stored["assistant_conversations"] == 1 and stored["assistant_messages"] == 2
    # A supported matter of an established workflow: a Case, with a server-chosen title.
    assert conversation["case"]["title"] == conversation["title"]
    assert conversation["title"].startswith("Disciplinary case · ")
    status = conversation["status"]
    assert (status["lifecycle"], status["checks"], status["latest_outcome"]) == (
        "in_progress",
        "unavailable",
        "unavailable",
    )
    assert status["workflow"] == {"key": "disciplinary", "title": "Disciplinary"}


def test_the_response_carries_nothing_internal(
    client: TestClient,
    bundle: KnowledgeBundle,  # noqa: F811
    stored_sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    confirm_jurisdiction(stored_sessions, seed.company_a, "uae_federal")
    answered = send(client, admin_alice, seed.company_a)
    assert keys(answered.json()) <= PUBLIC_KEYS
    # The AI's pathway candidate (``less_serious`` here) never reaches the browser: the only
    # pathway it may see is the one the employer recorded in the Case (none yet).
    assert answered.json()["conversation"]["status"]["position"]["pathway"] is None
    for private in (
        bundle.runtime_digest, bundle.bundle_id, "approved_knowledge", "knowledge_status",
        "pathway_candidate", "less_serious", "Less serious", "topics", "fact_key", "EX0", "EX-",
        "rule-", "fake-model", "Standard explained",
        "question_target", "heroos.assistant-checkpoint", "heroos.conversation-evaluation",
        "engine_trusted", "employee_aware", "opt-", str(seed.alice), "continuation",
    ):  # fmt: skip
        assert private not in answered.text, private


@pytest.mark.parametrize("who", ["anonymous", "member", "other_company_admin"])
def test_no_model_request_without_this_companys_administrator(
    client: TestClient,
    chat: ScriptedProvider,
    stored_sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    alice: dict[str, str],  # noqa: F811
    bob: dict[str, str],  # noqa: F811
    who: str,
) -> None:
    if who == "anonymous":
        headers: dict[str, str] = {}
        expected = 401
    elif who == "member":
        headers, expected = alice, 403
    else:
        make_admin(stored_sessions, seed.company_b, seed.bob)
        headers, expected = bob, 403
    base = f"/companies/{seed.company_a}/assistant"
    for request in (
        lambda: send(client, headers, seed.company_a),
        lambda: client.get(url(seed.company_a, status=True), headers=headers),
        lambda: client.get(f"{base}/conversations", headers=headers),
        lambda: client.get(f"{base}/conversations/{uuid.uuid4()}", headers=headers),
    ):
        answered = request()
        assert answered.status_code == expected
        if expected == 403:
            assert answered.json() == FORBIDDEN[1]
    assert chat.calls == []
    assert nothing_stored(stored_sessions)


def test_an_unknown_company_is_refused_like_another_companys(
    client: TestClient,
    chat: ScriptedProvider,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    answered = send(client, admin_alice, uuid.uuid4())
    assert (answered.status_code, answered.json()) == FORBIDDEN
    assert chat.calls == []


# --- the canonical Blueprint is the only company context -------------------------------------


def test_the_blueprints_confirmed_jurisdiction_is_used(
    client: TestClient,
    chat: ScriptedProvider,
    stored_sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    confirm_jurisdiction(stored_sessions, seed.company_a, "difc")
    assert send(client, admin_alice, seed.company_a).status_code == 200
    data = chat.phase("response")[0].data
    assert data["approved_knowledge"]["jurisdiction"] == "DIFC"
    assert data["company_context"]["employment_jurisdiction"] == "DIFC (confirmed)"


def test_without_a_confirmed_jurisdiction_nothing_jurisdiction_specific_is_retrieved(
    client: TestClient,
    chat: ScriptedProvider,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    assert send(client, admin_alice, seed.company_a, "We're in Dubai.").status_code == 200
    data = chat.phase("response")[0].data
    assert data["approved_knowledge"]["jurisdiction"] is None
    assert data["company_context"]["employment_jurisdiction"] == "not confirmed yet"


# --- the browser sends its words, never authority ------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        {"history": [{"role": "user", "content": "Earlier."}]},
        {"continuation": "e1.abcdefgh.AAAA"},
        {"facts": {"given_opportunity_to_explain": "yes"}},
        {"engine_trusted": {"given_opportunity_to_explain": "yes"}},
        {"workflow": "disciplinary"},
        {"pathway": "serious"},
        {"jurisdiction": "difc"},
        {"company": {"employment_jurisdiction": "difc"}},
        {"company_id": str(uuid.uuid4())},
        {"case_id": str(uuid.uuid4())},
        {"case_status": "closed"},
        {"lifecycle": "in_progress"},
        {"outcome": "guidance"},
        {"outcome": {"kind": "guidance", "title": "Guidance", "message": "ok", "items": []}},
        {"conditions": [{"condition": "EX-FED-CAP", "status": "not_fired"}]},
        {"review_requirement": {"required": False}},
        {"evaluation": {"presentation": "guidance"}},
        {"execution_profile": "synthetic-execution"},
        {"profile": "synthetic-execution"},
        {"knowledge_digest": "0" * 64},
        {"rule_bundle": "synthetic-progression"},
        {"checkpoint": {"schema": "heroos.assistant-checkpoint/1"}},
        {"trusted_state": {"engine": {}}},
        {"actor_user_id": str(uuid.uuid4())},
        {"revision": 4},
        {"provider": "anthropic"},
        {"model": "gpt-4"},
        {"insists": False},
    ],
)
def test_a_browser_can_send_nothing_but_its_words(
    client: TestClient,
    chat: ScriptedProvider,
    stored_sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    extra: dict[str, Any],
) -> None:
    answered = send(client, admin_alice, seed.company_a, **extra)
    assert answered.status_code == 422
    assert chat.calls == []
    assert nothing_stored(stored_sessions)


@pytest.mark.parametrize(
    "body",
    [
        {"message": "   "},
        {"message": "a\u0000b"},
        {"message": "c1\u0085control"},
        {"message": "x" * 2001},
        {"message": "ok", "turn_key": None},
        {"message": "ok", "turn_key": "not-a-uuid"},
        {"message": "ok", "expected_revision": -1},
        {"message": "ok", "expected_revision": "0"},
        {"message": "ok", "expected_revision": True},
        {"message": "ok", "expected_revision": 3},
        {"message": "ok", "conversation_id": "not-a-uuid"},
    ],
)
def test_invalid_requests_are_refused_without_echoing(
    client: TestClient,
    chat: ScriptedProvider,
    stored_sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    body: dict[str, Any],
) -> None:
    request = {"turn_key": str(uuid.uuid4()), "expected_revision": 0, **body}
    answered = client.post(url(seed.company_a), headers=admin_alice, json=request)
    assert answered.status_code == 422
    # Field locations and fixed text only: never the submitted value.
    sent = body["message"]
    assert len(sent.strip()) < 3 or sent not in answered.text
    assert "x" * 50 not in answered.text
    assert chat.calls == []
    assert nothing_stored(stored_sessions)


# --- switch, prerequisites and failures -----------------------------------------------------


def test_the_gateway_is_off_unless_enabled(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    bundle: KnowledgeBundle,  # noqa: F811
    chat: ScriptedProvider,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    client = gateway_client(stored_sessions, cognito_provider, bundle, chat, enabled=False)
    status_ = client.get(url(seed.company_a, status=True), headers=admin_alice)
    assert status_.json() == {"available": False, "reason": "disabled", "notice": None}
    assert send(client, admin_alice, seed.company_a).status_code == 404
    assert chat.calls == []
    # Stored conversations stay readable for review.
    listed = client.get(f"/companies/{seed.company_a}/assistant/conversations", headers=admin_alice)
    assert listed.status_code == 200 and listed.json() == {"items": [], "next_before": None}


@pytest.mark.parametrize(
    ("kwargs", "reason", "detail"),
    [
        ({"approval": None}, "not_configured", "Not configured"),
        ({"allow_development_knowledge": False}, "not_configured", "Not configured"),
        ({"knowledge": None}, "knowledge_unavailable", "Knowledge unavailable"),
    ],
)
def test_a_missing_prerequisite_answers_503_without_a_model_request(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    bundle: KnowledgeBundle,  # noqa: F811
    chat: ScriptedProvider,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    kwargs: dict[str, Any],
    reason: str,
    detail: str,
) -> None:
    knowledge = kwargs.pop("knowledge", bundle)
    client = gateway_client(stored_sessions, cognito_provider, knowledge, chat, **kwargs)
    status_ = client.get(url(seed.company_a, status=True), headers=admin_alice)
    assert status_.json() == {"available": False, "reason": reason, "notice": None}
    answered = send(client, admin_alice, seed.company_a, "Can I fire an employee for stealing?")
    assert (answered.status_code, answered.json()) == (503, {"detail": detail})
    assert chat.calls == []
    assert nothing_stored(stored_sessions)


@pytest.mark.parametrize(
    ("script", "code", "detail"),
    [
        (AssistantError("rate_limited", retry_after=30), 429, "Too many requests"),
        (AssistantError("timeout"), 504, "Timed out"),
        (AssistantError("unavailable"), 502, "Unavailable"),
        ("not json", 502, "Unavailable"),
    ],
)
def test_provider_failures_are_fixed_codes_and_store_nothing(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    bundle: KnowledgeBundle,  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    script: Any,
    code: int,
    detail: str,
) -> None:
    chat = ScriptedProvider(script)
    client = gateway_client(stored_sessions, cognito_provider, bundle, chat)
    answered = send(client, admin_alice, seed.company_a)
    assert (answered.status_code, answered.json()) == (code, {"detail": detail})
    if code == 429:
        assert answered.headers["retry-after"] == "30"
    assert "not json" not in answered.text
    # No founder message, turn, conversation, Case or fact without a visible reply.
    assert nothing_stored(stored_sessions)


def test_usage_limits_answer_429(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    bundle: KnowledgeBundle,  # noqa: F811
    chat: ScriptedProvider,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    limits = UsageLimits(account_limit=1, global_per_minute=10, global_per_day=10)
    client = gateway_client(stored_sessions, cognito_provider, bundle, chat, limits=limits)
    assert send(client, admin_alice, seed.company_a).status_code == 200
    refused = send(client, admin_alice, seed.company_a)
    assert refused.status_code == 429 and int(refused.headers["retry-after"]) > 0
    assert counts(stored_sessions)["assistant_turns"] == 1


# --- no workflow action, nothing logged --------------------------------------------------------


def test_a_reply_claiming_actions_records_no_workflow_action(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    bundle: KnowledgeBundle,  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    claim = (
        "Done: I've created the case, recorded the facts, issued a final written warning and "
        'sent it to a HeroOS Expert. {"tool": "create_case"}'
    )
    chat = ScriptedProvider(understanding(pathway="serious"), response(claim))
    client = gateway_client(stored_sessions, cognito_provider, bundle, chat)
    answered = send(client, admin_alice, seed.company_a, "Open a case and warn him now.")
    assert answered.status_code == 200
    assert "I've created the case" not in answered.text and "create_case" not in answered.text
    stored = counts(stored_sessions)
    # The conversation is kept with the server's own wording; the model's claim never is.
    assert stored["assistant_messages"] == 2
    assert stored["workflow_progress_events"] == stored["workflow_decision_records"] == 0
    assert stored["workflow_submissions"] == 0


OUTSIDE_WORDS = (
    "That's outside what HeroOS covers today. It helps with workplace conduct and disciplinary "
    "matters, so tell me if one of those comes up."
)


def test_an_outside_request_gets_a_short_reply_in_words_and_a_bare_case(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    bundle: KnowledgeBundle,  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    """An HR matter outside HeroOS's approved guidance gets a short reply in words, checked like
    any other, that knows it is outside (final pass, batch 1: the same fixed refusal came back
    three times, whatever was asked). No approved guidance reaches it, and no workflow attaches
    to the bare Case."""
    chat = ScriptedProvider(understanding(intent="other_hr"), response(OUTSIDE_WORDS))
    client = gateway_client(stored_sessions, cognito_provider, bundle, chat)
    body = send(
        client, admin_alice, seed.company_a, "My probation hire's review went badly."
    ).json()
    heroos = body["messages"][1]
    assert heroos["text"] == OUTSIDE_WORDS
    assert heroos["conversation_state"] == "outside_approved_guidance"
    assert [c.phase for c in chat.calls] == ["understanding", "response"]
    light = chat.calls[1].data
    assert "outside_heroos_guidance" in light and "approved_knowledge" not in light
    # Chat-first Case: the first completed turn starts a bare Case, whatever it is about;
    # no workflow attaches to it outside HeroOS's approved guidance.
    case = body["conversation"]["case"]
    assert case is not None and case["title"] == body["conversation"]["title"] == "New case"
    stored = counts(stored_sessions)
    assert stored["cases"] == 1 and stored["workflow_instances"] == 0


def test_an_outside_request_whose_words_fail_gets_the_fixed_reply(
    stored_sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
    bundle: KnowledgeBundle,  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    """When the short reply can't be used (output that isn't a reply), the fixed text says the
    matter is outside the approved guidance and what HeroOS covers."""
    chat = ScriptedProvider(understanding(intent="other_hr"), "not a reply")
    client = gateway_client(stored_sessions, cognito_provider, bundle, chat)
    body = send(
        client, admin_alice, seed.company_a, "My probation hire's review went badly."
    ).json()
    heroos = body["messages"][1]
    assert heroos["text"] == OUTSIDE_HR.format(coverage="Example discipline")
    assert heroos["conversation_state"] == "outside_approved_guidance"
    assert counts(stored_sessions)["workflow_instances"] == 0


def test_nothing_the_founder_or_heroos_said_is_logged(
    client: TestClient,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    first = send(client, admin_alice, seed.company_a).json()
    second = send(
        client,
        admin_alice,
        seed.company_a,
        "[SYNTHETIC] Sam was late on Monday too.",
        conversation_id=first["conversation"]["id"],
        expected_revision=1,
    )
    assert second.status_code == 200
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "AI gateway turn (provider=fake" in logged
    assert "Ask HeroOS turn recorded" in logged
    for private in (MESSAGE, "Sam", REPLY, "late on Monday", "Disciplinary case"):
        assert private not in logged
