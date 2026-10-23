"""The one HTTPS exchange every provider adapter makes, and its fixed failure kinds.

Each adapter (``app.assistant.groq``, ``app.assistant.anthropic``) posts one
JSON body to its own fixed endpoint through ``send``: TLS verified, redirects
refused, the response read only up to a limit. ``exchange`` turns everything
that isn't a 200 into a fixed ``AssistantError`` kind (``rate_limited`` with the
provider's ``Retry-After``, ``timeout``, ``unavailable``); a refusal's body is
read only for its short error type and code, then dropped, never logged in
full or returned. Nothing here retries.

The transport refuses every request in an automated test run unless a live
smoke test opted in (``app.assistant.live``): no test reaches a provider.
"""

import json
import logging
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, Final

from app.assistant.live import transport_permitted
from app.assistant.provider import AssistantError

logger = logging.getLogger(__name__)

MAX_RESPONSE_BYTES: Final = 256 * 1024
# How much of a refusal's body is read (for its error type and code only).
MAX_ERROR_BYTES: Final = 4096

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


def send(
    url: str, headers: Mapping[str, str], body: bytes, timeout: float
) -> tuple[int, Mapping[str, str], bytes]:
    if not transport_permitted():
        # An automated test run never reaches the provider (app.assistant.live).
        logger.warning("External AI request blocked (automated test run)")
        raise ConnectionRefusedError("external AI requests are blocked in automated tests")
    opener = urllib.request.build_opener(
        _RefuseRedirects(), urllib.request.HTTPSHandler(context=_tls_context())
    )
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        with exc:
            # Bounded: only its error type and code are ever read (``error_code``).
            return exc.code, dict(exc.headers or {}), exc.read(MAX_ERROR_BYTES)


def retry_after(headers: Mapping[str, str]) -> int | None:
    for name, value in headers.items():
        if name.lower() == "retry-after":
            try:
                seconds = int(float(value))
            except ValueError:
                return None
            return min(max(seconds, 1), 3600)
    return None


def error_code(body: bytes) -> str:
    """The provider's error code if it is a short identifier (never its message or output)."""
    try:
        error = json.loads(body)["error"]
        parts = [error.get("type"), error.get("code")]
    except (ValueError, KeyError, TypeError, AttributeError):
        return "-"
    shown = [
        p for p in parts if isinstance(p, str) and p.replace("_", "").isalnum() and len(p) <= 40
    ]
    return "/".join(shown) or "-"


def exchange(
    send: Send,
    provider: str,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    timeout: float,
) -> bytes:
    """One request to the fixed ``url``; the 200 response body, or a fixed failure kind."""
    body = json.dumps(payload).encode("utf-8")
    try:
        status, response_headers, response_body = send(url, headers, body, timeout)
    except TimeoutError:
        raise AssistantError("timeout") from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise AssistantError("timeout") from None
        raise AssistantError("unavailable") from None
    except (OSError, ValueError):
        raise AssistantError("unavailable") from None
    if status == 429:
        raise AssistantError("rate_limited", retry_after=retry_after(response_headers))
    if status != 200:
        logger.warning(
            "%s request refused (status=%d, code=%s)", provider, status, error_code(response_body)
        )
        raise AssistantError("unavailable", status=status)
    return response_body
