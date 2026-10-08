from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth.dependencies import get_authentication_provider
from app.core.config import settings
from app.db.runtime_role import verify_runtime_role
from app.db.session import engine
from app.observability import configure_logging, install_observability
from app.storage.dependencies import get_private_object_storage

# Structured JSON logs on stdout before anything else logs. This also disables
# Uvicorn's raw access log (it records query strings); the application's
# request_completed event is the authoritative request log.
configure_logging(settings.heroos_log_level)

# Build the authentication provider at import so unsafe or incomplete auth
# configuration (e.g. the development provider outside development) stops
# startup instead of surfacing per request.
get_authentication_provider()
# Same for private object storage: an unavailable provider (e.g. s3 without an adapter)
# or an unsafe local root stops startup; nothing falls back to local disk.
get_private_object_storage()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Refuse to serve if DATABASE_URL could bypass Row-Level Security
    # (superuser, BYPASSRLS or table owner).
    verify_runtime_role(engine)
    yield


app = FastAPI(
    title="HeroOS API",
    version="0.1.0",
    lifespan=lifespan,
)
install_observability(app)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
