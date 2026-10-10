"""HTTP-level security controls: CORS allow-list and response security headers.

See docs/architecture/authentication.md (§10 Browser access).

- CORS is installed only when ``HEROOS_CORS_ALLOWED_ORIGINS`` lists origins. Then
  only those exact origins, only ``GET`` and only the ``Authorization`` request
  header are allowed, and credentials (cookies) never are: the API authenticates
  bearer tokens, not ambient browser state.
- Every response carries ``nosniff``, ``no-store``, ``no-referrer`` and
  ``frame-ancestors``/``X-Frame-Options`` denial. Outside development the API also
  sends a deny-all CSP and HSTS; it serves JSON only, so nothing needs to load.
"""

from typing import Final

from fastapi import FastAPI
from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings

CORS_ALLOWED_METHODS: Final = ("GET",)
CORS_ALLOWED_HEADERS: Final = ("Authorization",)
CORS_MAX_AGE_SECONDS: Final = 600

BASE_SECURITY_HEADERS: Final = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    # Authenticated, tenant-private JSON must never be stored by browsers or proxies.
    "Cache-Control": "no-store",
}
DEPLOYED_SECURITY_HEADERS: Final = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "Strict-Transport-Security": "max-age=63072000",
}


class SecurityHeadersMiddleware:
    """Pure ASGI middleware adding fixed security headers to every HTTP response."""

    def __init__(self, app: ASGIApp, headers: dict[str, str]) -> None:
        self.app = app
        self.headers = dict(headers)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                headers = MutableHeaders(scope=message)
                for name, value in self.headers.items():
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


def security_headers(settings: Settings) -> dict[str, str]:
    headers = dict(BASE_SECURITY_HEADERS)
    if settings.heroos_env != "development":
        headers.update(DEPLOYED_SECURITY_HEADERS)
    return headers


def install_http_security(app: FastAPI, settings: Settings) -> None:
    """Install CORS (if configured) inside the security-header middleware.

    Call before ``install_observability`` so request correlation stays outermost.
    """
    origins = settings.cors_allowed_origins
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(origins),
            allow_methods=list(CORS_ALLOWED_METHODS),
            allow_headers=list(CORS_ALLOWED_HEADERS),
            allow_credentials=False,
            max_age=CORS_MAX_AGE_SECONDS,
        )
    app.add_middleware(SecurityHeadersMiddleware, headers=security_headers(settings))
