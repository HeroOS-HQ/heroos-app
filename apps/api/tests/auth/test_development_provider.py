from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from pydantic import SecretStr

from app.auth.exceptions import AuthenticationConfigurationError, AuthenticationError
from app.auth.providers.development import (
    DEVELOPMENT_ALGORITHM,
    DEVELOPMENT_ISSUER,
    DevelopmentAuthenticationProvider,
    issue_development_token,
)
from tests.auth.conftest import TEST_DEV_SECRET


def issue(subject: str = "alice-subject", **kwargs: object) -> str:
    return issue_development_token(
        environment="development",
        secret=TEST_DEV_SECRET,
        subject=subject,
        **kwargs,  # type: ignore[arg-type]
    )


def sign(claims: dict[str, object], secret: str = TEST_DEV_SECRET.get_secret_value()) -> str:
    return jwt.encode(claims, secret, algorithm=DEVELOPMENT_ALGORITHM)


def test_issued_token_verifies(development_provider: DevelopmentAuthenticationProvider) -> None:
    identity = development_provider.authenticate(issue("alice-subject"))

    assert identity.subject == "alice-subject"
    assert identity.issuer == DEVELOPMENT_ISSUER


def test_issued_token_is_short_lived() -> None:
    claims = jwt.decode(
        issue(),
        TEST_DEV_SECRET.get_secret_value(),
        algorithms=[DEVELOPMENT_ALGORITHM],
        issuer=DEVELOPMENT_ISSUER,
    )

    assert claims["exp"] - claims["iat"] == 15 * 60
    assert set(claims) == {"iss", "sub", "iat", "exp"}


def test_wrong_secret_rejected(development_provider: DevelopmentAuthenticationProvider) -> None:
    token = issue_development_token(
        environment="development",
        secret=SecretStr("a-different-development-secret-0123456789"),
        subject="alice-subject",
    )

    with pytest.raises(AuthenticationError):
        development_provider.authenticate(token)


def test_expired_token_rejected(development_provider: DevelopmentAuthenticationProvider) -> None:
    token = issue(now=datetime.now(UTC) - timedelta(hours=2))

    with pytest.raises(AuthenticationError, match="ExpiredSignatureError"):
        development_provider.authenticate(token)


def test_wrong_issuer_rejected(development_provider: DevelopmentAuthenticationProvider) -> None:
    now = datetime.now(UTC)
    token = sign(
        {
            "iss": "someone-else",
            "sub": "alice-subject",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        }
    )

    with pytest.raises(AuthenticationError, match="InvalidIssuerError"):
        development_provider.authenticate(token)


def test_overlong_lifetime_rejected(
    development_provider: DevelopmentAuthenticationProvider,
) -> None:
    now = datetime.now(UTC)
    token = sign(
        {
            "iss": DEVELOPMENT_ISSUER,
            "sub": "alice-subject",
            "iat": now,
            "exp": now + timedelta(days=30),
        }
    )

    with pytest.raises(AuthenticationError, match="lifetime"):
        development_provider.authenticate(token)


@pytest.mark.parametrize("missing", ["sub", "iat", "exp", "iss"])
def test_required_claims_enforced(
    development_provider: DevelopmentAuthenticationProvider, missing: str
) -> None:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": DEVELOPMENT_ISSUER,
        "sub": "alice-subject",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    del claims[missing]

    with pytest.raises(AuthenticationError):
        development_provider.authenticate(sign(claims))


def test_unsigned_token_rejected(development_provider: DevelopmentAuthenticationProvider) -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": DEVELOPMENT_ISSUER,
            "sub": "alice-subject",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        None,
        algorithm="none",
    )

    with pytest.raises(AuthenticationError):
        development_provider.authenticate(token)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_provider_cannot_be_constructed_outside_development(environment: str) -> None:
    with pytest.raises(AuthenticationConfigurationError):
        DevelopmentAuthenticationProvider(environment=environment, secret=TEST_DEV_SECRET)  # type: ignore[arg-type]


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_tokens_cannot_be_issued_outside_development(environment: str) -> None:
    with pytest.raises(AuthenticationConfigurationError):
        issue_development_token(
            environment=environment,  # type: ignore[arg-type]
            secret=TEST_DEV_SECRET,
            subject="alice-subject",
        )


@pytest.mark.parametrize("lifetime", [timedelta(0), timedelta(hours=2)])
def test_issue_rejects_unsafe_lifetime(lifetime: timedelta) -> None:
    with pytest.raises(ValueError, match="lifetime"):
        issue(lifetime=lifetime)


def test_dev_token_script_refuses_without_development_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.create_dev_token import main

    monkeypatch.chdir(tmp_path)  # no local .env

    assert main(["alice-subject"]) == 1
    assert "Refusing" in capsys.readouterr().err


def test_dev_token_script_issues_verifiable_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    development_provider: DevelopmentAuthenticationProvider,
) -> None:
    from scripts.create_dev_token import main

    monkeypatch.chdir(tmp_path)  # no local .env
    monkeypatch.setenv("HEROOS_ENV", "development")
    monkeypatch.setenv("HEROOS_AUTH_PROVIDER", "development")
    monkeypatch.setenv("HEROOS_DEV_AUTH_SECRET", TEST_DEV_SECRET.get_secret_value())

    assert main(["alice-subject", "--minutes", "5"]) == 0
    token = capsys.readouterr().out.strip()
    assert development_provider.authenticate(token).subject == "alice-subject"
