"""No automated test reaches a real AI provider, whatever it was configured with (M2-NEW-05).

During M2-NEW-05's verification, a harness left the gateway enabled with a
placeholder key and one synthetic end-to-end message reached GroqCloud (which
refused it). These prove that can't happen again:

- stale gateway, demo and key settings in the environment build an offline
  provider, never the real one, and a turn fails as ``unavailable`` with no
  connection attempted;
- the real transport refuses inside a test run even if a provider is built
  directly;
- only an explicit live smoke opt-in (refused in production) allows a real
  provider outside a deployed environment;
- the end-to-end harness marks every API it starts as a test run, after any
  suite's own settings.
"""

import hashlib
import socket
import sys
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.assistant.gateway.service import FounderTurn, GatewayFailure
from app.assistant.groq import GroqChatProvider
from app.assistant.live import (
    OfflineProvider,
    automated_test_process,
    external_ai_permitted,
    transport_permitted,
)
from app.assistant.provider import AssistantError, ChatTurn
from app.core.config import Settings
from app.main import create_app, external_provider, load_hannah_demo
from tests.auth.test_company_api import staging_settings
from tests.fixtures.gateway import company

KEY = "test-only-placeholder-not-a-key"
REPO = Path(__file__).resolve().parents[4]


class NetworkUsed(ConnectionRefusedError):
    """Raised by the guard; the attempt is also recorded, so a swallowed one still fails."""


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Any attempt to open a connection is recorded and fails the test."""
    attempts: list[str] = []

    def refuse(*args: Any, **kwargs: Any) -> Any:
        attempts.append(repr(args[:2]))
        raise NetworkUsed("a test tried to open a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", refuse)
    return attempts


def test_the_decision_ignores_gateway_and_key_settings() -> None:
    deployed: dict[str, Any] = {"automated_test": False, "live_smoke": False, "modules": {}}
    assert external_ai_permitted(environment="staging", **deployed) is True
    assert external_ai_permitted(environment="production", **deployed) is True
    assert external_ai_permitted(environment="development", **deployed) is False
    # A test run: pytest loaded, or the harness's marker.
    assert (
        external_ai_permitted(environment="staging", **deployed | {"modules": {"pytest": sys}})
        is False
    )
    assert (
        external_ai_permitted(environment="staging", **deployed | {"automated_test": True}) is False
    )
    # Only the explicit live smoke opt-in changes that.
    smoke = deployed | {"automated_test": True, "live_smoke": True}
    assert external_ai_permitted(environment="development", **smoke) is True
    assert automated_test_process({}, {}) is False
    assert automated_test_process({"HEROOS_AUTOMATED_TEST": "true"}, {}) is True
    assert automated_test_process({}, {"pytest": sys}) is True
    assert transport_permitted({}, {}) is True
    assert transport_permitted({"HEROOS_AUTOMATED_TEST": "true"}, {}) is False
    assert transport_permitted(
        {"HEROOS_AUTOMATED_TEST": "1", "HEROOS_AI_LIVE_SMOKE_ENABLED": "true"}, {}
    )


def test_live_smoke_is_off_by_default_and_never_in_production() -> None:
    config = staging_settings()
    assert (config.heroos_ai_live_smoke_enabled, config.heroos_automated_test) == (False, False)
    with pytest.raises(ValidationError, match="HEROOS_AI_LIVE_SMOKE_ENABLED"):
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            heroos_env="production",
            database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
            heroos_ai_live_smoke_enabled=True,
        )


def test_a_test_run_gets_an_offline_provider_and_a_live_smoke_gets_the_real_one() -> None:
    with_key = {"groq_api_key": SecretStr(KEY)}
    offline = external_provider(staging_settings().model_copy(update=with_key), "m")
    assert isinstance(offline, OfflineProvider) and offline.name == "offline"
    smoke = staging_settings().model_copy(update=with_key | {"heroos_ai_live_smoke_enabled": True})
    assert isinstance(external_provider(smoke, "m"), GroqChatProvider)  # built, never called here
    assert external_provider(staging_settings(), "m") is None  # no key, no provider


def test_stale_gateway_and_demo_settings_never_reach_the_network(
    monkeypatch: pytest.MonkeyPatch,
    bundle_file: Path,
    no_network: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Everything left enabled, a key in the environment: still no connection."""
    pin = hashlib.sha256(bundle_file.read_bytes()).hexdigest()
    for name, value in {
        "HEROOS_AI_GATEWAY_ENABLED": "true",
        "HEROOS_AI_GATEWAY_PROVIDER": "groq",
        "HEROOS_AI_GATEWAY_MODEL": "openai/gpt-oss-120b",
        "HEROOS_AI_GATEWAY_APPROVAL": "STALE-TEST",
        "HEROOS_AI_GATEWAY_ALLOW_DEVELOPMENT_KNOWLEDGE": "true",
        "HEROOS_HANNAH_DEMO_ENABLED": "true",
        "HEROOS_KNOWLEDGE_BUNDLE_PATH": str(bundle_file),
        "HEROOS_KNOWLEDGE_BUNDLE_SHA256": pin,
        "GROQ_API_KEY": KEY,
    }.items():
        monkeypatch.setenv(name, value)
    caplog.set_level("INFO")
    app = create_app(staging_settings())
    ai, demo = app.state.ai_gateway, app.state.hannah_demo
    assert ai.reason is None and ai.provider.name == "offline"
    assert demo.provider is not None and demo.provider.name == "offline"
    assert "AI gateway enabled (provider=offline" in caplog.text
    assert KEY not in caplog.text
    with pytest.raises(GatewayFailure) as failure:
        ai.respond(company(), FounderTurn("[SYNTHETIC] Can I dismiss an employee today?"))
    assert failure.value.kind == "unavailable"
    with pytest.raises(AssistantError):
        demo.provider.reply("SYSTEM", [ChatTurn("user", "[SYNTHETIC] hello")])
    assert no_network == []


def test_the_real_transport_refuses_inside_a_test_run(
    no_network: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    provider = GroqChatProvider(SecretStr(KEY), "openai/gpt-oss-120b")
    with pytest.raises(AssistantError) as error:
        provider.reply("SYSTEM", [ChatTurn("user", "[SYNTHETIC] hello")])
    assert error.value.kind == "unavailable"
    with pytest.raises(AssistantError):
        provider.complete_json(
            "S", [ChatTurn("user", "{}")], temperature=0, max_completion_tokens=10, timeout=5
        )
    assert no_network == []
    assert "External AI request blocked (automated test run)" in caplog.text


def test_the_live_smoke_opt_in_is_what_reaches_the_transport(
    monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> None:
    """With the opt-in, the request gets as far as opening a connection (refused here)."""
    monkeypatch.setenv("HEROOS_AI_LIVE_SMOKE_ENABLED", "true")
    with pytest.raises(AssistantError):
        GroqChatProvider(SecretStr(KEY), "m").reply("S", [ChatTurn("user", "[SYNTHETIC] x")])
    assert len(no_network) == 1


def test_the_hannah_demo_is_offline_in_a_test_run_too() -> None:
    config = staging_settings().model_copy(
        update={"heroos_hannah_demo_enabled": True, "groq_api_key": SecretStr(KEY)}
    )
    provider = load_hannah_demo(config).provider
    assert provider is not None and provider.name == "offline"


def test_the_end_to_end_harness_marks_every_api_as_a_test_run() -> None:
    """Set after a suite's own settings, so no suite (or screenshot harness) can undo them."""
    harness = REPO / "e2e" / "lib" / "processes.mjs"
    if not harness.exists():
        pytest.skip("the e2e harness isn't part of this checkout")
    text = harness.read_text(encoding="utf-8")
    extra = text.index("...extraEnv,")
    assert text.index('HEROOS_AUTOMATED_TEST: "true"') > extra
    assert text.index('HEROOS_AI_LIVE_SMOKE_ENABLED: "false"') > extra
