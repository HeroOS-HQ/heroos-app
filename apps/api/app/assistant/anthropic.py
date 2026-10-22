"""Anthropic's native Messages API for the Hannah demo and the Ask gateway.

The endpoint is fixed here and the model comes from server configuration only:
nothing a client sends can choose either. Each request carries no tools (so no
browsing, web search, code execution or function calls), a low effort, a
bounded reply and a timeout, and is never retried. The API key is sent only in
the ``x-api-key`` header to the fixed HTTPS endpoint; redirects are refused.

Current Claude models think adaptively within ``max_tokens`` and refuse a
caller-set temperature, so neither the gateway's temperature nor a thinking
setting is sent: ``effort: low`` (the equivalent of Groq's low reasoning
effort) keeps the thinking short. Thinking blocks are never read; only the
reply's text blocks are.

``complete_json`` (the Ask HeroOS gateway) asks for one JSON object through the
gateway's own instructions, with the caller's completion budget and timeout
clamped to fixed bounds here. The object is returned as text, unvalidated: the
gateway validates it. A Markdown code fence around the object is removed, and
nothing else is changed.

Failures map to fixed kinds (``rate_limited``, ``timeout``, ``unavailable``),
as do a declined (``refusal``) or otherwise incomplete reply and any content
block other than text or thinking. The provider's error bodies are read only up
to a limit and then dropped, never logged or returned (``app.assistant.transport``).

The transport refuses every request in an automated test run unless a live
smoke test opted in (``app.assistant.live``): no test reaches Anthropic.
"""

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any, Final

from pydantic import SecretStr

from app.assistant import transport
from app.assistant.provider import AssistantError, ChatTurn, Completion
from app.assistant.transport import MAX_RESPONSE_BYTES, Send

logger = logging.getLogger(__name__)

ANTHROPIC_MESSAGES_URL: Final = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION: Final = "2023-06-01"
TIMEOUT_SECONDS: Final = 30.0
EFFORT: Final = "low"
# Adaptive thinking shares max_tokens with the reply: room for a short thinking
# pass and a reply of a few paragraphs.
MAX_TOKENS: Final = 2048
MAX_REPLY_CHARS: Final = 6000
USER_AGENT: Final = "HeroOS-API"
# The gateway's completion budget is for the JSON object; adaptive thinking spends from the same
# max_tokens first. Found live (Haiku 5.5, gateway budget 1,200): most turns spent it all thinking
# and returned no text (unavailable) or a cut-off object (invalid output). So a JSON request adds
# room for the thinking pass.
JSON_THINKING_TOKENS: Final = 3000
# Bounds on what the gateway may ask for (whatever it passes).
MAX_JSON_TOKENS: Final = 4800
MAX_JSON_TIMEOUT_SECONDS: Final = 30.0
MAX_JSON_CHARS: Final = 12_000

# A complete reply. "refusal" (declined), "tool_use" and "pause_turn" never are.
COMPLETE: Final = frozenset({"end_turn", "stop_sequence", "max_tokens"})
# Blocks the reply may carry besides its text (never read).
THINKING_BLOCKS: Final = frozenset({"thinking", "redacted_thinking"})
CACHE_INPUT_TOKENS: Final = ("cache_creation_input_tokens", "cache_read_input_tokens")


def _shown(value: object) -> str:
    """A provider value fit for a log line: a short identifier, or "-"."""
    if isinstance(value, str) and value.replace("_", "").isalnum() and len(value) <= 40:
        return value
    return "-"


def _message(body: bytes) -> tuple[str, Any]:
    """The reply's text and the parsed body; ``unavailable`` for anything else."""
    if len(body) > MAX_RESPONSE_BYTES:
        raise AssistantError("unavailable")
    try:
        data = json.loads(body)
        blocks, stop = data["content"], data["stop_reason"]
    except (ValueError, KeyError, TypeError):
        raise AssistantError("unavailable") from None
    if not isinstance(blocks, list) or stop not in COMPLETE:
        logger.warning("Anthropic reply not used (stop_reason=%s)", _shown(stop))
        raise AssistantError("unavailable")
    parts: list[str] = []
    for block in blocks:
        kind = block.get("type") if isinstance(block, dict) else None
        if kind == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif kind not in THINKING_BLOCKS:
            logger.warning("Anthropic reply not used (block=%s)", _shown(kind))
            raise AssistantError("unavailable")
    text = "".join(parts).strip()
    if not text:
        raise AssistantError("unavailable")
    if stop == "max_tokens":
        logger.info("Anthropic reply reached its token limit")
    return text, data


def _without_fence(text: str) -> str:
    """The object without a Markdown code fence around it (the gateway still validates it)."""
    if text.startswith("```") and text.endswith("```") and "\n" in text:
        return text[text.index("\n") + 1 : -3].strip()
    return text


def _count(usage: Mapping[str, Any], name: str) -> int | None:
    value = usage.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _usage(data: Any) -> tuple[int | None, int | None]:
    """Input tokens (cached or not) and output tokens, as reported; None where absent."""
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return None, None
    prompt = _count(usage, "input_tokens")
    if prompt is not None:
        prompt += sum(_count(usage, name) or 0 for name in CACHE_INPUT_TOKENS)
    return prompt, _count(usage, "output_tokens")


class AnthropicChatProvider:
    """A Claude model on Anthropic's API (the Hannah demo and the Ask HeroOS gateway)."""

    def __init__(self, api_key: SecretStr, model: str, *, send: Send = transport.send) -> None:
        self._api_key = api_key
        self._model = model
        self._send = send

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    def payload(
        self, system: str, turns: Sequence[ChatTurn], *, max_tokens: int = MAX_TOKENS
    ) -> dict[str, Any]:
        return {
            "model": self._model,
            "system": system,
            "messages": [{"role": turn.role, "content": turn.content} for turn in turns],
            "max_tokens": max_tokens,
            "output_config": {"effort": EFFORT},
            "stream": False,
        }

    def reply(self, system: str, turns: Sequence[ChatTurn]) -> str:
        body = self._post(self.payload(system, turns), TIMEOUT_SECONDS)
        return _message(body)[0][:MAX_REPLY_CHARS]

    def complete_json(
        self,
        system: str,
        turns: Sequence[ChatTurn],
        *,
        temperature: float,
        max_completion_tokens: int,
        timeout: float,
    ) -> Completion:
        # No temperature: current Claude models refuse one (see the module docstring).
        tokens = min(max(max_completion_tokens, 1) + JSON_THINKING_TOKENS, MAX_JSON_TOKENS)
        payload = self.payload(system, turns, max_tokens=tokens)
        body = self._post(payload, min(max(timeout, 1.0), MAX_JSON_TIMEOUT_SECONDS))
        text, data = _message(body)
        if len(text) > MAX_JSON_CHARS:
            raise AssistantError("unavailable")
        prompt_tokens, completion_tokens = _usage(data)
        return Completion(
            text=_without_fence(text),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def _post(self, payload: dict[str, Any], timeout: float) -> bytes:
        """One request to the fixed endpoint; the response body, or a fixed failure kind."""
        headers = {
            "x-api-key": self._api_key.get_secret_value(),
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        return transport.exchange(
            self._send, "Anthropic", ANTHROPIC_MESSAGES_URL, headers, payload, timeout
        )
