from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import companies, onboarding
from app.auth.dependencies import get_authentication_provider
from app.core.config import Settings, settings
from app.core.http_security import install_http_security
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


async def health() -> dict[str, str]:
    return {"status": "ok"}


def create_app(config: Settings) -> FastAPI:
    # Interactive API docs and the OpenAPI schema are development aids; deployed
    # environments do not publish them.
    development = config.heroos_env == "development"
    application = FastAPI(
        title="HeroOS API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if development else None,
        redoc_url="/redoc" if development else None,
        openapi_url="/openapi.json" if development else None,
    )
    # Order matters: request correlation (observability) stays outermost.
    install_http_security(application, config)
    install_observability(application)

    # Founder self-registration is off unless explicitly enabled (activation step).
    application.state.self_registration_enabled = config.heroos_self_registration_enabled
    application.add_api_route("/health", health, methods=["GET"], tags=["system"])
    application.include_router(companies.router)
    application.include_router(onboarding.router)
    return application


app = create_app(settings)
