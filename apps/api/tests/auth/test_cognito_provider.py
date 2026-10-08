"""Cognito access-token verification against locally generated RSA/JWKS material."""

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.exceptions import AuthenticationError
from app.auth.providers.cognito import CognitoAccessTokenProvider
from tests.auth.conftest import (
    OMIT,
    TEST_APP_CLIENT_ID,
    TEST_COGNITO_ISSUER,
    CognitoTokenFactory,
    LocalJWKClient,
)

RESOURCE_AUDIENCE = "https://api.test.invalid"


@pytest.fixture
def resource_bound_provider(jwk_client: LocalJWKClient) -> CognitoAccessTokenProvider:
    return CognitoAccessTokenProvider(
        issuer=TEST_COGNITO_ISSUER,
        app_client_id=TEST_APP_CLIENT_ID,
        jwks_client=jwk_client,
        resource_audience=RESOURCE_AUDIENCE,
    )


def test_valid_access_token_verifies(
    cognito_provider: CognitoAccessTokenProvider, make_cognito_token: CognitoTokenFactory
) -> None:
    identity = cognito_provider.authenticate(make_cognito_token("alice-subject"))

    assert identity.subject == "alice-subject"
    assert identity.issuer == TEST_COGNITO_ISSUER


def test_signing_keys_resolved_from_jwks_and_cached(
    cognito_provider: CognitoAccessTokenProvider,
    make_cognito_token: CognitoTokenFactory,
    jwk_client: LocalJWKClient,
) -> None:
    cognito_provider.authenticate(make_cognito_token())
    cognito_provider.authenticate(make_cognito_token())

    assert jwk_client.fetch_count == 1


def test_signature_from_untrusted_key_rejected(
    cognito_provider: CognitoAccessTokenProvider,
    make_cognito_token: CognitoTokenFactory,
    untrusted_key: rsa.RSAPrivateKey,
) -> None:
    # Correct kid, wrong private key.
    with pytest.raises(AuthenticationError, match="InvalidSignatureError"):
        cognito_provider.authenticate(make_cognito_token(key=untrusted_key))


def test_tampered_payload_rejected(
    cognito_provider: CognitoAccessTokenProvider, make_cognito_token: CognitoTokenFactory
) -> None:
    header, _, signature = make_cognito_token("alice-subject").split(".")
    _, forged_payload, _ = make_cognito_token("bob-subject").split(".")

    with pytest.raises(AuthenticationError):
        cognito_provider.authenticate(f"{header}.{forged_payload}.{signature}")


@pytest.mark.parametrize("kid", ["unknown-kid", None])
def test_unknown_or_missing_kid_rejected(
    cognito_provider: CognitoAccessTokenProvider,
    make_cognito_token: CognitoTokenFactory,
    kid: str | None,
) -> None:
    with pytest.raises(AuthenticationError):
        cognito_provider.authenticate(make_cognito_token(kid=kid))


def test_expired_token_rejected(
    cognito_provider: CognitoAccessTokenProvider, make_cognito_token: CognitoTokenFactory
) -> None:
    now = int(time.time())
    token = make_cognito_token(iat=now - 7200, auth_time=now - 7200, exp=now - 3600)

    with pytest.raises(AuthenticationError, match="ExpiredSignatureError"):
        cognito_provider.authenticate(token)


def test_wrong_issuer_rejected(
    cognito_provider: CognitoAccessTokenProvider, make_cognito_token: CognitoTokenFactory
) -> None:
    token = make_cognito_token(iss="https://cognito-idp.test.invalid/another-user-pool")

    with pytest.raises(AuthenticationError, match="InvalidIssuerError"):
        cognito_provider.authenticate(token)


def test_wrong_app_client_rejected(
    cognito_provider: CognitoAccessTokenProvider, make_cognito_token: CognitoTokenFactory
) -> None:
    with pytest.raises(AuthenticationError, match="client_id"):
        cognito_provider.authenticate(make_cognito_token(client_id="another-app-client"))


def test_id_token_rejected(
    cognito_provider: CognitoAccessTokenProvider, make_cognito_token: CognitoTokenFactory
) -> None:
    # A genuine ID token for the right App Client: aud instead of client_id.
    token = make_cognito_token(token_use="id", aud=TEST_APP_CLIENT_ID, client_id=OMIT)

    with pytest.raises(AuthenticationError):
        cognito_provider.authenticate(token)


def test_id_token_rejected_by_token_use_even_with_matching_client_id(
    cognito_provider: CognitoAccessTokenProvider, make_cognito_token: CognitoTokenFactory
) -> None:
    # Every other check passes, so token_use alone must reject it.
    token = make_cognito_token(token_use="id", aud=TEST_APP_CLIENT_ID)

    with pytest.raises(AuthenticationError, match="token_use"):
        cognito_provider.authenticate(token)


@pytest.mark.parametrize("token_use", ["id", "refresh", ""])
def test_wrong_token_use_rejected(
    cognito_provider: CognitoAccessTokenProvider,
    make_cognito_token: CognitoTokenFactory,
    token_use: str,
) -> None:
    with pytest.raises(AuthenticationError, match="token_use"):
        cognito_provider.authenticate(make_cognito_token(token_use=token_use))


def test_access_token_without_aud_accepted(
    cognito_provider: CognitoAccessTokenProvider, make_cognito_token: CognitoTokenFactory
) -> None:
    token = make_cognito_token()

    assert "aud" not in jwt.decode(token, options={"verify_signature": False})
    assert cognito_provider.authenticate(token).subject == "alice-subject"


@pytest.mark.parametrize(
    "aud", [RESOURCE_AUDIENCE, "https://other.test.invalid", [RESOURCE_AUDIENCE]]
)
def test_access_token_with_aud_accepted_when_no_resource_audience_configured(
    cognito_provider: CognitoAccessTokenProvider,
    make_cognito_token: CognitoTokenFactory,
    aud: object,
) -> None:
    # Resource-bound access tokens carry aud; it must not be mistaken for an ID token.
    assert cognito_provider.authenticate(make_cognito_token(aud=aud)).subject == "alice-subject"


@pytest.mark.parametrize(
    "aud", [RESOURCE_AUDIENCE, ["https://other.test.invalid", RESOURCE_AUDIENCE]]
)
def test_configured_resource_audience_accepted(
    resource_bound_provider: CognitoAccessTokenProvider,
    make_cognito_token: CognitoTokenFactory,
    aud: object,
) -> None:
    identity = resource_bound_provider.authenticate(make_cognito_token(aud=aud))

    assert identity.subject == "alice-subject"


@pytest.mark.parametrize(
    "aud",
    [
        pytest.param("https://other.test.invalid", id="wrong"),
        pytest.param(["https://other.test.invalid"], id="wrong-list"),
        pytest.param(TEST_APP_CLIENT_ID, id="app-client-id"),
        pytest.param(OMIT, id="missing"),
    ],
)
def test_configured_resource_audience_mismatch_rejected(
    resource_bound_provider: CognitoAccessTokenProvider,
    make_cognito_token: CognitoTokenFactory,
    aud: object,
) -> None:
    with pytest.raises(AuthenticationError):
        resource_bound_provider.authenticate(make_cognito_token(aud=aud))


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"token_use": "id"}, id="id-token-use"),
        pytest.param({"client_id": "another-app-client"}, id="wrong-client"),
        pytest.param({"iss": "https://cognito-idp.test.invalid/other-pool"}, id="wrong-issuer"),
        pytest.param({"exp": int(time.time()) - 60, "iat": int(time.time()) - 660}, id="expired"),
    ],
)
def test_matching_resource_audience_does_not_relax_other_checks(
    resource_bound_provider: CognitoAccessTokenProvider,
    make_cognito_token: CognitoTokenFactory,
    overrides: dict[str, object],
) -> None:
    with pytest.raises(AuthenticationError):
        resource_bound_provider.authenticate(
            make_cognito_token(**{"aud": RESOURCE_AUDIENCE, **overrides})
        )


@pytest.mark.parametrize("missing", ["sub", "iss", "exp", "iat", "token_use", "client_id"])
def test_required_claims_enforced(
    cognito_provider: CognitoAccessTokenProvider,
    make_cognito_token: CognitoTokenFactory,
    missing: str,
) -> None:
    with pytest.raises(AuthenticationError):
        cognito_provider.authenticate(make_cognito_token(**{missing: OMIT}))


@pytest.mark.parametrize("subject", ["", "   ", "x" * 256])
def test_invalid_subject_rejected(
    cognito_provider: CognitoAccessTokenProvider,
    make_cognito_token: CognitoTokenFactory,
    subject: str,
) -> None:
    with pytest.raises(AuthenticationError, match="subject"):
        cognito_provider.authenticate(make_cognito_token(subject))


def test_algorithm_confusion_with_public_key_rejected(
    cognito_provider: CognitoAccessTokenProvider,
    make_cognito_token: CognitoTokenFactory,
    signing_key: rsa.RSAPrivateKey,
) -> None:
    public_pem = signing_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    claims = jwt.decode(make_cognito_token(), options={"verify_signature": False})
    # PyJWT refuses to HMAC-sign with PEM material, so forge the HS256 token by hand.
    forged = _hs256_token(claims, public_pem)

    with pytest.raises(AuthenticationError):
        cognito_provider.authenticate(forged)


def test_unsigned_token_rejected(
    cognito_provider: CognitoAccessTokenProvider, make_cognito_token: CognitoTokenFactory
) -> None:
    claims = jwt.decode(make_cognito_token(), options={"verify_signature": False})
    token = jwt.encode(claims, None, algorithm="none", headers={"kid": "test-signing-key"})

    with pytest.raises(AuthenticationError):
        cognito_provider.authenticate(token)


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.b.c", "a.b"])
def test_malformed_token_rejected(cognito_provider: CognitoAccessTokenProvider, token: str) -> None:
    with pytest.raises(AuthenticationError):
        cognito_provider.authenticate(token)


def test_jwks_unavailable_fails_closed(make_cognito_token: CognitoTokenFactory) -> None:
    class UnreachableJWKClient(LocalJWKClient):
        def fetch_data(self) -> Any:
            raise jwt.PyJWKClientConnectionError("JWKS endpoint unreachable")

    provider = CognitoAccessTokenProvider(
        issuer=TEST_COGNITO_ISSUER,
        app_client_id=TEST_APP_CLIENT_ID,
        jwks_client=UnreachableJWKClient({"keys": []}),
    )

    with pytest.raises(AuthenticationError):
        provider.authenticate(make_cognito_token())


def _hs256_token(claims: dict[str, Any], key: bytes) -> str:
    import base64
    import hashlib
    import hmac
    import json

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "test-signing-key"}).encode())
    payload = b64(json.dumps(claims).encode())
    signature = hmac.new(key, f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{b64(signature)}"
