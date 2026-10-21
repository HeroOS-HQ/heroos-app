"""The evaluation continuation: encrypted, authenticated, bound, bounded, multi-instance.

A token only ever carries canonical, non-sensitive state; any problem with it
loses that state (and lost state is re-confirmed), never grants anything.
"""

import base64
import json
from uuid import uuid4

import pytest

from app.evaluation.continuation import (
    MAX_PAYLOAD_BYTES,
    MAX_TOKEN_CHARS,
    ContinuationCodec,
    ContinuationState,
    message_digest,
    parse_key,
)
from app.evaluation.facts import Asked
from app.evaluation.model import TwoState
from app.workflows.conditions import Tri
from tests.fixtures.evaluation import KEY

COMPANY, USER = uuid4(), uuid4()
VERSIONS = "knowledge-a|profile-x"
MESSAGE = "I want to suspend him for 20 days."
STATE = ContinuationState(
    workflow="disciplinary",
    asked=(Asked("insistence", "fictional_cap", "opt-suspension"),),
    engine={"proposed_suspension_days": 20, "given_opportunity_to_explain": "yes"},
    jurisdiction="confirmed",
    two_state={"fictional_cap": TwoState("fictional_cap", True, True, Tri.TRUE)},
    reconfirm=False,
    actions=("opt-suspension",),
)


def issue(codec: ContinuationCodec, state: ContinuationState = STATE) -> str:
    return codec.issue(state, company=COMPANY, user=USER, versions=VERSIONS, message=MESSAGE)


def read(codec: ContinuationCodec, token: str | None, **changes: object):  # type: ignore[no-untyped-def]
    arguments: dict[str, object] = {
        "company": COMPANY,
        "user": USER,
        "versions": VERSIONS,
        "previous_message": MESSAGE,
    }
    arguments.update(changes)
    return codec.read(token, **arguments)  # type: ignore[arg-type]


def test_another_instance_with_the_shared_key_reads_it() -> None:
    """Multi-instance safe: no process-local state, only the configured shared secret."""
    token = issue(ContinuationCodec(KEY))
    result = read(ContinuationCodec(KEY), token)
    assert result.rejection is None and result.trusted
    assert result.state == STATE


def test_it_is_confidential() -> None:
    token = issue(ContinuationCodec(KEY))
    assert len(token) <= MAX_TOKEN_CHARS and token.startswith("e1.")
    body = base64.urlsafe_b64decode(token.split(".")[2] + "==")
    for secret in (
        b"fictional_cap",
        b"proposed_suspension_days",
        b"disciplinary",
        b"opt-suspension",
        b"confirmed",
        str(COMPANY).encode(),
    ):
        assert secret not in body and secret.decode() not in token


@pytest.mark.parametrize(
    ("changes", "rejection"),
    [
        ({"company": uuid4()}, "wrong_company"),
        ({"user": uuid4()}, "wrong_user"),
        # Issued under another knowledge digest or execution profile.
        ({"versions": "knowledge-b|profile-y"}, "version_mismatch"),
        ({"versions": "knowledge-a|profile-y"}, "version_mismatch"),
        # Not the conversation it answered: an older token replayed.
        ({"previous_message": "Something else."}, "replayed"),
        ({"previous_message": None}, "replayed"),
    ],
)
def test_a_token_for_anything_else_is_rejected(changes: dict[str, object], rejection: str) -> None:
    codec = ContinuationCodec(KEY)
    result = read(codec, issue(codec), **changes)
    assert result.state is None and result.rejection == rejection


def test_tampering_is_rejected() -> None:
    codec = ContinuationCodec(KEY)
    token = issue(codec)
    prefix, key_id, body = token.split(".")
    flipped = body[:-6] + ("A" if body[-6] != "A" else "B") + body[-5:]
    assert read(codec, f"{prefix}.{key_id}.{flipped}").rejection == "tampered"
    assert read(codec, f"e2.{key_id}.{body}").rejection == "unknown_version"
    assert read(ContinuationCodec(b"z" * 32), token).rejection == "key_mismatch"
    for junk in (None, "", "x", "a.b", "e1.abcdefgh.!!!!", "e1.a.b.c", "e1." + "A" * 3000):
        assert read(codec, junk).state is None


def test_expiry() -> None:
    now = [1_000_000.0]
    codec = ContinuationCodec(KEY, now=lambda: now[0])
    token = issue(codec)
    now[0] += 4 * 3600 - 1
    assert read(codec, token).state is not None
    now[0] += 2
    assert read(codec, token).rejection == "expired"


def test_a_decoded_state_is_validated_not_trusted() -> None:
    """A payload the server never wrote (even correctly encrypted) is refused."""
    codec = ContinuationCodec(KEY)
    token = issue(codec)
    raw = base64.urlsafe_b64decode(token.split(".")[2] + "==")
    plain = json.loads(codec._aead.decrypt(raw[:12], raw[12:], codec._aad))  # noqa: SLF001
    for field, value in (
        ("f", {"narrative": "He shouted at Ahmed in front of customers"}),
        ("f", {"x": True}),
        ("f", {"x": 10**9}),
        ("t", {"r": [True, True, "maybe"]}),
        ("j", "uae_federal"),
        ("a", [["z", "x"]]),
        ("p", ["opt one with spaces"]),
        ("r", "yes"),
    ):
        forged = dict(plain, **{field: value})
        nonce = b"\0" * 12
        body = nonce + codec._aead.encrypt(nonce, json.dumps(forged).encode(), codec._aad)  # noqa: SLF001
        token = (
            "e1." + token.split(".")[1] + "." + base64.urlsafe_b64encode(body).rstrip(b"=").decode()
        )
        assert read(codec, token).rejection == "invalid_state", field


def test_it_holds_only_canonical_state() -> None:
    """No message, name, narrative or sensitive value can be issued: only codes and numbers."""
    codec = ContinuationCodec(KEY)
    raw = base64.urlsafe_b64decode(issue(codec).split(".")[2] + "==")
    plain = json.loads(codec._aead.decrypt(raw[:12], raw[12:], codec._aad))  # noqa: SLF001
    assert set(plain) == {"s", "x", "co", "us", "v", "m", "a", "w", "j", "r", "t", "f", "p"}
    assert plain["m"] == message_digest(MESSAGE) and MESSAGE not in json.dumps(plain)
    assert len(plain["co"]) == 16 and str(COMPANY) not in json.dumps(plain)


def test_the_size_is_bounded_by_dropping_facts_only() -> None:
    codec = ContinuationCodec(KEY)
    big = ContinuationState(
        workflow="disciplinary",
        engine={f"fact_{i:03d}_" + "x" * 80: i for i in range(24)},
        two_state={f"rule_{i}": TwoState(f"rule_{i}", True, False, Tri.TRUE) for i in range(8)},
    )
    token = issue(codec, big)
    assert len(token) <= MAX_TOKEN_CHARS
    state = read(codec, token).state
    assert state is not None
    # Two-state answers survive (losing them could loosen); facts go first (stricter).
    assert len(state.two_state) == 8 and len(state.engine) < 24
    raw = base64.urlsafe_b64decode(token.split(".")[2] + "==")
    assert len(raw) - 12 - 16 <= MAX_PAYLOAD_BYTES


def test_without_a_shared_key_nothing_trusted_is_carried() -> None:
    """A per-process key is never trusted across instances: what was asked, nothing more."""
    codec = ContinuationCodec(None)
    result = read(codec, issue(codec))
    assert not result.trusted and result.state is not None
    assert result.state.engine == {} and result.state.two_state == {}
    assert result.state.asked == ()  # an insistence question is trusted state too
    assert read(ContinuationCodec(None), issue(codec)).rejection == "key_mismatch"


def test_the_configured_key() -> None:
    assert parse_key("ab" * 32) == bytes.fromhex("ab" * 32)
    assert len(parse_key(base64.urlsafe_b64encode(b"s" * 48).decode())) == 48
    for bad in ("short", "ab" * 8, "%%%%"):
        with pytest.raises(ValueError):
            parse_key(bad)
