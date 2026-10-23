import re
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.core.database_settings import DatabaseSettings
from app.evaluation.continuation import parse_key

Environment = Literal["development", "staging", "production"]
AuthProviderName = Literal["development", "cognito", "oidc"]
# Which providers each environment may use. Production stays Cognito-only (M5);
# the provider-neutral OIDC provider serves the pre-M5 demo in staging.
ALLOWED_AUTH_PROVIDERS: dict[str, frozenset[str]] = {
    "staging": frozenset({"cognito", "oidc"}),
    "production": frozenset({"cognito"}),
}
OIDC_SUPPORTED_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"}
)
# "s3" is the production contract; no adapter exists yet, so selecting it
# stops startup instead of falling back to anything else.
StorageProviderName = Literal["local", "s3"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
# "synthetic_demo": the environment holds synthetic demo data only.
SensitiveScreening = Literal["disabled", "synthetic_demo"]

# An AI model id: an identifier, never a URL (each provider's endpoint is fixed
# in its adapter, app.assistant.anthropic or app.assistant.groq).
HANNAH_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
# A GroqCloud model: with HEROOS_HANNAH_PROVIDER=anthropic, HEROOS_HANNAH_MODEL is required.
DEFAULT_HANNAH_MODEL = "openai/gpt-oss-120b"

# The AI providers HeroOS has adapters for (server configuration only, never a
# client's choice). Each uses only its own key: ANTHROPIC_API_KEY or GROQ_API_KEY.
AiProvider = Literal["anthropic", "groq"]
# A reference to HeroOS's approval of this deployment's AI configuration (for
# example a privacy decision id): a short identifier, never free text.
AI_GATEWAY_APPROVAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,63}$")

# The pinned SHA-256 of the rule bundle (or template bundle) file (lowercase hex).
RULE_BUNDLE_PIN = re.compile(r"^[0-9a-f]{64}$")

# Loopback hosts of the local Docker Compose database. Deployed environments
# refuse them for DATABASE_URL.
LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# Matches user_identities.issuer (app.db.models.user_identity.MAX_ISSUER_LENGTH).
MAX_ISSUER_LENGTH = 512

# HS256 keys shorter than the 256-bit digest weaken the development signature.
DEV_AUTH_SECRET_MIN_LENGTH = 32

# Hosts allowed as plain-http CORS origins, in development only.
LOCAL_ORIGIN_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})


def parse_cors_origins(raw: str | None, environment: Environment) -> tuple[str, ...]:
    """Validate a comma-separated CORS origin allow-list (docs/architecture/authentication.md).

    Each entry must be an exact browser origin (``scheme://host[:port]``, lowercase,
    no path, query, fragment or credentials). No wildcards. ``https`` only, except
    ``http://localhost``-style origins in development.
    """
    origins: list[str] = []
    for entry in (raw or "").split(","):
        origin = entry.strip()
        if not origin:
            continue
        if "*" in origin:
            raise ValueError("HEROOS_CORS_ALLOWED_ORIGINS must not contain wildcards")
        parts = urlsplit(origin)
        if (
            origin != origin.lower()
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.path
            or parts.query
            or parts.fragment
            or origin != f"{parts.scheme}://{parts.netloc}"
        ):
            raise ValueError(
                "HEROOS_CORS_ALLOWED_ORIGINS entries must be lowercase scheme://host[:port] "
                "origins without path, query, fragment or credentials"
            )
        local = parts.netloc.rsplit(":", 1)[0] in LOCAL_ORIGIN_HOSTS
        if parts.scheme == "https" or (
            parts.scheme == "http" and local and environment == "development"
        ):
            origins.append(origin)
            continue
        raise ValueError(
            "HEROOS_CORS_ALLOWED_ORIGINS entries must use https "
            "(plain http only for localhost in development)"
        )
    return tuple(dict.fromkeys(origins))


class Settings(DatabaseSettings):
    """Full API configuration: database plus environment and authentication."""

    # Required, no default: a missing HEROOS_ENV must stop startup rather than
    # silently selecting development.
    heroos_env: Environment

    # Structured application log level (docs/architecture/observability.md).
    # DEBUG adds no sensitive content: redaction does not depend on the level.
    heroos_log_level: LogLevel = "INFO"

    # Authentication. See docs/architecture/authentication.md.
    # Unset means no provider: protected routes reject every request.
    heroos_auth_provider: AuthProviderName | None = None
    heroos_dev_auth_secret: SecretStr | None = None
    heroos_cognito_issuer: str | None = None
    heroos_cognito_app_client_id: str | None = None
    heroos_cognito_jwks_uri: str | None = None
    # Optional resource-server audience. When set, access tokens must carry a
    # matching `aud`; when unset, `aud` is not used for any decision.
    heroos_cognito_resource_audience: str | None = None

    # Provider-neutral OpenID Connect (staging only; docs/architecture/authentication.md §4.3).
    heroos_oidc_issuer: str | None = None
    # The HeroOS API identifier access tokens must carry in `aud`. Required.
    heroos_oidc_audience: str | None = None
    # Comma-separated client IDs allowed to obtain tokens (`client_id`/`azp`). Required.
    heroos_oidc_client_ids: str | None = None
    # Optional; defaults to the `jwks_uri` from OIDC discovery.
    heroos_oidc_jwks_uri: str | None = None
    heroos_oidc_algorithms: str = "RS256,ES256"
    # RFC 9068 JWT access-token profile (typ at+jwt, client_id, jti).
    heroos_oidc_require_rfc9068: bool = True

    # Private object storage. See docs/architecture/private-object-storage.md.
    # Unset means no storage: every storage operation fails; nothing falls back
    # to local disk.
    heroos_storage_provider: StorageProviderName | None = None
    heroos_local_storage_root: Path | None = None

    # Browser origins allowed to call the API cross-origin (comma-separated).
    # Unset means no CORS headers at all. The demo web app calls the API from its
    # server (docs/operations/demo-authentication-deployment.md), so it needs none.
    heroos_cors_allowed_origins: str | None = None

    # The identity operator credential (ADR-008). It belongs only to the operator
    # CLI's shell, never to a running API: declared here so deployed
    # environments can refuse it if it is ever configured.
    heroos_operator_database_url: SecretStr | None = None

    # Self-service founder registration (M1-10C, POST /company-registrations).
    # Off unless explicitly enabled, in every environment: deploying the code
    # does not open public Company creation. Enabling it is an activation step,
    # together with the identity provider's sign-up setting
    # (docs/operations/company-registration.md).
    heroos_self_registration_enabled: bool = False

    # The Disciplinary safety screening (M2-02) asks health-related and other
    # legally sensitive questions about an employee. No privacy basis or
    # retention policy is approved for them yet, so it is off unless an
    # environment that holds only synthetic demo data enables it explicitly;
    # production refuses it. When off, the screening step can't be answered
    # and no intake can be completed (docs/architecture/disciplinary-intake.md).
    heroos_sensitive_screening: SensitiveScreening = "disabled"

    # Workflow progression rules (M2-03): the private rule bundle, a JSON file in
    # server-side storage only this service can read, and the SHA-256 the file
    # must have (set both or neither). Unset: workflow progression is
    # unavailable (fail closed) and everything else works. Set: the bundle is
    # read and verified once at startup, and a missing, changed or invalid file
    # stops startup; nothing falls back to other rules
    # (docs/architecture/workflow-progression.md).
    heroos_rule_bundle_path: Path | None = None
    heroos_rule_bundle_sha256: str | None = None

    # Document templates (M2-04C): the private template bundle, a JSON file in
    # server-side storage only this service can read, and the SHA-256 the file
    # must have (set both or neither). Unset: document previews are unavailable
    # (fail closed) and everything else works. Set: the bundle is read and
    # verified once at startup, together with the rule bundle it was written
    # for; a missing, changed, invalid or mismatched file stops startup, and
    # production refuses synthetic or provisional templates
    # (docs/architecture/document-templates.md).
    heroos_template_bundle_path: Path | None = None
    heroos_template_bundle_sha256: str | None = None

    # Approved knowledge (M2-NEW-04): the private knowledge bundle compiled
    # offline from HeroOS's approved sources, a JSON file in server-side storage
    # only this service can read, and the SHA-256 the file must have (set both
    # or neither). Unset: the knowledge runtime answers "bundle unavailable"
    # (fail closed) and everything else works. Set: the bundle is read and
    # verified once at startup (pin, schema, both digests, safety invariants);
    # a missing, changed or invalid file stops startup, and production refuses
    # synthetic or development content (docs/architecture/knowledge-runtime.md).
    heroos_knowledge_bundle_path: Path | None = None
    heroos_knowledge_bundle_sha256: str | None = None

    # Ask HeroOS's deterministic conversation evaluation (M2-NEW-06): the execution
    # profile approving which knowledge, workflow definition, rule bundle and Condition
    # bindings operate together, a private JSON file plus its SHA-256 (set both or
    # neither), and the shared secret that encrypts and authenticates the trusted state
    # a conversation carries between turns (any API instance can read it; at least 32
    # random bytes, base64url or hex; required with a profile). Unset: deterministic
    # checks are unavailable and say so; nothing else changes. A synthetic or
    # development profile is refused in production
    # (docs/architecture/conversation-evaluation.md).
    heroos_execution_profile_path: Path | None = None
    heroos_execution_profile_sha256: str | None = None
    heroos_evaluation_continuation_key: SecretStr | None = None

    # Hannah AI demo (conversational). Off unless explicitly enabled; then any
    # Company administrator can use it in their own Company's Cases. Production
    # refuses it. The chat never changes a Case and receives no tools
    # (docs/architecture/hannah-ai-demo.md). Its provider is chosen here, never
    # from which keys exist; groq unless set, and anthropic needs its own model.
    heroos_hannah_demo_enabled: bool = False
    heroos_hannah_provider: AiProvider = "groq"
    heroos_hannah_model: str = DEFAULT_HANNAH_MODEL
    # Usage ceilings in this API process's memory (not durable or distributed):
    # messages per account per 5 minutes, and for the whole service per minute
    # and per day, below the provider's shared free-tier quota.
    heroos_hannah_account_limit: Annotated[int, Field(ge=1, le=1000)] = 20
    heroos_hannah_global_limit_per_minute: Annotated[int, Field(ge=1, le=10_000)] = 20
    heroos_hannah_global_limit_per_day: Annotated[int, Field(ge=1, le=1_000_000)] = 900
    # The providers' API keys (server-side only, never logged or returned). Each
    # is used only by the provider it belongs to; the configured provider's key
    # unset: the demo answers 503 and the gateway stays unavailable.
    groq_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    # Ask HeroOS's staging chat-only demo (temporary). Off unless explicitly enabled;
    # production refuses it. On, Ask HeroOS is a plain conversation through the Hannah
    # demo's provider, model, key, instruction, reply check and limits (independent of
    # HEROOS_HANNAH_DEMO_ENABLED): no Case, facts, workflow, outcome or stored
    # conversation, and the persistent Ask HeroOS turn answers 404
    # (docs/architecture/hannah-ai-demo.md).
    heroos_chat_only_demo: bool = False

    # Ask HeroOS's controlled AI conversation gateway (M2-NEW-05). Off unless
    # explicitly enabled. Enabled, it is active only when every prerequisite
    # holds: a provider and model chosen here (never by a client), the
    # provider's key, a valid approved-knowledge bundle, and the reference of
    # HeroOS's approval of this deployment's AI configuration (provider, data
    # protection terms, environment). A bundle that is still development or
    # synthetic content also needs ALLOW_DEVELOPMENT_KNOWLEDGE, which
    # production refuses. Anything missing: the gateway stays unavailable
    # (fail closed) and everything else works (docs/architecture/ai-gateway.md).
    heroos_ai_gateway_enabled: bool = False
    heroos_ai_gateway_provider: AiProvider | None = None
    heroos_ai_gateway_model: str | None = None
    # A model for each phase, when they differ: the understanding (the structured, untrusted
    # reading of the founder's words) and the response (the founder-facing reply). Each falls back
    # to HEROOS_AI_GATEWAY_MODEL; same provider for both.
    heroos_ai_gateway_understanding_model: str | None = None
    heroos_ai_gateway_response_model: str | None = None
    heroos_ai_gateway_approval: str | None = None
    heroos_ai_gateway_allow_development_knowledge: bool = False
    # Founder turns (each up to four provider requests) in this API process's
    # memory: per account per 5 minutes, and for the whole service per minute
    # and per day. Technical abuse ceilings, not a commercial allowance.
    heroos_ai_gateway_account_limit: Annotated[int, Field(ge=1, le=1000)] = 10
    heroos_ai_gateway_global_limit_per_minute: Annotated[int, Field(ge=1, le=10_000)] = 6
    heroos_ai_gateway_global_limit_per_day: Annotated[int, Field(ge=1, le=1_000_000)] = 300

    # Real external AI calls (the gateway and the Hannah demo). Never from an
    # automated test run (pytest, or a harness that sets HEROOS_AUTOMATED_TEST)
    # or local development, whatever gateway, demo or key settings it was given:
    # those processes get an offline provider that fails every request without a
    # network call. A deliberate local live smoke test sets
    # HEROOS_AI_LIVE_SMOKE_ENABLED=true; production refuses it
    # (app/assistant/live.py, docs/architecture/ai-gateway.md).
    heroos_automated_test: bool = False
    heroos_ai_live_smoke_enabled: bool = False
    # The date founders' dates are read against ("yesterday", "on Monday") instead of today: an
    # evaluation harness's fixed clock, so a frozen scenario corpus written for one day reads the
    # same on any day. Unset in every deployment; production refuses it.
    heroos_evaluation_reference_date: date | None = None

    @property
    def ai_gateway_understanding_model(self) -> str | None:
        """The understanding phase's model (HEROOS_AI_GATEWAY_MODEL unless set apart)."""
        return self.heroos_ai_gateway_understanding_model or self.heroos_ai_gateway_model

    @property
    def ai_gateway_response_model(self) -> str | None:
        """The response phase's model (HEROOS_AI_GATEWAY_MODEL unless set apart)."""
        return self.heroos_ai_gateway_response_model or self.heroos_ai_gateway_model

    @model_validator(mode="after")
    def _validate_ai_gateway(self) -> Self:
        for name, model in (
            ("HEROOS_AI_GATEWAY_MODEL", self.heroos_ai_gateway_model),
            ("HEROOS_AI_GATEWAY_UNDERSTANDING_MODEL", self.heroos_ai_gateway_understanding_model),
            ("HEROOS_AI_GATEWAY_RESPONSE_MODEL", self.heroos_ai_gateway_response_model),
        ):
            if model is not None and not HANNAH_MODEL_ID.fullmatch(model):
                raise ValueError(f"{name} must be a model identifier")
        approval = self.heroos_ai_gateway_approval
        if approval is not None and not AI_GATEWAY_APPROVAL.fullmatch(approval):
            raise ValueError("HEROOS_AI_GATEWAY_APPROVAL must be a short reference identifier")
        if self.heroos_env == "production" and self.heroos_ai_gateway_allow_development_knowledge:
            raise ValueError(
                "HEROOS_AI_GATEWAY_ALLOW_DEVELOPMENT_KNOWLEDGE must be false when "
                "HEROOS_ENV=production (only approved knowledge serves customers)"
            )
        if self.heroos_env == "production" and self.heroos_ai_live_smoke_enabled:
            raise ValueError(
                "HEROOS_AI_LIVE_SMOKE_ENABLED must be false when HEROOS_ENV=production "
                "(a local smoke-test switch, never a deployment setting)"
            )
        if self.heroos_env == "production" and self.heroos_evaluation_reference_date is not None:
            raise ValueError(
                "HEROOS_EVALUATION_REFERENCE_DATE must be unset when HEROOS_ENV=production "
                "(an evaluation harness's fixed clock, never a deployment setting)"
            )
        return self

    @model_validator(mode="after")
    def _validate_hannah_demo(self) -> Self:
        if self.heroos_env == "production" and self.heroos_hannah_demo_enabled:
            raise ValueError(
                "HEROOS_HANNAH_DEMO_ENABLED must be false when HEROOS_ENV=production "
                "(a demonstration, not an approved service)"
            )
        if self.heroos_env == "production" and self.heroos_chat_only_demo:
            raise ValueError(
                "HEROOS_CHAT_ONLY_DEMO must be false when HEROOS_ENV=production "
                "(a staging demonstration, not an approved service)"
            )
        if not HANNAH_MODEL_ID.fullmatch(self.heroos_hannah_model):
            raise ValueError("HEROOS_HANNAH_MODEL must be a model identifier")
        if self.heroos_hannah_provider == "anthropic" and (
            self.heroos_hannah_model == DEFAULT_HANNAH_MODEL
        ):
            raise ValueError(
                "HEROOS_HANNAH_MODEL must name an Anthropic model when "
                "HEROOS_HANNAH_PROVIDER=anthropic (the default is a GroqCloud model)"
            )
        return self

    @model_validator(mode="after")
    def _validate_rule_bundle(self) -> Self:
        path, pin = self.heroos_rule_bundle_path, self.heroos_rule_bundle_sha256
        if (path is None) != (pin is None):
            raise ValueError(
                "HEROOS_RULE_BUNDLE_PATH and HEROOS_RULE_BUNDLE_SHA256 must be set together"
            )
        if path is not None and not path.is_absolute():
            raise ValueError("HEROOS_RULE_BUNDLE_PATH must be an absolute path")
        if pin is not None and not RULE_BUNDLE_PIN.fullmatch(pin):
            raise ValueError("HEROOS_RULE_BUNDLE_SHA256 must be 64 lowercase hex characters")
        return self

    @model_validator(mode="after")
    def _validate_template_bundle(self) -> Self:
        path, pin = self.heroos_template_bundle_path, self.heroos_template_bundle_sha256
        if (path is None) != (pin is None):
            raise ValueError(
                "HEROOS_TEMPLATE_BUNDLE_PATH and HEROOS_TEMPLATE_BUNDLE_SHA256 must be set together"
            )
        if path is not None and not path.is_absolute():
            raise ValueError("HEROOS_TEMPLATE_BUNDLE_PATH must be an absolute path")
        if pin is not None and not RULE_BUNDLE_PIN.fullmatch(pin):
            raise ValueError("HEROOS_TEMPLATE_BUNDLE_SHA256 must be 64 lowercase hex characters")
        if path is not None and self.heroos_rule_bundle_path is None:
            # Templates are bound to the rule bundle's stages: never without it.
            raise ValueError("HEROOS_TEMPLATE_BUNDLE_PATH requires HEROOS_RULE_BUNDLE_PATH")
        return self

    @model_validator(mode="after")
    def _validate_knowledge_bundle(self) -> Self:
        path, pin = self.heroos_knowledge_bundle_path, self.heroos_knowledge_bundle_sha256
        if (path is None) != (pin is None):
            raise ValueError(
                "HEROOS_KNOWLEDGE_BUNDLE_PATH and HEROOS_KNOWLEDGE_BUNDLE_SHA256 must be set "
                "together"
            )
        if path is not None and not path.is_absolute():
            raise ValueError("HEROOS_KNOWLEDGE_BUNDLE_PATH must be an absolute path")
        if pin is not None and not RULE_BUNDLE_PIN.fullmatch(pin):
            raise ValueError("HEROOS_KNOWLEDGE_BUNDLE_SHA256 must be 64 lowercase hex characters")
        return self

    @model_validator(mode="after")
    def _validate_execution_profile(self) -> Self:
        path, pin = self.heroos_execution_profile_path, self.heroos_execution_profile_sha256
        if (path is None) != (pin is None):
            raise ValueError(
                "HEROOS_EXECUTION_PROFILE_PATH and HEROOS_EXECUTION_PROFILE_SHA256 must be set "
                "together"
            )
        if path is not None and not path.is_absolute():
            raise ValueError("HEROOS_EXECUTION_PROFILE_PATH must be an absolute path")
        if pin is not None and not RULE_BUNDLE_PIN.fullmatch(pin):
            raise ValueError("HEROOS_EXECUTION_PROFILE_SHA256 must be 64 lowercase hex characters")
        key = self.heroos_evaluation_continuation_key
        if path is not None and key is None:
            # Trusted state across turns and API instances needs a shared secret.
            raise ValueError(
                "HEROOS_EXECUTION_PROFILE_PATH requires HEROOS_EVALUATION_CONTINUATION_KEY"
            )
        if key is not None:
            try:
                parse_key(key.get_secret_value())
            except ValueError as error:
                raise ValueError(
                    "HEROOS_EVALUATION_CONTINUATION_KEY must be base64url or hex of at least 32 "
                    "random bytes"
                ) from error
        return self

    @model_validator(mode="after")
    def _validate_sensitive_screening(self) -> Self:
        if self.heroos_env == "production" and self.heroos_sensitive_screening != "disabled":
            raise ValueError(
                "HEROOS_SENSITIVE_SCREENING must be disabled when HEROOS_ENV=production "
                "(no approved privacy basis for the screening answers)"
            )
        return self

    @model_validator(mode="after")
    def _validate_cors(self) -> Self:
        parse_cors_origins(self.heroos_cors_allowed_origins, self.heroos_env)
        return self

    @property
    def cors_allowed_origins(self) -> tuple[str, ...]:
        return parse_cors_origins(self.heroos_cors_allowed_origins, self.heroos_env)

    @model_validator(mode="after")
    def _validate_storage(self) -> Self:
        if self.heroos_env != "development":
            # Deployed environments never store private objects on local disk.
            if self.heroos_storage_provider == "local":
                raise ValueError(
                    "HEROOS_STORAGE_PROVIDER=local is not allowed when "
                    f"HEROOS_ENV={self.heroos_env}"
                )
            if self.heroos_local_storage_root is not None:
                raise ValueError("HEROOS_LOCAL_STORAGE_ROOT must not be set outside development")

        if self.heroos_storage_provider == "local":
            root = self.heroos_local_storage_root
            if root is None or not root.is_absolute():
                raise ValueError(
                    "HEROOS_LOCAL_STORAGE_ROOT must be an absolute path for the local provider"
                )
        elif self.heroos_local_storage_root is not None:
            raise ValueError("HEROOS_LOCAL_STORAGE_ROOT is only valid with the local provider")

        return self

    @model_validator(mode="after")
    def _validate_authentication(self) -> Self:
        if self.heroos_env != "development":
            # Deployed environments fail closed: production is Cognito only,
            # staging Cognito or OIDC, and no development signing material may be
            # present at all.
            allowed = ALLOWED_AUTH_PROVIDERS[self.heroos_env]
            if self.heroos_auth_provider not in allowed:
                names = " or ".join(f"'{name}'" for name in sorted(allowed))
                raise ValueError(
                    f"HEROOS_AUTH_PROVIDER must be {names} when HEROOS_ENV={self.heroos_env}"
                )
            if self.heroos_dev_auth_secret is not None:
                raise ValueError("HEROOS_DEV_AUTH_SECRET must not be set outside development")

        if self.heroos_auth_provider == "development":
            secret = self.heroos_dev_auth_secret
            if secret is None or len(secret.get_secret_value()) < DEV_AUTH_SECRET_MIN_LENGTH:
                raise ValueError(
                    "HEROOS_DEV_AUTH_SECRET must be at least "
                    f"{DEV_AUTH_SECRET_MIN_LENGTH} characters for the development provider"
                )

        if self.heroos_auth_provider == "cognito":
            if not self.heroos_cognito_issuer or not self.heroos_cognito_app_client_id:
                raise ValueError(
                    "HEROOS_COGNITO_ISSUER and HEROOS_COGNITO_APP_CLIENT_ID are required "
                    "for the cognito provider"
                )
            issuer = self.heroos_cognito_issuer
            if not issuer.startswith("https://") or issuer.endswith("/"):
                # Compared verbatim with the token `iss` claim, which has no
                # trailing slash.
                raise ValueError("HEROOS_COGNITO_ISSUER must be an https URL without a trailing /")
            if self.heroos_cognito_jwks_uri and not self.heroos_cognito_jwks_uri.startswith(
                "https://"
            ):
                raise ValueError("HEROOS_COGNITO_JWKS_URI must be an https URL")
            audience = self.heroos_cognito_resource_audience
            if audience is not None and not audience.strip():
                raise ValueError("HEROOS_COGNITO_RESOURCE_AUDIENCE must not be blank when set")

        if self.heroos_auth_provider == "oidc":
            self._validate_oidc()

        issuers: tuple[tuple[str, str | None], ...] = (
            ("HEROOS_COGNITO_ISSUER", self.heroos_cognito_issuer),
            ("HEROOS_OIDC_ISSUER", self.heroos_oidc_issuer),
        )
        for name, configured in issuers:
            # Identities are bound to the exact issuer (user_identities.issuer).
            if configured is not None and len(configured) > MAX_ISSUER_LENGTH:
                raise ValueError(f"{name} must be at most {MAX_ISSUER_LENGTH} characters")

        return self

    def _validate_oidc(self) -> None:
        issuer = self.heroos_oidc_issuer or ""
        parts = urlsplit(issuer)
        if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment:
            raise ValueError("HEROOS_OIDC_ISSUER must be an https URL without query or fragment")
        audience = (self.heroos_oidc_audience or "").strip()
        if not audience:
            raise ValueError("HEROOS_OIDC_AUDIENCE is required for the oidc provider")
        if not self.oidc_client_ids:
            # Without an allow-list any client registered at the issuer could
            # obtain an access token the API would accept.
            raise ValueError("HEROOS_OIDC_CLIENT_IDS is required for the oidc provider")
        if audience in self.oidc_client_ids:
            # ID tokens carry the client ID as `aud`: an API audience equal to a
            # client ID would let an ID token pass the audience check.
            raise ValueError("HEROOS_OIDC_AUDIENCE must differ from every client ID")
        if self.heroos_oidc_jwks_uri and not self.heroos_oidc_jwks_uri.startswith("https://"):
            raise ValueError("HEROOS_OIDC_JWKS_URI must be an https URL")
        algorithms = self.oidc_algorithms
        if not algorithms or not set(algorithms) <= OIDC_SUPPORTED_ALGORITHMS:
            raise ValueError(
                "HEROOS_OIDC_ALGORITHMS must list asymmetric algorithms only "
                f"({', '.join(sorted(OIDC_SUPPORTED_ALGORITHMS))})"
            )

    @property
    def oidc_algorithms(self) -> tuple[str, ...]:
        return tuple(a.strip() for a in self.heroos_oidc_algorithms.split(",") if a.strip())

    @property
    def oidc_client_ids(self) -> frozenset[str]:
        return frozenset(
            c.strip() for c in (self.heroos_oidc_client_ids or "").split(",") if c.strip()
        )

    @model_validator(mode="after")
    def _validate_database(self) -> Self:
        # No environment has a built-in database credential to fall back to
        # (docs/operations/database-credentials.md).
        if self.database_url is None:
            raise ValueError(
                f"DATABASE_URL must be explicitly configured when HEROOS_ENV={self.heroos_env}; "
                "there is no default (local development: `make env-init`)"
            )
        if self.heroos_env == "development":
            return self
        # Deployed environments never use a local development database, and the
        # API never receives the migration/admin credential.
        try:
            host = make_url(self.database_url.get_secret_value()).host
        except ArgumentError:
            # `from None`: SQLAlchemy's message quotes the raw URL.
            raise ValueError("DATABASE_URL is not a valid database URL") from None
        if host in LOCAL_DATABASE_HOSTS:
            raise ValueError(
                f"DATABASE_URL must not name a local development database host when "
                f"HEROOS_ENV={self.heroos_env}"
            )
        if "migration_database_url" in self.model_fields_set:
            raise ValueError(
                "MIGRATION_DATABASE_URL must not be provided to the API outside development"
            )
        if "heroos_operator_database_url" in self.model_fields_set:
            raise ValueError(
                "HEROOS_OPERATOR_DATABASE_URL must not be provided to the API outside development"
            )
        return self

    @property
    def cognito_jwks_uri(self) -> str | None:
        if self.heroos_cognito_jwks_uri:
            return self.heroos_cognito_jwks_uri
        if self.heroos_cognito_issuer:
            return f"{self.heroos_cognito_issuer}/.well-known/jwks.json"
        return None


# Required fields come from the environment / .env, not constructor arguments.
settings = Settings()  # type: ignore[call-arg]
