"""The GroqCloud adapter and the Hannah demo settings, with a fake transport (no network)."""

import json
from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.assistant.groq import GROQ_CHAT_COMPLETIONS_URL, MAX_REPLY_CHARS, GroqChatProvider
from app.assistant.provider import AssistantError, ChatTurn
from app.core.config import DEFAULT_HANNAH_MODEL, Settings
from app.main import load_hannah_demo

KEY = SecretStr("test-only-placeholder-not-a-key")
TURNS = [ChatTurn("user", "One of our employees keeps arriving late.")]


class FakeSend:
    def __init__(
        self,
        status: int = 200,
        body: Any = None,
        headers: Mapping[str, str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.status = status
        self.body = body
        self.headers = headers or {}
        self.error = error
        self.calls: list[tuple[str, Mapping[str, str], dict[str, Any], float]] = []

    def __call__(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        self.calls.append((url, headers, json.loads(body), timeout))
        if self.error is not None:
            raise self.error
        raw = self.body if isinstance(self.body, bytes) else json.dumps(self.body).encode()
        return self.status, self.headers, raw


def completion(content: Any) -> dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def test_a_reply_is_one_bounded_request_without_tools() -> None:
    send = FakeSend(body=completion("  Have you spoken with them yet?  "))
    provider = GroqChatProvider(KEY, DEFAULT_HANNAH_MODEL, send=send)
    assert provider.reply("SYSTEM", TURNS) == "Have you spoken with them yet?"
    assert len(send.calls) == 1
    url, headers, payload, timeout = send.calls[0]
    assert url == GROQ_CHAT_COMPLETIONS_URL
    assert headers["Authorization"] == f"Bearer {KEY.get_secret_value()}"
    assert payload["model"] == "openai/gpt-oss-120b"
    assert payload["messages"] == [
        {"role": "system", "content": "SYSTEM"},
        {"role": "user", "content": TURNS[0].content},
    ]
    assert payload["stream"] is False
    assert payload["temperature"] <= 0.5
    assert payload["max_completion_tokens"] <= 1024
    for tool_key in ("tools", "tool_choice", "functions", "function_call"):
        assert tool_key not in payload
    assert 0 < timeout <= 30


@pytest.mark.parametrize(
    ("send", "kind"),
    [
        (FakeSend(429, {"error": {"message": "Rate limit reached for model"}}), "rate_limited"),
        (FakeSend(500, {"error": {"message": "boom"}}), "unavailable"),
        (FakeSend(401, {"error": {"message": "Invalid API Key"}}), "unavailable"),
        (FakeSend(error=TimeoutError()), "timeout"),
        (FakeSend(error=OSError("connection refused")), "unavailable"),
        (FakeSend(body=b"not json"), "unavailable"),
        (FakeSend(body={"choices": []}), "unavailable"),
        (FakeSend(body=completion("   ")), "unavailable"),
        (FakeSend(body=completion(None)), "unavailable"),
    ],
)
def test_failures_become_fixed_kinds_without_provider_text(send: FakeSend, kind: str) -> None:
    provider = GroqChatProvider(KEY, DEFAULT_HANNAH_MODEL, send=send)
    with pytest.raises(AssistantError) as raised:
        provider.reply("SYSTEM", TURNS)
    assert raised.value.kind == kind
    assert str(raised.value) == kind
    assert raised.value.__cause__ is None
    assert len(send.calls) == 1


def test_a_429_carries_the_providers_retry_after() -> None:
    send = FakeSend(429, {}, headers={"retry-after": "12"})
    with pytest.raises(AssistantError) as raised:
        GroqChatProvider(KEY, DEFAULT_HANNAH_MODEL, send=send).reply("SYSTEM", TURNS)
    assert raised.value.retry_after == 12


def test_a_long_reply_is_cut() -> None:
    send = FakeSend(body=completion("x" * (MAX_REPLY_CHARS + 50)))
    assert len(GroqChatProvider(KEY, "m", send=send).reply("S", TURNS)) == MAX_REPLY_CHARS


def settings(**values: Any) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
        **{"heroos_env": "development", "groq_api_key": None, **values},
    )


def test_the_demo_is_off_by_default_with_the_default_model() -> None:
    config = settings()
    assert config.heroos_hannah_demo_enabled is False
    assert config.heroos_hannah_model == "openai/gpt-oss-120b"
    demo = load_hannah_demo(config)
    assert (demo.enabled, demo.provider) == (False, None)


def test_enabled_needs_only_the_switch_and_a_key() -> None:
    demo = load_hannah_demo(settings(heroos_hannah_demo_enabled=True, groq_api_key=KEY))
    assert demo.enabled is True
    assert demo.provider is not None and demo.provider.model == DEFAULT_HANNAH_MODEL
    # A test run gets an offline stand-in, never the real provider (app.assistant.live).
    assert demo.provider.name == "offline"
    assert load_hannah_demo(settings(heroos_hannah_demo_enabled=True)).provider is None


def test_usage_limits_are_configurable_and_bounded() -> None:
    config = settings(
        heroos_hannah_account_limit=5,
        heroos_hannah_global_limit_per_minute=7,
        heroos_hannah_global_limit_per_day=100,
    )
    limits = load_hannah_demo(config).limits
    assert all(limits.acquire("account") is None for _ in range(5))
    exceeded = limits.acquire("account")
    assert exceeded is not None and exceeded.scope == "account"
    assert limits.acquire("another") is None and limits.acquire("third") is None
    exceeded = limits.acquire("fourth")
    assert exceeded is not None and exceeded.scope == "global"
    for field in (
        "heroos_hannah_account_limit",
        "heroos_hannah_global_limit_per_minute",
        "heroos_hannah_global_limit_per_day",
    ):
        with pytest.raises(ValidationError):
            settings(**{field: 0})


def test_production_refuses_the_demo_and_models_are_identifiers() -> None:
    with pytest.raises(ValidationError, match="HEROOS_HANNAH_DEMO_ENABLED"):
        settings(
            heroos_env="production",
            heroos_auth_provider="cognito",
            heroos_cognito_issuer="https://cognito-idp.test.invalid/pool",
            heroos_cognito_app_client_id="client",
            heroos_hannah_demo_enabled=True,
        )
    for model in ("https://evil.invalid/v1", "model name", ""):
        with pytest.raises(ValidationError, match="HEROOS_HANNAH_MODEL"):
            settings(heroos_hannah_model=model)
    assert settings(heroos_hannah_model="llama-3.3-70b-versatile").heroos_hannah_model


def test_the_key_is_never_rendered() -> None:
    config = settings(groq_api_key=KEY)
    assert KEY.get_secret_value() not in repr(config)
    assert KEY.get_secret_value() not in str(config.model_dump())
