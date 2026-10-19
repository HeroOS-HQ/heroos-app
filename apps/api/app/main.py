import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import assistant, companies, documents, onboarding, workflows
from app.api.assistant import HannahDemo
from app.assistant.groq import GroqChatProvider
from app.assistant.limits import UsageLimits
from app.auth.dependencies import get_authentication_provider
from app.core.config import Settings, settings
from app.core.http_security import install_http_security
from app.db.runtime_role import verify_runtime_role
from app.db.session import engine
from app.documents.bundle import TemplateBundle, check_against_rules, load_template_bundle
from app.observability import configure_logging, install_observability
from app.storage.dependencies import get_private_object_storage
from app.workflows.progression.bundle import RuleBundle, load_bundle

logger = logging.getLogger(__name__)

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


def load_rule_bundle(config: Settings) -> RuleBundle | None:
    """The configured workflow-progression rule bundle, verified; None if none is configured.

    A configured bundle that is missing, doesn't match its pinned SHA-256 or
    fails validation raises (startup stops): nothing falls back to other rules.
    The log names the bundle and version only, never its content.
    """
    path, pin = config.heroos_rule_bundle_path, config.heroos_rule_bundle_sha256
    if path is None or pin is None:
        logger.info("Workflow progression rules not installed")
        return None
    bundle = load_bundle(path, pin, production=config.heroos_env == "production")
    logger.info(
        "Workflow progression rules loaded (bundle=%s, version=%s, provenance=%s)",
        bundle.bundle_id,
        bundle.version,
        bundle.provenance,
    )
    return bundle


def load_templates(config: Settings, rules: RuleBundle | None) -> TemplateBundle | None:
    """The configured document-template bundle, verified; None if none is configured.

    A configured bundle that is missing, doesn't match its pinned SHA-256,
    fails validation or doesn't fit the installed rule bundle raises (startup
    stops): nothing falls back to other templates. The log names the bundle,
    version, provenance and approval only, never wording.
    """
    path, pin = config.heroos_template_bundle_path, config.heroos_template_bundle_sha256
    if path is None or pin is None:
        logger.info("Document templates not installed")
        return None
    bundle = load_template_bundle(path, pin, production=config.heroos_env == "production")
    check_against_rules(bundle, rules)
    logger.info(
        "Document templates loaded (bundle=%s, version=%s, provenance=%s, approval=%s)",
        bundle.bundle_id,
        bundle.version,
        bundle.provenance,
        bundle.approval,
    )
    return bundle


def load_hannah_demo(config: Settings) -> HannahDemo:
    """The Hannah AI demo's switch, provider and usage limits (docs/architecture/hannah-ai-demo.md).

    Off unless enabled; then for every Company administrator in their own
    Company's Cases. The log names the provider, model and limits, never the key.
    """
    key = config.groq_api_key
    provider = (
        GroqChatProvider(key, config.heroos_hannah_model)
        if key is not None and key.get_secret_value().strip()
        else None
    )
    if config.heroos_hannah_demo_enabled:
        logger.info(
            "Hannah AI demo enabled (provider=%s, model=%s, account_limit=%d/5min, "
            "global_limit=%d/min %d/day)",
            "groq" if provider is not None else "none",
            config.heroos_hannah_model,
            config.heroos_hannah_account_limit,
            config.heroos_hannah_global_limit_per_minute,
            config.heroos_hannah_global_limit_per_day,
        )
    return HannahDemo(
        enabled=config.heroos_hannah_demo_enabled,
        provider=provider,
        limits=UsageLimits(
            account_limit=config.heroos_hannah_account_limit,
            global_per_minute=config.heroos_hannah_global_limit_per_minute,
            global_per_day=config.heroos_hannah_global_limit_per_day,
        ),
    )


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
    # The Disciplinary safety screening: off unless enabled for synthetic demo data.
    application.state.sensitive_screening = config.heroos_sensitive_screening
    # Workflow progression rules: verified at startup, never re-read while running.
    application.state.rule_bundle = load_rule_bundle(config)
    # Document templates (previews only): verified against those rules at startup.
    application.state.template_bundle = load_templates(config, application.state.rule_bundle)
    # The Hannah AI demo: off unless enabled, then for every Company administrator.
    application.state.hannah_demo = load_hannah_demo(config)
    application.add_api_route("/health", health, methods=["GET"], tags=["system"])
    application.include_router(companies.router)
    application.include_router(onboarding.router)
    application.include_router(workflows.router)
    application.include_router(documents.router)
    application.include_router(assistant.router)
    return application


app = create_app(settings)
