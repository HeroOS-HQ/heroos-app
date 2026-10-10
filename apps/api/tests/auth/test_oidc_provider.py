"""Provider-neutral OIDC access-token verification (no network, no AWS).

Keys and JWKS are generated in-process; discovery documents are served by a
stub fetcher. The production ``PyJWKClient`` key-selection code still runs.
"""

import base64
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm
from pydantic import ValidationError

from app.auth.exceptions import AuthenticationConfigurationError, AuthenticationError
from app.auth.providers import build_authentication_provider
from app.auth.providers.oidc import OidcAccessTokenProvider, OidcKeySource, discovery_url
from app.core.config import Settings
from tests.auth.conftest import LocalJWKClient

ISSUER = "https://heroos-demo.idp.test.invalid/"
AUDIENCE = "https://api.heroos-demo.test.invalid"
CLIENT_ID = "web-client-123"
RSA_KID = "rsa-key"
EC_KID = "ec-key"
API_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def ec_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def jwks(signing_key: rsa.RSAPrivateKey, ec_key: ec.EllipticCurvePrivateKey) -> dict[str, Any]:
    rsa_jwk: dict[str, Any] = RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    rsa_jwk.update({"kid": RSA_KID, "alg": "RS256", "use": "sig"})
    ec_jwk: dict[str, Any] = ECAlgorithm.to_jwk(ec_key.public_key(), as_dict=True)
    ec_jwk.update({"kid": EC_KID, "alg": "ES256", "use": "sig"})
    return {"keys": [rsa_jwk, ec_jwk]}


class Discovery:
    """Stub OIDC discovery: records fetches; serves a document or raises."""

    def __init__(self, document: Any = None, error: Exception | None = None) -> None:
        self.document = document
        self.error = error
        self.urls: list[str] = []

    def __call__(self, url: str) -> Any:
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        return self.document


def good_discovery() -> Discovery:
    return Discovery(
        {"issuer": ISSUER, "jwks_uri": "https://heroos-demo.idp.test.invalid/.well-known/jwks.json"}
    )


def make_provider(
    jwks: dict[str, Any], discovery: Discovery | None = None, **kwargs: Any
) -> OidcAccessTokenProvider:
    keys = OidcKeySource(
        ISSUER,
        fetch=discovery or good_discovery(),
        client_factory=lambda _uri: LocalJWKClient(jwks),
    )
    kwargs.setdefault("client_ids", [CLIENT_ID])
    return OidcAccessTokenProvider(issuer=ISSUER, audience=AUDIENCE, keys=keys, **kwargs)


def access_token(
    key: Any, *, kid: str = RSA_KID, alg: str = "RS256", typ: str | None = "at+jwt", **claims: Any
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "auth0|alpha",
        "aud": [AUDIENCE, "https://heroos-demo.idp.test.invalid/userinfo"],
        "client_id": CLIENT_ID,
        "iat": now,
        "exp": now + 600,
        "jti": str(uuid.uuid4()),
        "scope": "openid",
    }
    payload.update(claims)
    payload = {k: v for k, v in payload.items() if v is not None}
    headers: dict[str, Any] = {"kid": kid}
    if typ is not None:
        headers["typ"] = typ
    return jwt.encode(payload, key, algorithm=alg, headers=headers)


# --- accepted tokens ----------------------------------------------------------


def test_rfc9068_access_token_accepted(
    jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey
) -> None:
    discovery = good_discovery()
    identity = make_provider(jwks, discovery).authenticate(access_token(signing_key))

    assert identity.subject == "auth0|alpha"
    assert identity.issuer == ISSUER
    assert discovery.urls == [
        "https://heroos-demo.idp.test.invalid/.well-known/openid-configuration"
    ]


def test_es256_access_token_accepted(
    jwks: dict[str, Any], ec_key: ec.EllipticCurvePrivateKey
) -> None:
    token = access_token(ec_key, kid=EC_KID, alg="ES256")
    assert make_provider(jwks).authenticate(token).subject == "auth0|alpha"


def test_single_string_audience_accepted(
    jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey
) -> None:
    assert make_provider(jwks).authenticate(access_token(signing_key, aud=AUDIENCE))


def test_azp_used_when_client_id_absent_in_generic_profile(
    jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey
) -> None:
    provider = make_provider(jwks, require_rfc9068=False)
    token = access_token(signing_key, typ="JWT", client_id=None, jti=None, azp=CLIENT_ID)
    assert provider.authenticate(token).subject == "auth0|alpha"


def test_discovery_runs_once_and_never_at_construction(
    jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey
) -> None:
    discovery = good_discovery()
    provider = make_provider(jwks, discovery)
    assert discovery.urls == []
    provider.authenticate(access_token(signing_key))
    provider.authenticate(access_token(signing_key))
    assert len(discovery.urls) == 1


# --- rejected tokens ----------------------------------------------------------


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param({"iss": "https://other-idp.test.invalid/"}, id="other-issuer"),
        pytest.param({"iss": ISSUER.rstrip("/")}, id="issuer-without-trailing-slash"),
        pytest.param({"aud": "https://other-api.test.invalid"}, id="other-audience"),
        pytest.param({"aud": CLIENT_ID}, id="client-id-audience"),
        pytest.param({"aud": None}, id="no-audience"),
        pytest.param({"exp": int(time.time()) - 1, "iat": int(time.time()) - 600}, id="expired"),
        pytest.param({"exp": None}, id="no-exp"),
        pytest.param({"iat": None}, id="no-iat"),
        pytest.param({"nbf": int(time.time()) + 300}, id="not-yet-valid"),
        pytest.param({"sub": None}, id="no-sub"),
        pytest.param({"sub": ""}, id="empty-sub"),
        pytest.param({"client_id": None}, id="no-client-id"),
        pytest.param({"jti": None}, id="no-jti"),
        pytest.param({"client_id": "another-client"}, id="other-client"),
        pytest.param({"nonce": "n-0S6_WzA2Mj"}, id="nonce-claim"),
        pytest.param({"at_hash": "77QmUPtjPfzWtF2AnpK9RQ"}, id="at-hash-claim"),
        pytest.param({"c_hash": "LDktKdoQak3Pk0cnXxCltA"}, id="c-hash-claim"),
    ],
)
def test_invalid_claims_rejected(
    jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey, claims: dict[str, Any]
) -> None:
    with pytest.raises(AuthenticationError):
        make_provider(jwks).authenticate(access_token(signing_key, **claims))


def test_id_token_rejected(jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey) -> None:
    """A realistic OIDC ID token: aud = client ID, typ JWT, nonce, at_hash."""
    id_token = access_token(
        signing_key,
        typ="JWT",
        aud=CLIENT_ID,
        client_id=None,
        jti=None,
        azp=CLIENT_ID,
        nonce="abc",
        at_hash="def",
        email="alpha@example.invalid",
    )
    with pytest.raises(AuthenticationError):
        make_provider(jwks).authenticate(id_token)
    with pytest.raises(AuthenticationError):
        make_provider(jwks, require_rfc9068=False).authenticate(id_token)


def test_id_token_with_api_audience_still_rejected_by_typ_and_claims(
    jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey
) -> None:
    token = access_token(signing_key, typ="JWT", nonce="abc")
    with pytest.raises(AuthenticationError):
        make_provider(jwks).authenticate(token)
    with pytest.raises(AuthenticationError):
        make_provider(jwks, require_rfc9068=False).authenticate(token)


@pytest.mark.parametrize("typ", [None, "JWT", "id+jwt", "dpop+jwt"])
def test_rfc9068_profile_requires_at_jwt_type(
    jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey, typ: str | None
) -> None:
    with pytest.raises(AuthenticationError):
        make_provider(jwks).authenticate(access_token(signing_key, typ=typ))


def test_untrusted_signature_rejected(
    jwks: dict[str, Any], untrusted_key: rsa.RSAPrivateKey
) -> None:
    with pytest.raises(AuthenticationError):
        make_provider(jwks).authenticate(access_token(untrusted_key))


def test_unknown_kid_rejected(jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey) -> None:
    with pytest.raises(AuthenticationError):
        make_provider(jwks).authenticate(access_token(signing_key, kid="unknown"))


def test_algorithm_outside_allow_list_rejected(
    jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey
) -> None:
    provider = make_provider(jwks, algorithms=["ES256"])
    with pytest.raises(AuthenticationError, match="algorithm"):
        provider.authenticate(access_token(signing_key))


def test_hmac_with_public_key_rejected_before_key_lookup(
    jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey
) -> None:
    public_pem = signing_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "at+jwt", "kid": RSA_KID}).encode()
    ).rstrip(b"=")
    payload = base64.urlsafe_b64encode(json.dumps({"iss": ISSUER, "sub": "x"}).encode()).rstrip(
        b"="
    )
    import hashlib
    import hmac

    signature = base64.urlsafe_b64encode(
        hmac.new(public_pem, header + b"." + payload, hashlib.sha256).digest()
    ).rstrip(b"=")
    forged = b".".join([header, payload, signature]).decode()
    discovery = good_discovery()
    with pytest.raises(AuthenticationError, match="algorithm"):
        make_provider(jwks, discovery).authenticate(forged)
    assert discovery.urls == []


def test_alg_none_rejected(jwks: dict[str, Any]) -> None:
    token = jwt.encode(
        {"iss": ISSUER, "sub": "x", "aud": AUDIENCE},
        None,
        algorithm="none",
        headers={"typ": "at+jwt"},
    )
    with pytest.raises(AuthenticationError):
        make_provider(jwks).authenticate(token)


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.b.c", "eyJhbGciOiJSUzI1NiJ9.e30"])
def test_malformed_tokens_rejected(jwks: dict[str, Any], token: str) -> None:
    with pytest.raises(AuthenticationError):
        make_provider(jwks).authenticate(token)


@pytest.mark.parametrize(
    "discovery",
    [
        pytest.param(Discovery(error=OSError("unreachable")), id="unreachable"),
        pytest.param(Discovery(document=["not", "an", "object"]), id="not-an-object"),
        pytest.param(
            Discovery(
                {
                    "issuer": "https://evil.test.invalid/",
                    "jwks_uri": "https://evil.test.invalid/jwks",
                }
            ),
            id="issuer-mismatch",
        ),
        pytest.param(Discovery({"issuer": ISSUER}), id="no-jwks-uri"),
        pytest.param(
            Discovery({"issuer": ISSUER, "jwks_uri": "http://heroos-demo.idp.test.invalid/jwks"}),
            id="http-jwks",
        ),
    ],
)
def test_bad_discovery_fails_closed_and_is_retried(
    jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey, discovery: Discovery
) -> None:
    provider = make_provider(jwks, discovery)
    for _ in range(2):
        with pytest.raises(AuthenticationError):
            provider.authenticate(access_token(signing_key))
    assert len(discovery.urls) == 2  # failures are never cached


def test_configured_jwks_uri_skips_discovery(
    jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey
) -> None:
    discovery = good_discovery()
    used: list[str] = []
    keys = OidcKeySource(
        ISSUER,
        jwks_uri="https://keys.test.invalid/jwks.json",
        fetch=discovery,
        client_factory=lambda uri: used.append(uri) or LocalJWKClient(jwks),
    )
    provider = OidcAccessTokenProvider(issuer=ISSUER, audience=AUDIENCE, keys=keys)
    provider.authenticate(access_token(signing_key))
    assert discovery.urls == []
    assert used == ["https://keys.test.invalid/jwks.json"]


def test_discovery_url_follows_the_spec() -> None:
    assert discovery_url("https://idp.test/") == "https://idp.test/.well-known/openid-configuration"
    assert (
        discovery_url("https://idp.test/realms/x")
        == "https://idp.test/realms/x/.well-known/openid-configuration"
    )


@pytest.mark.parametrize("algorithms", [[], ["HS256"], ["none"], ["RS256", "HS256"]])
def test_provider_refuses_unsafe_algorithm_lists(
    jwks: dict[str, Any], algorithms: list[str]
) -> None:
    with pytest.raises(ValueError):
        make_provider(jwks, algorithms=algorithms)


# --- settings and environment rules -------------------------------------------

OIDC = {
    "heroos_auth_provider": "oidc",
    "heroos_oidc_issuer": ISSUER,
    "heroos_oidc_audience": AUDIENCE,
    "heroos_oidc_client_ids": CLIENT_ID,
}
DEPLOYED_DATABASE_URL = "postgresql+psycopg://heroos_app@db.test.invalid/heroos"


def settings(environment: str = "staging", **values: Any) -> Settings:
    if environment != "development":
        values.setdefault("database_url", DEPLOYED_DATABASE_URL)
    return Settings(_env_file=None, heroos_env=environment, **{**OIDC, **values})  # type: ignore[call-arg]


def test_staging_accepts_oidc_and_builds_provider_without_network() -> None:
    provider = build_authentication_provider(settings())
    assert isinstance(provider, OidcAccessTokenProvider)


def test_development_accepts_oidc() -> None:
    assert isinstance(
        build_authentication_provider(settings("development")), OidcAccessTokenProvider
    )


def test_production_refuses_oidc() -> None:
    with pytest.raises(ValidationError) as exc_info:
        settings("production")
    assert "HEROOS_AUTH_PROVIDER must be 'cognito' when HEROOS_ENV=production" in str(
        exc_info.value
    )


def test_provider_factory_rechecks_production() -> None:
    config = settings()
    config.heroos_env = "production"  # bypass validation
    with pytest.raises(AuthenticationConfigurationError):
        build_authentication_provider(config)


def test_staging_still_refuses_development_provider_and_secret() -> None:
    with pytest.raises(ValidationError):
        settings(heroos_auth_provider="development", heroos_dev_auth_secret="x" * 40)
    with pytest.raises(ValidationError):
        settings(heroos_dev_auth_secret="x" * 40)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"heroos_oidc_issuer": None}, id="no-issuer"),
        pytest.param({"heroos_oidc_issuer": "http://idp.test.invalid/"}, id="http-issuer"),
        pytest.param({"heroos_oidc_issuer": "https://idp.test.invalid/?x=1"}, id="issuer-query"),
        pytest.param({"heroos_oidc_issuer": "not a url"}, id="issuer-garbage"),
        pytest.param({"heroos_oidc_audience": None}, id="no-audience"),
        pytest.param({"heroos_oidc_audience": "  "}, id="blank-audience"),
        pytest.param({"heroos_oidc_audience": CLIENT_ID}, id="audience-equals-client-id"),
        pytest.param({"heroos_oidc_jwks_uri": "http://keys.test.invalid/jwks"}, id="http-jwks"),
        pytest.param({"heroos_oidc_algorithms": "HS256"}, id="hmac"),
        pytest.param({"heroos_oidc_algorithms": "none"}, id="none"),
        pytest.param({"heroos_oidc_algorithms": " , "}, id="empty"),
    ],
)
def test_invalid_oidc_settings_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        settings(**overrides)


def test_oidc_validation_errors_do_not_echo_values() -> None:
    marker = "https://secret-marker.test.invalid/?leak=1"
    with pytest.raises(ValidationError) as exc_info:
        settings(heroos_oidc_issuer=marker)
    assert marker not in str(exc_info.value)


def test_application_starts_in_staging_with_oidc_without_contacting_the_provider() -> None:
    env = {
        "PATH": "/usr/bin:/bin",
        "HEROOS_ENV": "staging",
        "DATABASE_URL": DEPLOYED_DATABASE_URL,
        "HEROOS_AUTH_PROVIDER": "oidc",
        "HEROOS_OIDC_ISSUER": ISSUER,  # .invalid: any network attempt would fail
        "HEROOS_OIDC_AUDIENCE": AUDIENCE,
    }
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
