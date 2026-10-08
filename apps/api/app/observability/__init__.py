"""Privacy-safe observability: structured logs, request correlation, error boundary.

See docs/architecture/observability.md.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.observability.logging import configure_logging
from app.observability.middleware import RequestObservabilityMiddleware

__all__ = ["configure_logging", "install_observability"]

# Fields of a validation error that are safe to return. ``input`` (the raw
# submitted value) and ``ctx`` are dropped: the default FastAPI response echoes
# whatever the client sent, which can include credentials or HR content.
_SAFE_VALIDATION_FIELDS = ("type", "loc", "msg")


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {field: error[field] for field in _SAFE_VALIDATION_FIELDS if field in error}
        for error in exc.errors()
    ]
    return JSONResponse({"detail": errors}, status_code=422)


def install_observability(app: FastAPI) -> None:
    """Install request correlation, the error boundary and safe 422 responses."""
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_middleware(RequestObservabilityMiddleware)
