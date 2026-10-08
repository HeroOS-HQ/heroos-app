from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth.dependencies import get_authentication_provider
from app.db.runtime_role import verify_runtime_role
from app.db.session import engine
from app.storage.dependencies import get_private_object_storage

# Build the authentication provider at import so unsafe or incomplete auth
# configuration (e.g. the development provider outside development) stops
# startup instead of surfacing per request.
get_authentication_provider()
# Same for private object storage: an unavailable provider (e.g. s3 before M3)
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


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
