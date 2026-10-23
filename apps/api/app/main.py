import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import assistant, companies, documents, gateway, onboarding, workflows
from app.api.assistant import HannahDemo
from app.assistant.anthropic import AnthropicChatProvider
from app.assistant.gateway.service import AiGateway, utc_today
from app.assistant.groq import GroqChatProvider
from app.assistant.limits import UsageLimits
from app.assistant.live import OfflineProvider, external_ai_permitted
from app.assistant.provider import StructuredChatProvider
from app.auth.dependencies import get_authentication_provider
from app.core.config import AiProvider, Settings, settings
from app.core.http_security import install_http_security
from app.db.runtime_role import verify_runtime_role
from app.db.session import engine
from app.documents.bundle import TemplateBundle, check_against_rules, load_template_bundle
from app.evaluation.continuation import ContinuationCodec, parse_key
from app.evaluation.evaluator import ConversationEvaluationService
from app.evaluation.profile import load_execution_profile
from app.evaluation.snapshot import ExecutionRuntime, build_snapshot, describe
from app.knowledge.bundle import KnowledgeBundle, load_knowledge_bundle
from app.observability import configure_logging, install_observability
from app.storage.dependencies import get_private_object_storage
from app.workflows.definition import WORKFLOWS
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


def load_knowledge(config: Settings) -> KnowledgeBundle | None:
    """The configured approved-knowledge bundle, verified; None if none is configured.

    A configured bundle that is missing, doesn't match its pinned SHA-256 or
    fails validation (schema, digests, safety invariants, engine links) raises
    (startup stops): nothing falls back to other knowledge. The log names the
    bundle, version, provenance, approval and both digests, never content.
    """
    path, pin = config.heroos_knowledge_bundle_path, config.heroos_knowledge_bundle_sha256
    if path is None or pin is None:
        logger.info("Approved knowledge not installed")
        return None
    bundle = load_knowledge_bundle(path, pin, production=config.heroos_env == "production")
    logger.info(
        "Approved knowledge loaded (bundle=%s, version=%s, provenance=%s, approval=%s, "
        "source_package_digest=%s, runtime_bundle_digest=%s)",
        bundle.bundle_id,
        bundle.version,
        bundle.provenance,
        bundle.approval,
        bundle.source_package_digest,
        bundle.runtime_digest,
    )
    return bundle


def load_evaluation(
    config: Settings, knowledge: KnowledgeBundle | None, rules: RuleBundle | None
) -> ConversationEvaluationService:
    """Ask HeroOS's deterministic evaluation: one immutable snapshot of compatible artifacts.

    A configured profile that is missing, doesn't match its pin or fails its
    schema raises (startup stops). Whether it fits the installed knowledge,
    definitions and rule bundle is checked here too: a mismatch leaves
    deterministic evaluation unavailable for that workflow (logged with fixed
    codes), never running stale rules. The log names identities, never content.
    """
    path, pin = config.heroos_execution_profile_path, config.heroos_execution_profile_sha256
    profile = None
    if path is None or pin is None:
        logger.info("Conversation execution profile not installed")
    else:
        profile = load_execution_profile(path, pin, production=config.heroos_env == "production")
        logger.info(
            "Conversation execution profile loaded (profile=%s, version=%s, provenance=%s, "
            "approval=%s, digest=%s)",
            profile.profile,
            profile.version,
            profile.provenance,
            profile.approval,
            profile.digest[:16],
        )
    rule_bundles = {} if rules is None else {rules.workflow_key: rules}
    snapshot = build_snapshot(knowledge, profile, rule_bundles, WORKFLOWS)
    logger.info("Conversation evaluation snapshot %s", describe(snapshot))
    return ConversationEvaluationService(ExecutionRuntime(snapshot))


def continuation_codec(config: Settings) -> ContinuationCodec:
    """The shared-key codec (trusted state across instances), or a per-process one (none)."""
    key = config.heroos_evaluation_continuation_key
    return ContinuationCodec(None if key is None else parse_key(key.get_secret_value()))


# Each provider's key setting: only the configured provider's key is ever read.
PROVIDER_KEYS: dict[AiProvider, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY",
}


def external_provider(
    config: Settings, provider: AiProvider, model: str, *, cache: bool = False
) -> StructuredChatProvider | None:
    """The configured provider's chat model, or an offline stand-in where real calls aren't allowed.

    ``provider`` comes from server configuration and is never inferred from
    which keys exist. None without that provider's own key. An automated test
    run or local development (unless a live smoke test opted in) gets an
    ``OfflineProvider`` instead of the real one, whatever else is configured:
    it never reaches the network (app/assistant/live.py).
    """
    key = config.anthropic_api_key if provider == "anthropic" else config.groq_api_key
    if key is None or not key.get_secret_value().strip():
        return None
    permitted = external_ai_permitted(
        environment=config.heroos_env,
        automated_test=config.heroos_automated_test,
        live_smoke=config.heroos_ai_live_smoke_enabled,
    )
    if not permitted:
        return OfflineProvider(model)
    if provider == "anthropic":
        return AnthropicChatProvider(key, model, cache=cache)
    return GroqChatProvider(key, model)


def load_hannah_demo(config: Settings) -> HannahDemo:
    """The Hannah AI demo's switch, provider and usage limits (docs/architecture/hannah-ai-demo.md).

    Off unless enabled; then for every Company administrator in their own
    Company's Cases. The log names the provider, model and limits, never the key.
    """
    provider = external_provider(config, config.heroos_hannah_provider, config.heroos_hannah_model)
    if (config.heroos_hannah_demo_enabled or config.heroos_chat_only_demo) and provider is None:
        logger.warning(
            "Hannah AI demo provider key missing (provider=%s, key=%s)",
            config.heroos_hannah_provider,
            PROVIDER_KEYS[config.heroos_hannah_provider],
        )
    if config.heroos_hannah_demo_enabled:
        logger.info(
            "Hannah AI demo enabled (provider=%s, model=%s, account_limit=%d/5min, "
            "global_limit=%d/min %d/day)",
            "none" if provider is None else provider.name,
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


def load_chat_only_demo(config: Settings, demo: HannahDemo) -> bool:
    """Ask HeroOS's staging chat-only demo switch (production refuses it at settings load).

    On, Ask HeroOS is a plain conversation through the Hannah demo's provider,
    instruction, reply check and limits, and its workflow path answers 404
    (app/api/gateway.py). The log names the provider and model, never the key.
    """
    if config.heroos_chat_only_demo:
        logger.info(
            "Ask HeroOS chat-only demo enabled (provider=%s, model=%s)",
            "none" if demo.provider is None else demo.provider.name,
            config.heroos_hannah_model,
        )
    return config.heroos_chat_only_demo


def load_ai_gateway(
    config: Settings,
    knowledge: KnowledgeBundle | None,
    evaluation: ConversationEvaluationService | None = None,
) -> AiGateway:
    """Ask HeroOS's controlled AI gateway (docs/architecture/ai-gateway.md).

    Off unless enabled. Enabled, it answers only when every prerequisite holds
    (provider, model, key, approval reference, approved knowledge or explicitly
    allowed development knowledge); otherwise it stays unavailable and the
    log names what is missing, never a key or a value.
    """
    name = config.heroos_ai_gateway_provider
    model, understanding_model = (
        config.ai_gateway_response_model,
        config.ai_gateway_understanding_model,
    )
    reference = config.heroos_evaluation_reference_date
    provider: StructuredChatProvider | None = None
    understanding: StructuredChatProvider | None = None
    if name is not None and model is not None and understanding_model is not None:
        cache = config.heroos_ai_gateway_prompt_cache
        provider = external_provider(config, name, model, cache=cache)
        # The same provider for both phases; another instance only when the model differs.
        understanding = (
            provider
            if understanding_model == model
            else external_provider(config, name, understanding_model, cache=cache)
        )
        if provider is None and config.heroos_ai_gateway_enabled:
            logger.warning(
                "AI gateway provider key missing (provider=%s, key=%s)", name, PROVIDER_KEYS[name]
            )
    ai = AiGateway(
        enabled=config.heroos_ai_gateway_enabled,
        provider=provider,
        understanding=understanding,
        bundle=knowledge,
        approval=config.heroos_ai_gateway_approval,
        allow_development_knowledge=config.heroos_ai_gateway_allow_development_knowledge,
        limits=UsageLimits(
            account_limit=config.heroos_ai_gateway_account_limit,
            global_per_minute=config.heroos_ai_gateway_global_limit_per_minute,
            global_per_day=config.heroos_ai_gateway_global_limit_per_day,
        ),
        evaluation=evaluation,
        continuations=continuation_codec(config),
        today=utc_today if reference is None else lambda: reference,
    )
    if reference is not None:
        logger.warning("AI gateway reads dates against a fixed evaluation date (%s)", reference)
    if not ai.enabled:
        logger.info("AI gateway disabled")
    elif ai.reason is None:
        assert ai.provider is not None
        logger.info(
            "AI gateway enabled (provider=%s, model=%s, understanding_model=%s, prompt_cache=%s, "
            "approval=%s, development_knowledge=%s, account_limit=%d/5min, "
            "global_limit=%d/min %d/day)",
            ai.provider.name,
            model,
            understanding_model,
            config.heroos_ai_gateway_prompt_cache,
            config.heroos_ai_gateway_approval,
            ai.development_knowledge,
            config.heroos_ai_gateway_account_limit,
            config.heroos_ai_gateway_global_limit_per_minute,
            config.heroos_ai_gateway_global_limit_per_day,
        )
    else:
        logger.warning(
            "AI gateway enabled but unavailable (missing=%s)", ",".join(ai.missing) or "none"
        )
    return ai


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
    # Approved knowledge (server-side only: no route serves it): verified at startup.
    application.state.knowledge_bundle = load_knowledge(config)
    # The Hannah AI demo: off unless enabled, then for every Company administrator.
    application.state.hannah_demo = load_hannah_demo(config)
    # Staging only: Ask HeroOS as a plain chat through the Hannah demo, bypassing its workflow.
    application.state.chat_only_demo = load_chat_only_demo(config, application.state.hannah_demo)
    # Ask HeroOS's deterministic evaluation: the compatible artifacts, one immutable snapshot.
    application.state.conversation_evaluation = load_evaluation(
        config, application.state.knowledge_bundle, application.state.rule_bundle
    )
    # Ask HeroOS's AI gateway: off unless enabled and every prerequisite holds.
    application.state.ai_gateway = load_ai_gateway(
        config, application.state.knowledge_bundle, application.state.conversation_evaluation
    )
    application.add_api_route("/health", health, methods=["GET"], tags=["system"])
    application.include_router(companies.router)
    application.include_router(onboarding.router)
    application.include_router(workflows.router)
    application.include_router(documents.router)
    application.include_router(assistant.router)
    application.include_router(gateway.router)
    return application


app = create_app(settings)
