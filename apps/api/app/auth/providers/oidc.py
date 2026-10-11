"""Provider-neutral OpenID Connect access-token verification (pre-M5 demo).

HeroOS accepts **access tokens** issued for the HeroOS API by a standards-based
OpenID Provider (docs/architecture/authentication.md §4.3). Validation:

- the header ``alg`` must be in the configured allow-list (asymmetric only:
  RS/PS/ES); ``none`` and HMAC algorithms are never accepted, so a token signed
  with the public key as an HMAC secret is rejected before any key lookup
- with the RFC 9068 profile (default) the header ``typ`` must be ``at+jwt``
- signature against the issuer's JWKS, key selected by ``kid``; the JWKS URI
  comes from OIDC discovery (``<issuer>/.well-known/openid-configuration``),
  whose ``issuer`` must equal the configured issuer exactly and whose
  ``jwks_uri`` must be on the issuer's origin (other hosts only through an
  explicit ``HEROOS_OIDC_JWKS_URI``). Discovery and keys are fetched over https
  with certificate and host-name verification, never following redirects
- ``iss`` equals the configured issuer; ``aud`` contains the configured API
  audience; ``exp`` / ``iat`` present and ``exp`` not passed; ``nbf`` honoured
- RFC 9068 profile: ``client_id`` and ``jti`` required
- the authorized client must be present (``client_id`` and/or ``azp``; when
  both are present they must agree), a string, and one of the configured client
  IDs, which are required. This holds with and without the RFC 9068 profile
- ID tokens are rejected: their ``aud`` is a client ID (never the API
  audience, enforced by settings validation), they lack ``typ: at+jwt``, and
  tokens carrying ID-token-only claims (``nonce``, ``at_hash``, ``c_hash``) are refused
- non-empty ``sub``, mapped to ``users.identity_subject``

Discovery and keys are fetched lazily on first use, so startup never contacts
the provider. Any discovery or key failure fails closed with 401.
"""

import json
import ssl
import threading
import urllib.request
from collections.abc import Callable, Collection, Mapping
from typing import Any, Final
from urllib.parse import urlsplit

import jwt

from app.auth.exceptions import AuthenticationError
from app.auth.models import VerifiedIdentity
from app.auth.providers.base import require_subject

SUPPORTED_ALGORITHMS: Final = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"}
)
DEFAULT_ALGORITHMS: Final = ("RS256", "ES256")
DISCOVERY_PATH: Final = "/.well-known/openid-configuration"
RFC9068_TYPES: Final = frozenset({"at+jwt", "application/at+jwt"})
GENERIC_TYPES: Final = RFC9068_TYPES | {"jwt"}
ID_TOKEN_ONLY_CLAIMS: Final = ("nonce", "at_hash", "c_hash")
DISCOVERY_TIMEOUT_SECONDS: Final = 5
MAX_DISCOVERY_BYTES: Final = 256 * 1024
JWKS_CACHE_LIFESPAN_SECONDS: Final = 3600
JWKS_FETCH_TIMEOUT_SECONDS: Final = 5

FetchJson = Callable[[str], Any]


def tls_context() -> ssl.SSLContext:
    """Certificate and host-name verification, explicitly (not environment-dependent)."""
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """A 3xx is an error: discovery must be served at the issuer's own URL."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _open(url: str, context: ssl.SSLContext | None) -> bytes:
    handlers: list[Any] = [_RefuseRedirects()]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with opener.open(request, timeout=DISCOVERY_TIMEOUT_SECONDS) as response:
        body: bytes = response.read(MAX_DISCOVERY_BYTES + 1)
    if len(body) > MAX_DISCOVERY_BYTES:
        raise ValueError("discovery document too large")
    return body


def discovery_url(issuer: str) -> str:
    """OIDC Discovery 1.0 §4: the well-known path appended to the issuer."""
    return issuer.rstrip("/") + DISCOVERY_PATH


def fetch_json(url: str) -> Any:
    """GET a JSON document over verified https; no redirects, bounded size."""
    if urlsplit(url).scheme != "https":
        raise ValueError("discovery must use https")
    return json.loads(_open(url, tls_context()))


def build_oidc_jwks_client(jwks_uri: str) -> jwt.PyJWKClient:
    # PyJWKClient refuses redirects and rate-limits refetches on unknown `kid`;
    # TLS verification is made explicit here.
    return jwt.PyJWKClient(
        jwks_uri,
        cache_keys=True,
        lifespan=JWKS_CACHE_LIFESPAN_SECONDS,
        timeout=JWKS_FETCH_TIMEOUT_SECONDS,
        ssl_context=tls_context(),
    )


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


class OidcKeySource:
    """Resolves the issuer's JWKS client lazily, via discovery unless overridden."""

    def __init__(
        self,
        issuer: str,
        *,
        jwks_uri: str | None = None,
        fetch: FetchJson = fetch_json,
        client_factory: Callable[[str], jwt.PyJWKClient] = build_oidc_jwks_client,
    ) -> None:
        self._issuer = issuer
        self._jwks_uri = jwks_uri
        self._fetch = fetch
        self._client_factory = client_factory
        self._client: jwt.PyJWKClient | None = None
        self._lock = threading.Lock()

    def _resolve_jwks_uri(self) -> str:
        if self._jwks_uri is not None:
            return self._jwks_uri
        try:
            metadata = self._fetch(discovery_url(self._issuer))
        except Exception:  # noqa: BLE001 - any network/parse failure fails closed
            raise AuthenticationError("oidc discovery unavailable") from None
        if not isinstance(metadata, Mapping) or metadata.get("issuer") != self._issuer:
            raise AuthenticationError("oidc discovery issuer mismatch")
        jwks_uri = metadata.get("jwks_uri")
        if not isinstance(jwks_uri, str) or not jwks_uri.startswith("https://"):
            raise AuthenticationError("oidc discovery jwks_uri missing or not https")
        # Signing keys are trusted only from the issuer's own origin. A provider
        # that serves keys elsewhere must be configured explicitly
        # (HEROOS_OIDC_JWKS_URI), never by following discovery to another host.
        if _origin(jwks_uri) != _origin(self._issuer):
            raise AuthenticationError("oidc discovery jwks_uri is not on the issuer's origin")
        return jwks_uri

    def client(self) -> jwt.PyJWKClient:
        with self._lock:
            if self._client is None:
                # Only a successful resolution is cached; failures retry next time.
                self._client = self._client_factory(self._resolve_jwks_uri())
            return self._client


class OidcAccessTokenProvider:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        keys: OidcKeySource,
        client_ids: Collection[str],
        algorithms: Collection[str] = DEFAULT_ALGORITHMS,
        require_rfc9068: bool = True,
    ) -> None:
        unsupported = set(algorithms) - SUPPORTED_ALGORITHMS
        if not algorithms or unsupported:
            raise ValueError(
                "OIDC algorithms must be a non-empty subset of the asymmetric algorithms"
            )
        if not client_ids or any(not isinstance(c, str) or not c for c in client_ids):
            # Without an allow-list any client of the issuer could obtain a usable token.
            raise ValueError("OIDC client IDs must be a non-empty list of non-empty strings")
        self._issuer = issuer
        self._audience = audience
        self._keys = keys
        self._algorithms = list(algorithms)
        self._client_ids = frozenset(client_ids)
        self._require_rfc9068 = require_rfc9068

    def _check_header(self, token: str) -> None:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"oidc token rejected ({type(exc).__name__})") from None
        if header.get("alg") not in self._algorithms:
            raise AuthenticationError("oidc token algorithm not allowed")
        token_type = str(header.get("typ", "")).lower()
        if self._require_rfc9068:
            if token_type not in RFC9068_TYPES:
                raise AuthenticationError("oidc token is not an RFC 9068 access token (typ)")
        elif token_type and token_type not in GENERIC_TYPES:
            raise AuthenticationError("oidc token type not accepted")

    def authenticate(self, token: str) -> VerifiedIdentity:
        self._check_header(token)
        required = ["exp", "iat", "iss", "sub", "aud"]
        if self._require_rfc9068:
            required += ["client_id", "jti"]
        try:
            signing_key = self._keys.client().get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=self._algorithms,
                issuer=self._issuer,
                audience=self._audience,
                options={"require": required},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"oidc token rejected ({type(exc).__name__})") from None

        if any(claim in claims for claim in ID_TOKEN_ONLY_CLAIMS):
            raise AuthenticationError("oidc token carries ID-token claims")
        self._check_client(claims)

        return VerifiedIdentity(subject=require_subject(claims), issuer=self._issuer)

    def _check_client(self, claims: Mapping[str, Any]) -> None:
        """The authorized client must be present, unambiguous and allow-listed.

        RFC 9068 names it `client_id`; other profiles use `azp`. Both profiles
        are checked the same way, so disabling RFC 9068 never disables this.
        """
        candidates = [claims[name] for name in ("client_id", "azp") if name in claims]
        if not candidates:
            raise AuthenticationError("oidc token has no client identity")
        if any(not isinstance(value, str) for value in candidates):
            raise AuthenticationError("oidc token client identity is malformed")
        if len(set(candidates)) != 1:
            raise AuthenticationError("oidc token client_id and azp disagree")
        if candidates[0] not in self._client_ids:
            raise AuthenticationError("oidc token client is not allowed")
