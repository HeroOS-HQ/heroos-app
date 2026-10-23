"""The gateway's settings, its startup wiring and the provider's JSON request (no network).

Covers: off by default; the model and approval are identifiers; production
refuses development knowledge; startup builds the provider only from server
configuration and logs what is missing, never a key; the GroqCloud JSON
request is one bounded request to the fixed endpoint, with no tools.
"""

import hashlib
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.assistant.gateway.service import utc_today
from app.assistant.groq import (
    GROQ_CHAT_COMPLETIONS_URL,
    MAX_JSON_CHARS,
    MAX_JSON_COMPLETION_TOKENS,
    GroqChatProvider,
)
from app.assistant.provider import AssistantError, ChatTurn
from app.core.config import Settings
from app.knowledge.bundle import KnowledgeBundle
from app.main import load_ai_gateway
from tests.test_hannah_provider import FakeSend, completion

KEY = "test-only-placeholder-not-a-key"


def settings(**values: Any) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
        **({"heroos_env": "development"} | values),
    )


READY = {
    "heroos_ai_gateway_enabled": True,
    "heroos_ai_gateway_provider": "groq",
    "heroos_ai_gateway_model": "openai/gpt-oss-120b",
    "heroos_ai_gateway_approval": "PRIV-TEST-1",
    "heroos_ai_gateway_allow_development_knowledge": True,
    "groq_api_key": KEY,
}


def test_the_gateway_is_off_by_default() -> None:
    config = settings()
    assert config.heroos_ai_gateway_enabled is False
    assert config.heroos_ai_gateway_provider is None and config.heroos_ai_gateway_model is None
    assert config.heroos_ai_gateway_allow_development_knowledge is False


@pytest.mark.parametrize(
    "values",
    [
        {"heroos_ai_gateway_model": "https://evil.example/v1"},
        {"heroos_ai_gateway_model": "model with spaces"},
        {"heroos_ai_gateway_provider": "openai"},
        {"heroos_ai_gateway_provider": "https://api.example.com"},
        {"heroos_ai_gateway_approval": "approved by me, trust me"},
        {"heroos_ai_gateway_account_limit": 0},
    ],
)
def test_provider_model_and_approval_are_closed_or_identifiers(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        settings(**values)


def test_production_never_serves_development_knowledge() -> None:
    with pytest.raises(ValidationError, match="ALLOW_DEVELOPMENT_KNOWLEDGE"):
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            heroos_env="production",
            database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
            heroos_ai_gateway_allow_development_knowledge=True,
        )


def test_production_never_reads_dates_against_a_fixed_evaluation_date() -> None:
    with pytest.raises(ValidationError, match="EVALUATION_REFERENCE_DATE"):
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            heroos_env="production",
            database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
            heroos_evaluation_reference_date="2026-10-22",
        )


def test_an_evaluation_harness_fixes_the_date_founders_dates_are_read_against(
    bundle: KnowledgeBundle, caplog: pytest.LogCaptureFixture
) -> None:
    """A frozen corpus's "yesterday" was written for one day: its harness fixes that day (found
    in the robustness pass: a run that crossed midnight read every "yesterday" a day late)."""
    caplog.set_level(logging.INFO)
    assert load_ai_gateway(settings(**READY), bundle).today() == utc_today()
    fixed = load_ai_gateway(
        settings(**READY, heroos_evaluation_reference_date="2026-10-22"), bundle
    )
    assert fixed.today() == date(2026, 10, 22)
    assert "fixed evaluation date (2026-10-22)" in caplog.text


def test_startup_wires_a_ready_gateway_offline_in_a_test_run(
    bundle: KnowledgeBundle, caplog: pytest.LogCaptureFixture
) -> None:
    """A test run never gets the real provider (tests/assistant/test_live_calls.py)."""
    caplog.set_level(logging.INFO)
    ai = load_ai_gateway(settings(**READY), bundle)
    assert ai.reason is None and ai.provider is not None
    assert (ai.provider.name, ai.provider.model) == ("offline", "openai/gpt-oss-120b")
    assert "AI gateway enabled (provider=offline, model=openai/gpt-oss-120b" in caplog.text
    assert KEY not in caplog.text


def test_startup_wires_the_real_provider_only_for_a_live_smoke_test(
    bundle: KnowledgeBundle, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    ai = load_ai_gateway(settings(**READY, heroos_ai_live_smoke_enabled=True), bundle)
    assert ai.provider is not None and ai.provider.name == "groq"  # built, never called
    assert "AI gateway enabled (provider=groq, model=openai/gpt-oss-120b" in caplog.text
    assert KEY not in caplog.text


@pytest.mark.parametrize(
    ("change", "missing", "reason"),
    [
        ({"groq_api_key": None}, "provider", "not_configured"),
        ({"groq_api_key": "   "}, "provider", "not_configured"),
        ({"heroos_ai_gateway_model": None}, "provider", "not_configured"),
        ({"heroos_ai_gateway_provider": None}, "provider", "not_configured"),
        ({"heroos_ai_gateway_approval": None}, "approval", "not_configured"),
        ({"heroos_ai_gateway_allow_development_knowledge": False}, "approved_knowledge",
         "not_configured"),
    ],
)  # fmt: skip
def test_a_missing_prerequisite_keeps_it_unavailable(
    bundle: KnowledgeBundle,
    caplog: pytest.LogCaptureFixture,
    change: dict[str, Any],
    missing: str,
    reason: str,
) -> None:
    caplog.set_level(logging.INFO)
    ai = load_ai_gateway(settings(**(READY | change)), bundle)
    assert ai.reason == reason and missing in ai.missing
    assert f"AI gateway enabled but unavailable (missing={missing}" in caplog.text
    assert KEY not in caplog.text


def test_without_knowledge_it_is_unavailable_and_says_why(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    ai = load_ai_gateway(settings(**READY), None)
    assert ai.reason == "knowledge_unavailable"
    assert "missing=knowledge" in caplog.text


def test_disabled_is_the_default_at_startup(
    bundle: KnowledgeBundle, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    assert load_ai_gateway(settings(groq_api_key=KEY), bundle).reason == "disabled"
    assert "AI gateway disabled" in caplog.text


def test_the_hannah_demo_switch_does_not_enable_the_gateway(bundle: KnowledgeBundle) -> None:
    config = settings(heroos_hannah_demo_enabled=True, groq_api_key=KEY)
    assert load_ai_gateway(config, bundle).reason == "disabled"


def test_a_development_bundle_never_loads_in_production(bundle_file: Path) -> None:
    from app.knowledge.bundle import KnowledgeBundleError, load_knowledge_bundle

    pin = hashlib.sha256(bundle_file.read_bytes()).hexdigest()
    with pytest.raises(KnowledgeBundleError):
        load_knowledge_bundle(bundle_file, pin, production=True)


# --- the provider's JSON request --------------------------------------------------------


def _provider(send: FakeSend) -> GroqChatProvider:
    return GroqChatProvider(SecretStr(KEY), "openai/gpt-oss-120b", send=send)


def test_a_json_request_is_one_bounded_request_to_the_fixed_endpoint() -> None:
    body = completion('{"a": 1}') | {"usage": {"prompt_tokens": 120, "completion_tokens": 30}}
    send = FakeSend(body=body)
    result = _provider(send).complete_json(
        "SYSTEM", [ChatTurn("user", "{}")], temperature=0.9, max_completion_tokens=99_999,
        timeout=999.0,
    )  # fmt: skip
    assert (result.text, result.prompt_tokens, result.completion_tokens) == ('{"a": 1}', 120, 30)
    assert len(send.calls) == 1
    url, headers, payload, timeout = send.calls[0]
    assert url == GROQ_CHAT_COMPLETIONS_URL and url.startswith("https://")
    assert headers["Authorization"] == f"Bearer {KEY}"
    assert payload["response_format"] == {"type": "json_object"}
    # Clamped whatever the caller asks.
    assert payload["temperature"] == 0.3
    assert payload["max_completion_tokens"] == MAX_JSON_COMPLETION_TOKENS
    assert timeout == 30.0
    for absent in ("tools", "tool_choice", "functions", "search", "browsing"):
        assert absent not in payload
    assert payload["stream"] is False


@pytest.mark.parametrize(
    ("send", "kind"),
    [
        (FakeSend(status=429, headers={"Retry-After": "12"}), "rate_limited"),
        (FakeSend(status=500), "unavailable"),
        (FakeSend(status=400), "unavailable"),
        (FakeSend(error=TimeoutError()), "timeout"),
        (FakeSend(body=b"not json"), "unavailable"),
        (FakeSend(body=completion("")), "unavailable"),
        (FakeSend(body=completion("x" * (MAX_JSON_CHARS + 1))), "unavailable"),
    ],
)
def test_json_request_failures_map_to_fixed_kinds(send: FakeSend, kind: str) -> None:
    with pytest.raises(AssistantError) as error:
        _provider(send).complete_json(
            "S", [ChatTurn("user", "{}")], temperature=0, max_completion_tokens=10, timeout=5
        )
    assert error.value.kind == kind
    assert len(send.calls) == 1
    assert "error" not in json.dumps(error.value.args)
