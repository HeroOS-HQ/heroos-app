"""Per-request correlation context.

The middleware binds a ``RequestLogContext`` for each HTTP request. It is a
mutable object held in a ``ContextVar``: sync dependencies run in a worker
thread with a *copy* of the context, so they update the same object rather than
re-binding the variable.

Only opaque server-side identifiers are stored here. Never put request data,
headers, tokens or HR content in it.
"""

import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from app.auth.models import AuthenticatedCompanyContext


def new_request_id() -> str:
    """Server-generated: 32 lowercase hex characters. Client values are never used."""
    return secrets.token_hex(16)


def new_error_id() -> str:
    return secrets.token_hex(16)


@dataclass(slots=True)
class RequestLogContext:
    request_id: str
    company_id: UUID | None = None
    user_id: UUID | None = None


_current: ContextVar[RequestLogContext | None] = ContextVar("heroos_request", default=None)


def current_request_context() -> RequestLogContext | None:
    return _current.get()


def bind_request_context(context: RequestLogContext) -> object:
    return _current.set(context)


def reset_request_context(token: object) -> None:
    _current.reset(token)  # type: ignore[arg-type]


def record_authorized_company(context: AuthenticatedCompanyContext) -> None:
    """Attach the Membership-authorized Company and User to the request log.

    Called only after authorization succeeds, so a denied request never records
    the Company it asked for as if it had been granted.
    """
    request = _current.get()
    if request is not None:
        request.company_id = context.company_id
        request.user_id = context.user_id
