"""GroqCloud chat completions (OpenAI-compatible) for the Hannah demo and the Ask gateway.

The endpoint is fixed here and the model comes from server configuration only:
nothing a client sends can choose either. Each request carries no tools (so no
browsing, code execution or function calls), a low temperature, a bounded
reply and a timeout, and is never retried. The API key is sent only in the
``Authorization`` header to the fixed HTTPS endpoint; redirects are refused.

``complete_json`` (the Ask HeroOS gateway, M2-NEW-05) asks for one JSON object
(``response_format: json_object``) with the caller's temperature, completion
budget and timeout, each clamped to fixed bounds here. The object is returned
as text, unvalidated: the gateway validates it.

Failures map to fixed kinds (``rate_limited``, ``timeout``, ``unavailable``);
the provider's error bodies are read only up to a limit and then dropped, never
logged or returned (``app.assistant.transport``).

The transport refuses every request in an automated test run unless a live
smoke test opted in (``app.assistant.live``): no test reaches GroqCloud.
"""

import json
from collections.abc import Sequence
from typing import Any, Final

from pydantic import SecretStr

from app.assistant import transport
from app.assistant.provider import AssistantError, ChatTurn, Completion
from app.assistant.transport import MAX_RESPONSE_BYTES, Send

GROQ_CHAT_COMPLETIONS_URL: Final = "https://api.groq.com/openai/v1/chat/completions"
TIMEOUT_SECONDS: Final = 30.0
TEMPERATURE: Final = 0.3
# Reasoning tokens of the gpt-oss models are part of the completion: leave
# room for a short reasoning pass and a reply of a few paragraphs.
MAX_COMPLETION_TOKENS: Final = 1024
MAX_REPLY_CHARS: Final = 6000
USER_AGENT: Final = "HeroOS-API (Hannah demo)"
# Bounds on what the gateway may ask for (whatever it passes).
MAX_JSON_TEMPERATURE: Final = 0.3
MAX_JSON_COMPLETION_TOKENS: Final = 2048
MAX_JSON_TIMEOUT_SECONDS: Final = 30.0
MAX_JSON_CHARS: Final = 12_000


def _content(body: bytes) -> tuple[str, Any]:
    """The first choice's text and the parsed body; ``unavailable`` for anything else."""
    if len(body) > MAX_RESPONSE_BYTES:
        raise AssistantError("unavailable")
    try:
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise AssistantError("unavailable") from None
    if not isinstance(content, str) or not content.strip():
        raise AssistantError("unavailable")
    return content.strip(), data


def _reply_text(body: bytes) -> str:
    return _content(body)[0][:MAX_REPLY_CHARS]


def _tokens(data: Any, name: str) -> int | None:
    usage = data.get("usage") if isinstance(data, dict) else None
    value = usage.get(name) if isinstance(usage, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class GroqChatProvider:
    """The chat model on GroqCloud (the Hannah demo and the Ask HeroOS gateway)."""

    def __init__(self, api_key: SecretStr, model: str, *, send: Send = transport.send) -> None:
        self._api_key = api_key
        self._model = model
        self._send = send

    @property
    def name(self) -> str:
        return "groq"

    @property
    def model(self) -> str:
        return self._model

    def payload(self, system: str, turns: Sequence[ChatTurn]) -> dict[str, Any]:
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                *({"role": turn.role, "content": turn.content} for turn in turns),
            ],
            "temperature": TEMPERATURE,
            "max_completion_tokens": MAX_COMPLETION_TOKENS,
            "reasoning_effort": "low",
            "include_reasoning": False,
            "stream": False,
        }

    def json_payload(
        self,
        system: str,
        turns: Sequence[ChatTurn],
        *,
        temperature: float,
        max_completion_tokens: int,
    ) -> dict[str, Any]:
        payload = self.payload(system, turns)
        payload["temperature"] = min(max(temperature, 0.0), MAX_JSON_TEMPERATURE)
        payload["max_completion_tokens"] = min(
            max(max_completion_tokens, 1), MAX_JSON_COMPLETION_TOKENS
        )
        payload["response_format"] = {"type": "json_object"}
        return payload

    def reply(self, system: str, turns: Sequence[ChatTurn]) -> str:
        return _reply_text(self._post(self.payload(system, turns), TIMEOUT_SECONDS))

    def complete_json(
        self,
        system: str,
        turns: Sequence[ChatTurn],
        *,
        temperature: float,
        max_completion_tokens: int,
        timeout: float,
    ) -> Completion:
        payload = self.json_payload(
            system, turns, temperature=temperature, max_completion_tokens=max_completion_tokens
        )
        body = self._post(payload, min(max(timeout, 1.0), MAX_JSON_TIMEOUT_SECONDS))
        text, data = _content(body)
        if len(text) > MAX_JSON_CHARS:
            raise AssistantError("unavailable")
        return Completion(
            text=text,
            prompt_tokens=_tokens(data, "prompt_tokens"),
            completion_tokens=_tokens(data, "completion_tokens"),
        )

    def _post(self, payload: dict[str, Any], timeout: float) -> bytes:
        """One request to the fixed endpoint; the response body, or a fixed failure kind."""
        headers = {
            "Authorization": f"Bearer {self._api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        return transport.exchange(
            self._send, "Groq", GROQ_CHAT_COMPLETIONS_URL, headers, payload, timeout
        )
