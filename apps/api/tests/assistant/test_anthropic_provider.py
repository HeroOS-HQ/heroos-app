"""The Anthropic adapter and the explicit provider choice, with a fake transport (no network).

Covers: one bounded Messages API request to the fixed endpoint, with the key
only in its header, no tools and no temperature; only text blocks are read;
failures, declined or incomplete replies map to fixed kinds without provider
text; the gateway's JSON is bounded and passed on unvalidated; and the
configured provider (never whichever key exists) decides which key is used.
"""

import json
import logging
import urllib.error
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.assistant.anthropic import (
    ANTHROPIC_MESSAGES_URL,
    JSON_THINKING_TOKENS,
    MAX_JSON_CHARS,
    MAX_JSON_TOKENS,
    MAX_REPLY_CHARS,
    AnthropicChatProvider,
)
from app.assistant.groq import GroqChatProvider
from app.assistant.live import OfflineProvider
from app.assistant.provider import AssistantError, ChatTurn
from app.assistant.transport import MAX_RESPONSE_BYTES
from app.core.config import Settings
from app.knowledge.bundle import KnowledgeBundle
from app.main import external_provider, load_ai_gateway, load_hannah_demo
from tests.test_hannah_provider import FakeSend

KEY = "test-only-placeholder-not-a-key"
MODEL = "claude-test-model"
TURNS = [ChatTurn("user", "One of our employees keeps arriving late.")]


def message(*blocks: dict[str, Any], stop: Any = "end_turn", **extra: Any) -> dict[str, Any]:
    return {"type": "message", "role": "assistant", "content": list(blocks),
            "stop_reason": stop, **extra}  # fmt: skip


def text(value: Any) -> dict[str, Any]:
    return {"type": "text", "text": value}


def _provider(send: FakeSend) -> AnthropicChatProvider:
    return AnthropicChatProvider(SecretStr(KEY), MODEL, send=send)


def _json(provider: AnthropicChatProvider, **values: Any) -> Any:
    options = {"temperature": 0.0, "max_completion_tokens": 10, "timeout": 5.0} | values
    return provider.complete_json("SYSTEM", [ChatTurn("user", "{}")], **options)


# --- the request ------------------------------------------------------------------------


def test_a_reply_is_one_bounded_request_without_tools() -> None:
    send = FakeSend(body=message(text("  Have you spoken with them yet?  ")))
    assert _provider(send).reply("SYSTEM", TURNS) == "Have you spoken with them yet?"
    assert len(send.calls) == 1
    url, headers, payload, timeout = send.calls[0]
    assert url == ANTHROPIC_MESSAGES_URL and url.startswith("https://api.anthropic.com/")
    assert headers["x-api-key"] == KEY and headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in headers
    assert payload == {
        "model": MODEL,
        "system": "SYSTEM",
        "messages": [{"role": "user", "content": TURNS[0].content}],
        "max_tokens": 2048,
        "output_config": {"effort": "low"},
        "stream": False,
    }
    assert 0 < timeout <= 30


def test_the_history_keeps_its_roles_and_the_instruction_stays_separate() -> None:
    send = FakeSend(body=message(text("ok")))
    turns = [ChatTurn("user", "Hi"), ChatTurn("assistant", "Hello"), ChatTurn("user", "Help?")]
    _provider(send).reply("SYSTEM", turns)
    payload = send.calls[0][2]
    assert payload["system"] == "SYSTEM"
    assert [m["role"] for m in payload["messages"]] == ["user", "assistant", "user"]
    assert all(m["content"] != "SYSTEM" for m in payload["messages"])


def test_only_text_blocks_are_read() -> None:
    body = message(
        {"type": "thinking", "thinking": "", "signature": "sig"},
        text("Hello "),
        {"type": "redacted_thinking", "data": "opaque"},
        text("there."),
    )
    assert _provider(FakeSend(body=body)).reply("S", TURNS) == "Hello there."


def test_a_long_reply_is_cut() -> None:
    send = FakeSend(body=message(text("x" * (MAX_REPLY_CHARS + 50))))
    assert len(_provider(send).reply("S", TURNS)) == MAX_REPLY_CHARS


def test_a_reply_cut_at_its_token_limit_is_still_a_reply(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    send = FakeSend(body=message(text("A partial answer"), stop="max_tokens"))
    assert _provider(send).reply("S", TURNS) == "A partial answer"
    assert "Anthropic reply reached its token limit" in caplog.text


# --- failures ---------------------------------------------------------------------------

PROVIDER_TEXT = "provider-detail-that-must-not-leak"


@pytest.mark.parametrize(
    ("send", "kind"),
    [
        (FakeSend(429, {"type": "error", "error": {"type": "rate_limit_error",
                                                   "message": PROVIDER_TEXT}}), "rate_limited"),
        (FakeSend(529, {"type": "error", "error": {"type": "overloaded_error",
                                                   "message": PROVIDER_TEXT}}), "unavailable"),
        (FakeSend(500, {"error": {"type": "api_error", "message": PROVIDER_TEXT}}), "unavailable"),
        (FakeSend(401, {"error": {"type": "authentication_error", "message": PROVIDER_TEXT}}),
         "unavailable"),
        (FakeSend(400, {"error": {"type": "invalid_request_error", "message": PROVIDER_TEXT}}),
         "unavailable"),
        (FakeSend(404, b"<html>" + PROVIDER_TEXT.encode() + b"</html>"), "unavailable"),
        (FakeSend(error=TimeoutError()), "timeout"),
        (FakeSend(error=urllib.error.URLError(TimeoutError())), "timeout"),
        (FakeSend(error=urllib.error.URLError("name resolution failed")), "unavailable"),
        (FakeSend(error=OSError("connection refused")), "unavailable"),
        (FakeSend(body=b"not json"), "unavailable"),
        (FakeSend(body=b"x" * (MAX_RESPONSE_BYTES + 1)), "unavailable"),
        (FakeSend(body={"content": [text("no stop reason")]}), "unavailable"),
        (FakeSend(body={"stop_reason": "end_turn"}), "unavailable"),
        (FakeSend(body=message(stop="end_turn") | {"content": "not a list"}), "unavailable"),
        (FakeSend(body=message()), "unavailable"),
        (FakeSend(body=message(text("   "))), "unavailable"),
        (FakeSend(body=message(text(None))), "unavailable"),
        (FakeSend(body=message({"type": "thinking", "thinking": ""})), "unavailable"),
        (FakeSend(body=message(text(PROVIDER_TEXT), stop="refusal")), "unavailable"),
        (FakeSend(body=message(text("x"), stop="pause_turn")), "unavailable"),
        (FakeSend(body=message(text("x"), {"type": "tool_use", "id": "t", "name": "web_search",
                                           "input": {}}, stop="tool_use")), "unavailable"),
        (FakeSend(body=message(text("x"), {"type": "server_tool_use", "id": "t",
                                           "name": "web_search", "input": {}})), "unavailable"),
    ],
)  # fmt: skip
def test_failures_become_fixed_kinds_without_provider_text(
    send: FakeSend, kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    for call in (lambda p: p.reply("SYSTEM", TURNS), _json):
        with pytest.raises(AssistantError) as raised:
            call(_provider(send))
        assert raised.value.kind == kind
        assert str(raised.value) == kind
        assert raised.value.__cause__ is None
    assert len(send.calls) == 2  # one request each, never retried
    assert PROVIDER_TEXT not in caplog.text and KEY not in caplog.text


def test_a_refusal_logs_only_its_status_and_error_type(caplog: pytest.LogCaptureFixture) -> None:
    send = FakeSend(401, {"error": {"type": "authentication_error", "message": PROVIDER_TEXT}})
    with pytest.raises(AssistantError):
        _provider(send).reply("S", TURNS)
    assert "Anthropic request refused (status=401, code=authentication_error)" in caplog.text


def test_a_declined_reply_logs_only_its_stop_reason(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(AssistantError):
        _provider(FakeSend(body=message(text(PROVIDER_TEXT), stop="refusal"))).reply("S", TURNS)
    assert "Anthropic reply not used (stop_reason=refusal)" in caplog.text
    assert PROVIDER_TEXT not in caplog.text


def test_a_429_carries_the_providers_retry_after() -> None:
    send = FakeSend(429, {}, headers={"retry-after": "12"})
    with pytest.raises(AssistantError) as raised:
        _provider(send).reply("SYSTEM", TURNS)
    assert raised.value.retry_after == 12
    assert len(send.calls) == 1


# --- the gateway's JSON request ---------------------------------------------------------


def test_a_json_request_is_one_bounded_request_to_the_fixed_endpoint() -> None:
    usage = {"input_tokens": 100, "cache_creation_input_tokens": 15,
             "cache_read_input_tokens": 5, "output_tokens": 30}  # fmt: skip
    send = FakeSend(body=message(text('{"a": 1}'), usage=usage))
    result = _json(_provider(send), temperature=0.9, max_completion_tokens=99_999, timeout=999.0)
    assert (result.text, result.prompt_tokens, result.completion_tokens) == ('{"a": 1}', 120, 30)
    assert len(send.calls) == 1
    url, headers, payload, timeout = send.calls[0]
    assert url == ANTHROPIC_MESSAGES_URL and headers["x-api-key"] == KEY
    # Clamped whatever the caller asks; current Claude models refuse a temperature.
    assert payload["max_tokens"] == MAX_JSON_TOKENS
    assert timeout == 30.0
    for absent in ("temperature", "top_p", "top_k", "thinking", "tools", "tool_choice",
                   "mcp_servers", "container", "fallbacks", "response_format"):  # fmt: skip
        assert absent not in payload
    assert payload["stream"] is False


STABLE = [ChatTurn("user", '{"founder_messages": []}', stable='{"routing_catalog": {}}')]


def _cached(send: FakeSend) -> AnthropicChatProvider:
    return AnthropicChatProvider(SecretStr(KEY), MODEL, send=send, cache=True)


def test_a_cached_json_request_marks_only_the_instruction_and_the_stable_part() -> None:
    usage = {"input_tokens": 300, "cache_creation_input_tokens": 0,
             "cache_read_input_tokens": 4700, "output_tokens": 500}  # fmt: skip
    send = FakeSend(body=message(text("{}"), usage=usage))
    options = {"temperature": 0.0, "max_completion_tokens": 10, "timeout": 5.0}
    result = _cached(send).complete_json("SYSTEM", STABLE, **options)
    payload = send.calls[0][2]
    assert payload["system"] == [
        {"type": "text", "text": "SYSTEM", "cache_control": {"type": "ephemeral"}}
    ]
    assert payload["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": '{"routing_catalog": {}}',
                 "cache_control": {"type": "ephemeral"}},
                # The founder's words and per-request state: never in a cached part.
                {"type": "text", "text": '{"founder_messages": []}'},
            ],
        }
    ]  # fmt: skip
    assert (result.prompt_tokens, result.cache_read_tokens, result.cache_write_tokens) == (
        5000,
        4700,
        0,
    )


def test_without_caching_the_request_carries_no_cache_marker() -> None:
    send = FakeSend(body=message(text("{}")))
    options = {"temperature": 0.0, "max_completion_tokens": 10, "timeout": 5.0}
    _provider(send).complete_json("SYSTEM", STABLE, **options)
    payload = send.calls[0][2]
    assert payload["system"] == "SYSTEM"
    assert "cache_control" not in json.dumps(payload)
    # The stable part still comes first, as its own block: the same request otherwise.
    assert [b["text"] for b in payload["messages"][0]["content"]] == [
        '{"routing_catalog": {}}',
        '{"founder_messages": []}',
    ]


def test_the_hannah_reply_is_never_cached() -> None:
    send = FakeSend(body=message(text("Hello.")))
    _cached(send).reply("PERSONA", TURNS)
    assert send.calls[0][2]["system"] == "PERSONA"
    assert "cache_control" not in json.dumps(send.calls[0][2])


class RefusedOnce(FakeSend):
    """Refuses the first request with a 400 (as if the cache markers were refused)."""

    def __call__(self, url: str, headers: Any, body: bytes, timeout: float) -> Any:
        if not self.calls:
            self.calls.append((url, headers, json.loads(body), timeout))
            return 400, {}, b'{"type": "error", "error": {"type": "invalid_request_error"}}'
        return super().__call__(url, headers, body, timeout)


def test_a_refused_cached_request_is_sent_once_without_caching_and_caching_stays_off(
    caplog: pytest.LogCaptureFixture,
) -> None:
    send = RefusedOnce(body=message(text('{"a": 1}')))
    provider = _cached(send)
    options = {"temperature": 0.0, "max_completion_tokens": 10, "timeout": 5.0}
    assert provider.complete_json("SYSTEM", STABLE, **options).text == '{"a": 1}'
    assert len(send.calls) == 2
    assert "cache_control" in json.dumps(send.calls[0][2])
    assert "cache_control" not in json.dumps(send.calls[1][2])
    provider.complete_json("SYSTEM", STABLE, **options)
    assert "cache_control" not in json.dumps(send.calls[2][2])  # off for the process
    assert "Anthropic prompt caching turned off" in caplog.text


def test_any_other_refusal_is_never_sent_again() -> None:
    send = FakeSend(status=500, body={"type": "error"})
    with pytest.raises(AssistantError):
        _cached(send).complete_json(
            "SYSTEM", STABLE, temperature=0.0, max_completion_tokens=10, timeout=5.0
        )
    assert len(send.calls) == 1  # no hidden retry


def test_groq_sends_the_stable_part_first_in_the_same_message() -> None:
    send = FakeSend(body={"choices": [{"message": {"content": "{}"}}]})
    GroqChatProvider(SecretStr(KEY), "openai/gpt-oss-120b", send=send).complete_json(
        "SYSTEM", STABLE, temperature=0.0, max_completion_tokens=10, timeout=5.0
    )
    sent = send.calls[0][2]["messages"][1]["content"]
    assert sent == '{"routing_catalog": {}}\n{"founder_messages": []}'


def test_the_callers_smaller_budget_and_timeout_are_kept() -> None:
    # The caller's budget is for the object; adaptive thinking spends from max_tokens first.
    send = FakeSend(body=message(text("{}")))
    _json(_provider(send), max_completion_tokens=1200, timeout=12.5)
    assert send.calls[0][2]["max_tokens"] == 1200 + JSON_THINKING_TOKENS <= MAX_JSON_TOKENS
    assert send.calls[0][3] == 12.5


def test_unreported_usage_stays_unknown() -> None:
    result = _json(_provider(FakeSend(body=message(text("{}")))))
    assert (result.prompt_tokens, result.completion_tokens) == (None, None)
    partial = message(text("{}"), usage={"input_tokens": "many", "output_tokens": True})
    result = _json(_provider(FakeSend(body=partial)))
    assert (result.prompt_tokens, result.completion_tokens) == (None, None)


@pytest.mark.parametrize(
    ("raw", "passed_on"),
    [
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('```\n{"a": 1}\n```', '{"a": 1}'),
        # Anything else is passed on as it came: the gateway decides it is not JSON.
        ('Here it is: {"a": 1}', 'Here it is: {"a": 1}'),
        ('{"a": "```"}', '{"a": "```"}'),
    ],
)
def test_only_a_code_fence_around_the_object_is_removed(raw: str, passed_on: str) -> None:
    assert _json(_provider(FakeSend(body=message(text(raw))))).text == passed_on


def test_an_oversized_object_is_refused() -> None:
    send = FakeSend(body=message(text('{"a": "' + "x" * MAX_JSON_CHARS + '"}')))
    with pytest.raises(AssistantError) as raised:
        _json(_provider(send))
    assert raised.value.kind == "unavailable"


# --- the configured provider ------------------------------------------------------------


def settings(**values: Any) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
        **({"heroos_env": "development"} | values),
    )


SMOKE = {"heroos_ai_live_smoke_enabled": True}  # builds the real adapter (never called here)


@pytest.mark.parametrize("name", ["openai", "claude", "Anthropic", "ANTHROPIC", "anthropic,groq"])
def test_only_known_providers_can_be_chosen(name: str) -> None:
    with pytest.raises(ValidationError):
        settings(heroos_ai_gateway_provider=name)
    with pytest.raises(ValidationError):
        settings(heroos_hannah_provider=name, heroos_hannah_model=MODEL)


def test_each_provider_uses_only_its_own_key() -> None:
    both = settings(anthropic_api_key=KEY, groq_api_key=KEY + "-groq", **SMOKE)
    assert isinstance(external_provider(both, "anthropic", MODEL), AnthropicChatProvider)
    assert isinstance(external_provider(both, "groq", "m"), GroqChatProvider)
    # The other provider's key is never a fallback.
    assert external_provider(settings(groq_api_key=KEY, **SMOKE), "anthropic", MODEL) is None
    assert external_provider(settings(anthropic_api_key=KEY, **SMOKE), "groq", "m") is None
    assert external_provider(settings(anthropic_api_key="   ", **SMOKE), "anthropic", MODEL) is None


def test_a_test_run_gets_an_offline_provider_for_anthropic_too() -> None:
    offline = external_provider(settings(anthropic_api_key=KEY), "anthropic", MODEL)
    assert isinstance(offline, OfflineProvider) and offline.model == MODEL


GATEWAY = {
    "heroos_ai_gateway_enabled": True,
    "heroos_ai_gateway_provider": "anthropic",
    "heroos_ai_gateway_model": MODEL,
    "heroos_ai_gateway_approval": "PRIV-TEST-1",
    "heroos_ai_gateway_allow_development_knowledge": True,
}


def test_the_gateway_uses_anthropic_when_configured(
    bundle: KnowledgeBundle, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    ai = load_ai_gateway(settings(**GATEWAY, anthropic_api_key=KEY, **SMOKE), bundle)
    assert ai.reason is None and ai.provider is not None
    assert (ai.provider.name, ai.provider.model) == ("anthropic", MODEL)
    assert f"AI gateway enabled (provider=anthropic, model={MODEL}" in caplog.text
    assert KEY not in caplog.text


def test_the_gateway_names_the_missing_key_and_never_falls_back(
    bundle: KnowledgeBundle, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    ai = load_ai_gateway(settings(**GATEWAY, groq_api_key=KEY, **SMOKE), bundle)
    assert ai.provider is None and ai.reason == "not_configured" and "provider" in ai.missing
    assert "AI gateway provider key missing (provider=anthropic, key=ANTHROPIC_API_KEY)" in (
        caplog.text
    )
    assert KEY not in caplog.text


def test_hannah_stays_on_groq_unless_another_provider_is_chosen() -> None:
    assert settings().heroos_hannah_provider == "groq"
    demo = load_hannah_demo(settings(heroos_hannah_demo_enabled=True, groq_api_key=KEY, **SMOKE))
    assert isinstance(demo.provider, GroqChatProvider)


def test_hannah_on_anthropic_needs_an_anthropic_model() -> None:
    with pytest.raises(ValidationError, match="HEROOS_HANNAH_MODEL must name an Anthropic model"):
        settings(heroos_hannah_provider="anthropic")


def test_hannah_on_anthropic_needs_only_the_anthropic_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    chosen = {"heroos_hannah_provider": "anthropic", "heroos_hannah_model": MODEL}
    demo = load_hannah_demo(settings(**chosen, heroos_chat_only_demo=True,
                                     anthropic_api_key=KEY, **SMOKE))  # fmt: skip
    assert isinstance(demo.provider, AnthropicChatProvider) and demo.provider.model == MODEL
    demo = load_hannah_demo(settings(**chosen, heroos_hannah_demo_enabled=True, groq_api_key=KEY))
    assert demo.provider is None
    assert "Hannah AI demo provider key missing (provider=anthropic, key=ANTHROPIC_API_KEY)" in (
        caplog.text
    )
    assert KEY not in caplog.text


def test_the_anthropic_key_is_never_rendered() -> None:
    config = settings(anthropic_api_key=KEY)
    assert KEY not in repr(config) and KEY not in str(config.model_dump())
    assert KEY not in repr(AnthropicChatProvider(SecretStr(KEY), MODEL))
