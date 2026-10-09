"""Client-side SCRAM-SHA-256 verifiers match the standard, and the managed
password policy refuses everything that was not generated."""

import base64
import hashlib
import hmac
import re

import pytest

from scripts.scram import (
    PasswordPolicyError,
    check_password,
    generate_password,
    redact_verifiers,
    scram_keys,
    scram_verifier,
)

# RFC 7677 section 3 example exchange (user "user", password "pencil").
RFC_SALT = "W22ZaJ0SNY7soEsUEjb6gQ=="
RFC_NONCE = "rOprNGfwEbeRWgbNEkqO%hvYDpWUa2RaTCAfuxFIlj)hNlF$k0"
RFC_AUTH_MESSAGE = (
    f"n=user,r=rOprNGfwEbeRWgbNEkqO,r={RFC_NONCE},s={RFC_SALT},i=4096,c=biws,r={RFC_NONCE}"
).encode()
RFC_CLIENT_PROOF = "dHzbZapWIk4jUhN+Ute9ytag9zjfMHgsqmmiz7AndVQ="
RFC_SERVER_SIGNATURE = "6rriTRBi23WpRR/wtup+mMhUZUn/dB5nLTJRsjl95G4="


def _sign(key: bytes) -> bytes:
    return hmac.new(key, RFC_AUTH_MESSAGE, hashlib.sha256).digest()


def test_keys_reproduce_rfc_7677_exchange() -> None:
    stored_key, server_key = scram_keys("pencil", base64.b64decode(RFC_SALT), 4096)

    # The server proves itself with ServerKey ...
    assert base64.b64encode(_sign(server_key)).decode() == RFC_SERVER_SIGNATURE
    # ... and authenticates the client proof with StoredKey.
    client_key = bytes(
        a ^ b for a, b in zip(base64.b64decode(RFC_CLIENT_PROOF), _sign(stored_key), strict=True)
    )
    assert hashlib.sha256(client_key).digest() == stored_key


def test_verifier_has_postgresql_format_and_fresh_salt() -> None:
    password = generate_password()
    first, second = scram_verifier(password), scram_verifier(password)

    pattern = r"SCRAM-SHA-256\$4096:[A-Za-z0-9+/]{22}==\$[A-Za-z0-9+/]{43}=:[A-Za-z0-9+/]{43}="
    assert re.fullmatch(pattern, first)
    assert first != second  # random 16-byte salt per verifier
    assert password not in first


def test_verifier_with_fixed_salt_is_deterministic() -> None:
    salt = base64.b64decode(RFC_SALT)
    stored_key, server_key = scram_keys("pencil", salt)

    assert scram_verifier("pencil", salt=salt) == (
        f"SCRAM-SHA-256$4096:{RFC_SALT}$"
        f"{base64.b64encode(stored_key).decode()}:{base64.b64encode(server_key).decode()}"
    )


@pytest.mark.parametrize("password", ["pässword", "tab\tinside"])
def test_non_ascii_or_unprintable_passwords_are_refused(password: str) -> None:
    # PostgreSQL's SASLprep is the identity only for printable ASCII.
    with pytest.raises(PasswordPolicyError):
        scram_verifier(password)


def test_generated_passwords_meet_policy() -> None:
    passwords = {generate_password() for _ in range(20)}

    assert len(passwords) == 20
    for password in passwords:
        assert check_password(password, "X") == password


@pytest.mark.parametrize(
    "password",
    [
        None,
        "",
        "changeme",
        "retired_default_style_password",
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "g" * 64,
        " " + "a" * 63,
    ],
)
def test_policy_refuses_non_generated_passwords_without_quoting_them(
    password: str | None,
) -> None:
    with pytest.raises(PasswordPolicyError) as exc_info:
        check_password(password, "HEROOS_DB_APP_PASSWORD")

    assert "HEROOS_DB_APP_PASSWORD" in str(exc_info.value)
    if password:
        assert password.strip() not in str(exc_info.value)


def test_redact_verifiers() -> None:
    verifier = scram_verifier(generate_password())
    message = f"LINE 1: ALTER ROLE heroos PASSWORD '{verifier}';"

    redacted = redact_verifiers(message)

    assert verifier not in redacted
    assert "SCRAM-SHA-256$<redacted>" in redacted
