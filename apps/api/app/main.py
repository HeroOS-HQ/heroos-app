from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth.dependencies import get_authentication_provider
from app.db.runtime_role import verify_runtime_role
from app.db.session import engine

# Build the authentication provider at import so unsafe or incomplete auth
# configuration (e.g. the development provider outside development) stops
# startup instead of surfacing per request.
get_authentication_provider()


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
