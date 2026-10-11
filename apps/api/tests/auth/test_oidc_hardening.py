"""Regression tests for the OIDC security review (client allow-list, discovery trust).

Also pins the token profile of the intended hosted provider (Auth0 with the RFC
9068 access-token profile) so the verifier is proven against its actual shape.
"""

import http.server
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pydantic import ValidationError

from app.auth.exceptions import AuthenticationError
from app.auth.providers.oidc import (
    OidcAccessTokenProvider,
    OidcKeySource,
    _open,
    build_oidc_jwks_client,
    fetch_json,
    tls_context,
)
from app.core.config import Settings
from tests.auth.conftest import LocalJWKClient

ISSUER = "https://heroos-demo.eu.auth0.com/"
AUDIENCE = "https://api.heroos-demo.example"
CLIENT_ID = "aBcD1234WebClientIdXyZ"
KID = "auth0-style-kid"
API_ROOT = Path(__file__).resolve().parents[2]

# Discovery metadata shaped like a real Auth0 tenant's (issuer with trailing
# slash; endpoints and keys on the issuer's origin; checked against
# https://samples.auth0.com/.well-known/openid-configuration on 2026-10-11).
AUTH0_DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}authorize",
    "token_endpoint": f"{ISSUER}oauth/token",
    "jwks_uri": f"{ISSUER}.well-known/jwks.json",
    "end_session_endpoint": f"{ISSUER}oidc/logout",
    "response_types_supported": ["code", "token", "id_token"],
    "code_challenge_methods_supported": ["S256", "plain"],
}


@pytest.fixture
def jwks(signing_key: rsa.RSAPrivateKey) -> dict[str, Any]:
    jwk: dict[str, Any] = RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return {"keys": [jwk]}


def provider(
    jwks: dict[str, Any], *, discovery: Any = None, **kwargs: Any
) -> OidcAccessTokenProvider:
    used_uris: list[str] = []

    def factory(uri: str) -> LocalJWKClient:
        used_uris.append(uri)
        return LocalJWKClient(jwks)

    keys = OidcKeySource(
        ISSUER,
        fetch=lambda _url: AUTH0_DISCOVERY if discovery is None else discovery,
        client_factory=factory,
    )
    kwargs.setdefault("client_ids", [CLIENT_ID])
    instance = OidcAccessTokenProvider(issuer=ISSUER, audience=AUDIENCE, keys=keys, **kwargs)
    instance.used_jwks_uris = used_uris  # type: ignore[attr-defined]
    return instance


def token(key: Any, *, typ: str = "at+jwt", **claims: Any) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "auth0|6720c1f0a1b2c3d4e5f60718",
        "aud": [AUDIENCE, f"{ISSUER}userinfo"],
        "iat": now,
        "exp": now + 3600,
        "scope": "openid",
        "client_id": CLIENT_ID,
        "jti": str(uuid.uuid4()),
    }
    payload.update(claims)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, key, algorithm="RS256", headers={"typ": typ, "kid": KID})


# --- intended provider profile -----------------------------------------------


def test_auth0_rfc9068_profile_token_is_accepted(
    jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey
) -> None:
    """Auth0 'RFC 9068' JWT profile: typ at+jwt, client_id, jti, aud incl. userinfo."""
    identity = provider(jwks).authenticate(token(signing_key))
    assert identity.subject == "auth0|6720c1f0a1b2c3d4e5f60718"


def test_auth0_default_profile_token_is_rejected_under_rfc9068(
    jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey
) -> None:
    """Auth0's default 'Auth0' profile (typ JWT, azp, gty, no client_id/jti) must
    not pass: the demo API must be configured with the RFC 9068 profile."""
    auth0_profile = token(
        signing_key, typ="JWT", client_id=None, jti=None, azp=CLIENT_ID, gty="password"
    )
    with pytest.raises(AuthenticationError):
        provider(jwks).authenticate(auth0_profile)


# --- client identity ----------------------------------------------------------


@pytest.mark.parametrize("require_rfc9068", [True, False])
@pytest.mark.parametrize(
    "claims",
    [
        pytest.param({"client_id": None}, id="no-client-claims"),
        pytest.param({"client_id": "another-client"}, id="other-client_id"),
        pytest.param({"client_id": None, "azp": "another-client"}, id="other-azp"),
        pytest.param({"azp": "another-client"}, id="client_id-azp-disagree"),
        pytest.param({"client_id": [CLIENT_ID]}, id="client_id-list"),
        pytest.param({"client_id": None, "azp": {"id": CLIENT_ID}}, id="azp-object"),
        pytest.param({"client_id": ""}, id="empty-client_id"),
    ],
)
def test_client_identity_must_be_present_unambiguous_and_allowed(
    jwks: dict[str, Any],
    signing_key: rsa.RSAPrivateKey,
    claims: dict[str, Any],
    require_rfc9068: bool,
) -> None:
    typ = "at+jwt" if require_rfc9068 else "JWT"
    claims = {**claims, "jti": None} if not require_rfc9068 else claims
    with pytest.raises(AuthenticationError):
        provider(jwks, require_rfc9068=require_rfc9068).authenticate(
            token(signing_key, typ=typ, **claims)
        )


def test_generic_profile_still_requires_an_allowed_client(
    jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey
) -> None:
    generic = provider(jwks, require_rfc9068=False)
    ok = token(signing_key, typ="JWT", client_id=None, jti=None, azp=CLIENT_ID)
    assert generic.authenticate(ok).subject
    same = token(signing_key, typ="JWT", jti=None, azp=CLIENT_ID)
    assert generic.authenticate(same).subject


@pytest.mark.parametrize("client_ids", [[], [""], [None]])
def test_provider_requires_a_non_empty_client_allow_list(
    jwks: dict[str, Any], client_ids: list[Any]
) -> None:
    with pytest.raises(ValueError):
        provider(jwks, client_ids=client_ids)


BASE = {
    "heroos_auth_provider": "oidc",
    "heroos_oidc_issuer": ISSUER,
    "heroos_oidc_audience": AUDIENCE,
    "database_url": "postgresql+psycopg://heroos_app@db.test.invalid/heroos",
}


@pytest.mark.parametrize("environment", ["development", "staging"])
@pytest.mark.parametrize("client_ids", [None, "", " , ,"])
def test_settings_require_client_ids_for_oidc(environment: str, client_ids: str | None) -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, heroos_env=environment, heroos_oidc_client_ids=client_ids, **BASE)  # type: ignore[call-arg]
    assert "HEROOS_OIDC_CLIENT_IDS is required" in str(exc_info.value)


def test_application_refuses_to_start_without_client_ids() -> None:
    env = {
        "PATH": "/usr/bin:/bin",
        "HEROOS_ENV": "staging",
        "DATABASE_URL": BASE["database_url"],
        "HEROOS_AUTH_PROVIDER": "oidc",
        "HEROOS_OIDC_ISSUER": ISSUER,
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
    assert result.returncode != 0
    assert "HEROOS_OIDC_CLIENT_IDS is required" in result.stderr


# --- discovery and key trust --------------------------------------------------


@pytest.mark.parametrize(
    "jwks_uri",
    [
        "https://attacker.example/.well-known/jwks.json",
        "https://heroos-demo.eu.auth0.com.attacker.example/jwks.json",
        "https://heroos-demo.eu.auth0.com:8443/.well-known/jwks.json",
    ],
)
def test_discovered_jwks_on_another_origin_is_refused(
    jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey, jwks_uri: str
) -> None:
    instance = provider(jwks, discovery={**AUTH0_DISCOVERY, "jwks_uri": jwks_uri})
    with pytest.raises(AuthenticationError):
        instance.authenticate(token(signing_key))
    assert instance.used_jwks_uris == []  # type: ignore[attr-defined]


def test_discovered_jwks_on_the_issuer_origin_is_used(
    jwks: dict[str, Any], signing_key: rsa.RSAPrivateKey
) -> None:
    instance = provider(jwks)
    instance.authenticate(token(signing_key))
    assert instance.used_jwks_uris == [f"{ISSUER}.well-known/jwks.json"]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "url",
    [
        "http://heroos-demo.eu.auth0.com/.well-known/openid-configuration",
        "file:///etc/passwd",
        "ftp://x/",
    ],
)
def test_discovery_fetch_refuses_non_https(url: str) -> None:
    with pytest.raises(ValueError):
        fetch_json(url)


class _Recorder(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        _Recorder.hits.append(self.path)
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/target")
            self.end_headers()
        elif self.path == "/large":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"[" + b"1," * 200_000 + b"1]")
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def local_server() -> Iterator[str]:
    _Recorder.hits = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_discovery_transport_refuses_redirects(local_server: str) -> None:
    with pytest.raises(urllib.error.HTTPError):
        _open(f"{local_server}/redirect", None)
    assert _Recorder.hits == ["/redirect"]  # the redirect target is never requested


def test_discovery_transport_refuses_oversized_documents(local_server: str) -> None:
    with pytest.raises(ValueError, match="too large"):
        _open(f"{local_server}/large", None)


def test_tls_verification_is_explicit() -> None:
    context = tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    client = build_oidc_jwks_client("https://heroos-demo.eu.auth0.com/.well-known/jwks.json")
    assert client.ssl_context is not None
    assert client.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert client.ssl_context.check_hostname is True
