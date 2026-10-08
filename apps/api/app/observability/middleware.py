"""Request correlation, request logging and the unhandled-error boundary.

Pure ASGI middleware (it passes the scope through unchanged, so the matched
route template is visible after routing). For every HTTP request it:

1. generates a server-side request ID (client-supplied IDs are ignored),
2. returns it in the ``X-Request-ID`` response header,
3. logs one ``request_completed`` event with method, route template, status and
   duration - never the raw path, query string, headers or bodies,
4. turns any unhandled exception into a generic 500 carrying ``request_id`` and
   ``error_id``, and logs one sanitized ``unhandled_exception`` event.

Expected outcomes (401/403/404/422 and deliberate ``HTTPException``s) are
handled inside the application and only produce ``request_completed``.
"""

import logging
import time
from typing import Final

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.context import (
    RequestLogContext,
    bind_request_context,
    new_error_id,
    new_request_id,
    reset_request_context,
)
from app.observability.logging import sanitized_exception

REQUEST_ID_HEADER: Final = "X-Request-ID"
INTERNAL_SERVER_ERROR: Final = "Internal server error"
# Logged instead of a raw path when no route matched: an unmatched path can
# itself carry sensitive values.
UNMATCHED_ROUTE: Final = "<unmatched>"
_KNOWN_METHODS: Final = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"}
)

logger = logging.getLogger("app.request")


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else UNMATCHED_ROUTE


def _method(scope: Scope) -> str:
    method = str(scope.get("method", ""))
    return method if method in _KNOWN_METHODS else "OTHER"


class RequestObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        context = RequestLogContext(request_id=new_request_id())
        token = bind_request_context(context)
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                message.setdefault("headers", [])
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = context.request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            error_id = new_error_id()
            logger.error(
                "unhandled_exception",
                extra={
                    "event": "unhandled_exception",
                    "error_id": error_id,
                    "method": _method(scope),
                    "route": _route_template(scope),
                    **sanitized_exception(exc),
                },
            )
            if not response_started:
                response = JSONResponse(
                    {
                        "detail": INTERNAL_SERVER_ERROR,
                        "request_id": context.request_id,
                        "error_id": error_id,
                    },
                    status_code=500,
                )
                await response(scope, receive, send_with_request_id)
            # Not re-raised: the server would log the traceback, which carries
            # the exception message. If the response had already started, the
            # server closes the connection.
        finally:
            logger.log(
                logging.WARNING if status_code >= 500 else logging.INFO,
                "request_completed",
                extra={
                    "event": "request_completed",
                    "method": _method(scope),
                    "route": _route_template(scope),
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            reset_request_context(token)
