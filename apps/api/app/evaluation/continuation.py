"""The evaluation continuation (``heroos.evaluation-continuation/1``): trusted state across turns.

Nothing is stored server-side before M2-NEW-07, and a browser's plain facts
are never trusted. So each reply carries one opaque token the next message
sends back unchanged: AES-256-GCM (confidential and authenticated) under a
key derived from a **configured shared server secret**
(``HEROOS_EVALUATION_CONTINUATION_KEY``), so any API instance can read what
another issued. It holds only minimal, bounded, canonical, non-sensitive
state:

- what HeroOS asked last (fact keys, a confirmation's canonical candidate, a
  two-state insistence question, the jurisdiction question);
- ENGINE_TRUSTED facts (option values and whole numbers only);
- the founder's trusted answer about this employee's jurisdiction;
- each two-state caution's state (shown, acknowledged, insistence);
- whether trusted state was lost earlier in this conversation;
- the employer decisions the previous turn evaluated (option ids), so a direct
  answer ("Yes.") keeps the step it answers under evaluation;
- its expiry, keyed digests of the Company and the user, the identity of the
  knowledge and execution profile it was issued under, and a digest of the
  founder message it answered.

Never: a founder message, a name, a narrative, evidence, a sensitive answer,
provider output, knowledge text or guidance. The reader validates every value
against the current execution's schemas (``app.evaluation.facts``) and drops
anything it can't vouch for.

A token that is missing, malformed, of an unknown version, tampered with,
expired, for another Company or user, issued under other knowledge or another
profile, or replayed against a conversation it didn't answer is **rejected**
with a category for the log. Rejection only ever loses trusted state, and lost
state is re-confirmed (``PriorState.reconfirm``): it never makes an evaluation
less restrictive than the facts that remain.

Without a configured key the codec still works in one process (a random
per-process key) but carries only what HeroOS last asked, never trusted
state: a per-process key is never trusted across instances.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final, Literal
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.evaluation.facts import Asked, AskedKind
from app.evaluation.model import TwoState, Value
from app.workflows.conditions import Tri

SCHEMA: Final = "heroos.evaluation-continuation/1"
VERSION_PREFIX: Final = "e1"
TOKEN_SECONDS: Final = 4 * 3600
MAX_TOKEN_CHARS: Final = 2400
MAX_PAYLOAD_BYTES: Final = 1500
MAX_FACTS: Final = 24
MAX_ASKED: Final = 2
MAX_TWO_STATE: Final = 8
MAX_ACTIONS: Final = 3
MIN_KEY_BYTES: Final = 32
_NONCE_BYTES: Final = 12
_DIGEST_CHARS: Final = 16
_KEY_ID_CHARS: Final = 8
_ASKED_KINDS: Final[Mapping[str, AskedKind]] = {
    "f": "fact", "c": "confirm", "i": "insistence", "j": "jurisdiction",
}  # fmt: skip
_JURISDICTION_ANSWERS: Final = ("confirmed", "different", "not_sure")

Rejection = Literal[
    "missing", "malformed", "unknown_version", "key_mismatch", "tampered", "expired",
    "wrong_company", "wrong_user", "version_mismatch", "replayed", "invalid_state",
]  # fmt: skip


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def parse_key(raw: str) -> bytes:
    """The configured secret: base64url (or hex) of at least 32 random bytes."""
    text = raw.strip()
    try:
        key = bytes.fromhex(text) if len(text) == 64 and all(
            c in "0123456789abcdef" for c in text.lower()
        ) else _decode(text)  # fmt: skip
    except ValueError as error:
        raise ValueError("the continuation key must be base64url or hex") from error
    if len(key) < MIN_KEY_BYTES:
        raise ValueError("the continuation key must hold at least 32 bytes")
    return key


def message_digest(message: str) -> str:
    """Which founder message a token answered (a digest; the message is never in the token)."""
    return hashlib.sha256(message.strip().encode()).hexdigest()[:_DIGEST_CHARS]


@dataclass(frozen=True, slots=True)
class ContinuationState:
    workflow: str | None = None
    asked: tuple[Asked, ...] = ()
    engine: Mapping[str, Value] = field(default_factory=dict)
    jurisdiction: str | None = None
    two_state: Mapping[str, TwoState] = field(default_factory=dict)
    reconfirm: bool = False
    actions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReadResult:
    state: ContinuationState | None
    # Why there is no state (None when ``state`` is present, or nothing was sent).
    rejection: Rejection | None
    # The token carries trusted state (a configured shared key).
    trusted: bool


class ContinuationCodec:
    def __init__(self, key: bytes | None, *, now: Callable[[], float] = time.time) -> None:
        self.trusted = key is not None
        secret = key if key is not None else secrets.token_bytes(MIN_KEY_BYTES)
        derived = HKDF(
            algorithm=hashes.SHA256(), length=64, salt=None, info=SCHEMA.encode()
        ).derive(secret)
        self._aead = AESGCM(derived[:32])
        self._binding_key = derived[32:]
        self._key_id = _encode(hashlib.sha256(b"key-id|" + derived).digest())[:_KEY_ID_CHARS]
        self._now = now

    def _bound(self, label: str, value: bytes) -> str:
        digest = hmac.new(self._binding_key, label.encode() + b"|" + value, hashlib.sha256)
        return digest.hexdigest()[:_DIGEST_CHARS]

    @property
    def _aad(self) -> bytes:
        return f"{SCHEMA}|{self._key_id}".encode()

    def issue(
        self,
        state: ContinuationState,
        *,
        company: UUID,
        user: UUID,
        versions: str,
        message: str,
    ) -> str:
        """A token for the next turn, bounded: what would overflow is dropped (stricter only)."""
        payload: dict[str, object] = {
            "s": 1,
            "x": int(self._now()) + TOKEN_SECONDS,
            "co": self._bound("company", company.bytes),
            "us": self._bound("user", user.bytes),
            "v": self._bound("versions", versions.encode()),
            "m": message_digest(message),
            "a": [
                [kind, a.key, *([a.candidate] if a.candidate is not None else [])]
                for a in state.asked[:MAX_ASKED]
                for kind in [next(k for k, v in _ASKED_KINDS.items() if v == a.kind)]
                if self.trusted or a.kind == "fact"
            ],
        }
        if self.trusted:
            payload["w"] = state.workflow
            payload["j"] = state.jurisdiction
            payload["r"] = state.reconfirm
            payload["p"] = list(state.actions[:MAX_ACTIONS])
            payload["t"] = {
                t.rule: [t.shown, t.acknowledged, t.insists.value]
                for t in list(state.two_state.values())[:MAX_TWO_STATE]
            }
            facts = dict(list(state.engine.items())[:MAX_FACTS])
            payload["f"] = facts
            # Facts go first when the token would be too large (losing them is only stricter).
            while facts and len(self._json(payload)) > MAX_PAYLOAD_BYTES:
                facts.pop(next(reversed(facts)))
                payload["f"] = facts
        nonce = secrets.token_bytes(_NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, self._json(payload), self._aad)
        return f"{VERSION_PREFIX}.{self._key_id}.{_encode(nonce + sealed)}"

    @staticmethod
    def _json(payload: Mapping[str, object]) -> bytes:
        return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()

    def read(
        self,
        token: str | None,
        *,
        company: UUID,
        user: UUID,
        versions: str,
        previous_message: str | None,
    ) -> ReadResult:
        """The previous turn's state, or why there is none. Never raises on input."""
        if not token:
            return ReadResult(None, "missing", self.trusted)
        if len(token) > MAX_TOKEN_CHARS or token.count(".") != 2:
            return ReadResult(None, "malformed", self.trusted)
        version, key_id, body = token.split(".")
        if version != VERSION_PREFIX:
            return ReadResult(None, "unknown_version", self.trusted)
        if not hmac.compare_digest(key_id, self._key_id):
            return ReadResult(None, "key_mismatch", self.trusted)
        try:
            raw = _decode(body)
            plain = self._aead.decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], self._aad)
        except (ValueError, InvalidTag):
            return ReadResult(None, "tampered", self.trusted)
        try:
            data = json.loads(plain)
        except ValueError:
            return ReadResult(None, "malformed", self.trusted)
        if not isinstance(data, dict) or data.get("s") != 1:
            return ReadResult(None, "unknown_version", self.trusted)
        expires = data.get("x")
        if not isinstance(expires, int) or expires < self._now():
            return ReadResult(None, "expired", self.trusted)
        if data.get("co") != self._bound("company", company.bytes):
            return ReadResult(None, "wrong_company", self.trusted)
        if data.get("us") != self._bound("user", user.bytes):
            return ReadResult(None, "wrong_user", self.trusted)
        if data.get("v") != self._bound("versions", versions.encode()):
            return ReadResult(None, "version_mismatch", self.trusted)
        if previous_message is None or data.get("m") != message_digest(previous_message):
            # Not the conversation this token answered (an older token, or other history).
            return ReadResult(None, "replayed", self.trusted)
        state = self._state(data)
        if state is None:
            return ReadResult(None, "invalid_state", self.trusted)
        return ReadResult(state, None, self.trusted)

    def _state(self, data: Mapping[str, object]) -> ContinuationState | None:
        asked: list[Asked] = []
        raw_asked = data.get("a")
        if not isinstance(raw_asked, list) or len(raw_asked) > MAX_ASKED:
            return None
        for item in raw_asked:
            if not isinstance(item, list) or not 2 <= len(item) <= 3:
                return None
            kind, key = _ASKED_KINDS.get(str(item[0])), item[1]
            if kind is None or not isinstance(key, str) or not 0 < len(key) <= 120:
                return None
            value = item[2] if len(item) == 3 else None
            if value is not None and not _value(value):
                return None
            asked.append(Asked(kind, key, value))
        if not self.trusted:
            return ContinuationState(asked=tuple(a for a in asked if a.kind == "fact"))
        workflow, jurisdiction = data.get("w"), data.get("j")
        facts, two_state, actions = data.get("f"), data.get("t"), data.get("p")
        if (
            not isinstance(actions, list)
            or len(actions) > MAX_ACTIONS
            or not all(isinstance(a, str) and _value(a) for a in actions)
        ):
            return None
        if (
            (workflow is not None and not isinstance(workflow, str))
            or (jurisdiction is not None and jurisdiction not in _JURISDICTION_ANSWERS)
            or not isinstance(facts, dict)
            or len(facts) > MAX_FACTS
            or not isinstance(two_state, dict)
            or len(two_state) > MAX_TWO_STATE
            or not isinstance(data.get("r"), bool)
        ):
            return None
        if not all(isinstance(k, str) and _value(v) for k, v in facts.items()):
            return None
        states: dict[str, TwoState] = {}
        for rule, entry in two_state.items():
            if (
                not isinstance(entry, list)
                or len(entry) != 3
                or not all(isinstance(e, bool) for e in entry[:2])
                or entry[2] not in {t.value for t in Tri}
            ):
                return None
            states[rule] = TwoState(rule, entry[0], entry[1], Tri(entry[2]))
        return ContinuationState(
            workflow=workflow,
            asked=tuple(asked),
            engine=dict(facts),
            jurisdiction=jurisdiction,
            two_state=states,
            reconfirm=bool(data["r"]),
            actions=tuple(actions),
        )


def _value(value: object) -> bool:
    """A canonical value's shape: a short option code or a bounded whole number."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 <= value <= 1_000_000
    return isinstance(value, str) and 0 < len(value) <= 40 and value.replace("-", "_").replace(
        "_", ""
    ).isalnum()  # fmt: skip
