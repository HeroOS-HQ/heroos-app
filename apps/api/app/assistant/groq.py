"""GroqCloud chat completions (OpenAI-compatible) for the Hannah demo.

The endpoint is fixed here and the model comes from server configuration only:
nothing a client sends can choose either. Each request carries no tools (so no
browsing, code execution or function calls), a low temperature, a bounded
reply and a timeout, and is never retried. The API key is sent only in the
``Authorization`` header to the fixed HTTPS endpoint; redirects are refused.

Failures map to fixed kinds (``rate_limited``, ``timeout``, ``unavailable``);
the provider's error bodies are read only up to a limit and then dropped, never
logged or returned.
"""

import json
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

from pydantic import SecretStr

from app.assistant.provider import AssistantError, ChatTurn

GROQ_CHAT_COMPLETIONS_URL: Final = "https://api.groq.com/openai/v1/chat/completions"
TIMEOUT_SECONDS: Final = 30.0
TEMPERATURE: Final = 0.3
# Reasoning tokens of the gpt-oss models are part of the completion: leave
# room for a short reasoning pass and a reply of a few paragraphs.
MAX_COMPLETION_TOKENS: Final = 1024
MAX_RESPONSE_BYTES: Final = 256 * 1024
MAX_REPLY_CHARS: Final = 6000
USER_AGENT: Final = "HeroOS-API (Hannah demo)"

# (status, headers, body) of one HTTP exchange; raises TimeoutError or OSError.
Send = Callable[[str, Mapping[str, str], bytes, float], tuple[int, Mapping[str, str], bytes]]


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _send(
    url: str, headers: Mapping[str, str], body: bytes, timeout: float
) -> tuple[int, Mapping[str, str], bytes]:
    opener = urllib.request.build_opener(
        _RefuseRedirects(), urllib.request.HTTPSHandler(context=_tls_context())
    )
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, dict(exc.headers or {}), b""


def _retry_after(headers: Mapping[str, str]) -> int | None:
    for name, value in headers.items():
        if name.lower() == "retry-after":
            try:
                seconds = int(float(value))
            except ValueError:
                return None
            return min(max(seconds, 1), 3600)
    return None


def _reply_text(body: bytes) -> str:
    if len(body) > MAX_RESPONSE_BYTES:
        raise AssistantError("unavailable")
    try:
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise AssistantError("unavailable") from None
    if not isinstance(content, str) or not content.strip():
        raise AssistantError("unavailable")
    return content.strip()[:MAX_REPLY_CHARS]


class GroqChatProvider:
    """The Hannah demo's chat model on GroqCloud."""

    def __init__(self, api_key: SecretStr, model: str, *, send: Send = _send) -> None:
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

    def reply(self, system: str, turns: Sequence[ChatTurn]) -> str:
        headers = {
            "Authorization": f"Bearer {self._api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        body = json.dumps(self.payload(system, turns)).encode("utf-8")
        try:
            status, response_headers, response_body = self._send(
                GROQ_CHAT_COMPLETIONS_URL, headers, body, TIMEOUT_SECONDS
            )
        except TimeoutError:
            raise AssistantError("timeout") from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise AssistantError("timeout") from None
            raise AssistantError("unavailable") from None
        except (OSError, ValueError):
            raise AssistantError("unavailable") from None
        if status == 429:
            raise AssistantError("rate_limited", retry_after=_retry_after(response_headers))
        if status != 200:
            raise AssistantError("unavailable")
        return _reply_text(response_body)
