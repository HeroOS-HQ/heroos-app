"""Structured, privacy-safe application logging (JSON lines on stdout).

See docs/architecture/observability.md.

- Every record becomes one JSON object. Only allowlisted structured fields are
  emitted; any other ``extra`` is dropped.
- Exceptions are never formatted as tracebacks. ``exc_info`` is reduced to the
  exception type and code locations (file basename, line, function); exception
  messages, arguments and local variables are never serialized, because they
  can contain request data.
- ``stack_info`` is dropped.
- Loggers that can emit SQL parameters, request URLs or request lines
  (SQLAlchemy, HTTP clients, Uvicorn's access log) are pinned above DEBUG/INFO
  regardless of the configured level.
"""

import json
import logging
import sys
import traceback
from datetime import UTC, datetime
from types import TracebackType
from typing import IO, Any, Final

from app.observability.context import current_request_context

# Structured fields HeroOS code may attach with ``extra=``. Values must be
# opaque identifiers, enums, numbers or fixed strings - never request content.
# Ordered: this is also the field order in each JSON line.
SAFE_FIELDS: Final = (
    "event",
    "request_id",
    "method",
    "route",
    "status_code",
    "duration_ms",
    "error_id",
    "company_id",
    "user_id",
    "exception_type",
    "exception_chain",
    "exception_frames",
)

# Third-party loggers that would otherwise record SQL with bound parameters,
# outbound URLs with query strings, or raw request lines.
QUIETED_LOGGERS: Final = {
    "sqlalchemy": logging.WARNING,
    "sqlalchemy.engine": logging.WARNING,
    "sqlalchemy.pool": logging.WARNING,
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "urllib3": logging.WARNING,
}
UVICORN_LOGGERS: Final = ("uvicorn", "uvicorn.error", "uvicorn.access")

MAX_EXCEPTION_FRAMES: Final = 10
_HANDLER_MARKER: Final = "_heroos_structured_handler"


def exception_type_name(exc_type: type[BaseException]) -> str:
    module = exc_type.__module__
    return exc_type.__qualname__ if module == "builtins" else f"{module}.{exc_type.__qualname__}"


def sanitized_exception(exc: BaseException) -> dict[str, Any]:
    """Investigation metadata that never includes the exception message.

    Code locations only: ``file`` is the source basename, never a full path,
    and the source line text and frame locals are not captured.
    """
    frames = [
        {
            "file": frame.filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
            "line": frame.lineno,
            "function": frame.name,
        }
        for frame in traceback.extract_tb(exc.__traceback__, limit=None)[-MAX_EXCEPTION_FRAMES:]
    ]
    chain: list[str] = []
    cause = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
    while cause is not None and len(chain) < 5:
        chain.append(exception_type_name(type(cause)))
        cause = cause.__cause__ or (None if cause.__suppress_context__ else cause.__context__)
    return {
        "exception_type": exception_type_name(type(exc)),
        "exception_chain": chain,
        "exception_frames": frames,
    }


class StructuredFormatter(logging.Formatter):
    """Render a ``LogRecord`` as one privacy-safe JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
        }
        for field in SAFE_FIELDS:
            value = record.__dict__.get(field)
            if value is not None:
                payload[field] = value if isinstance(value, int | float | list) else str(value)
        if "event" not in payload:
            # Plain log calls (HeroOS fixed-reason messages, library lifecycle
            # messages). HeroOS code never formats request content into them.
            payload["message"] = record.getMessage()
        if record.exc_info and record.exc_info[1] is not None:
            payload.update(sanitized_exception(record.exc_info[1]))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)

    def formatException(  # noqa: N802
        self,
        ei: tuple[type[BaseException], BaseException, TracebackType | None]
        | tuple[None, None, None],
    ) -> str:
        # Never render a traceback (it carries the exception message).
        exc = ei[1]
        return exception_type_name(type(exc)) if exc is not None else ""

    def formatStack(self, stack_info: str) -> str:  # noqa: N802
        return ""


class RequestContextFilter(logging.Filter):
    """Stamp records with the current request's correlation identifiers."""

    def filter(self, record: logging.LogRecord) -> bool:
        context = current_request_context()
        if context is not None:
            record.request_id = getattr(record, "request_id", None) or context.request_id
            if context.company_id is not None and getattr(record, "company_id", None) is None:
                record.company_id = context.company_id
            if context.user_id is not None and getattr(record, "user_id", None) is None:
                record.user_id = context.user_id
        return True


def configure_logging(level: str = "INFO", *, stream: IO[str] | None = None) -> logging.Handler:
    """Install the single structured stdout handler on the root logger.

    Idempotent: a previous HeroOS handler is replaced, other handlers (e.g. a
    test capture handler) are left alone. Uvicorn's own handlers are removed so
    its records flow through this formatter, and its access log is disabled:
    HeroOS's ``request_completed`` event is the authoritative request log.
    """
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, _HANDLER_MARKER, False):
            root.removeHandler(existing)
    handler = logging.StreamHandler(stream or sys.stdout)
    setattr(handler, _HANDLER_MARKER, True)
    handler.setFormatter(StructuredFormatter())
    handler.addFilter(RequestContextFilter())
    root.addHandler(handler)
    root.setLevel(level)

    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # The raw access log includes the request target with its query string.
    logging.getLogger("uvicorn.access").disabled = True

    for name, quiet_level in QUIETED_LOGGERS.items():
        logging.getLogger(name).setLevel(quiet_level)
    return handler
