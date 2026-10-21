"""What HeroOS last asked about, carried by the browser in a token only this process can sign.

The understanding phase sees the founder's own words only, never HeroOS's
earlier replies (they are never evidence). But "yes" or "twice" only means
something next to the question it answers. So each reply carries an opaque
``continuation`` token naming the facts HeroOS asked about (as positions in
the installed bundle's fact list: no fact key, label or id is readable in
it), and the next turn tells the model "the founder may be answering a
question about: <labels>" from the bundle itself, never from text a browser
sent.

The token is HMAC-signed with a key held in this API process's memory, bound
to the Company, the user and the installed bundle, and expires. A restart,
another bundle, another user or a forged or stale token simply means HeroOS
doesn't know what it last asked: nothing else depends on it, and it grants
nothing.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable, Sequence
from typing import Final
from uuid import UUID

MAX_TOKEN_CHARS: Final = 512
TOKEN_SECONDS: Final = 4 * 3600
_SIGNATURE_BYTES: Final = 16


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Continuations:
    def __init__(
        self,
        fact_keys: Sequence[str],
        bundle_digest: str,
        *,
        key: bytes | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._facts = tuple(fact_keys)
        self._digest = bundle_digest
        self._key = key if key is not None else secrets.token_bytes(32)
        self._now = now

    def _signature(self, payload: bytes, company: UUID, user: UUID) -> bytes:
        message = b"|".join([payload, company.bytes, user.bytes, self._digest.encode("ascii")])
        return hmac.new(self._key, message, hashlib.sha256).digest()[:_SIGNATURE_BYTES]

    def issue(self, company: UUID, user: UUID, asked: Sequence[str]) -> str:
        positions = sorted({self._facts.index(k) for k in asked if k in self._facts})
        payload = json.dumps(
            {"v": 1, "t": positions, "x": int(self._now()) + TOKEN_SECONDS}, separators=(",", ":")
        ).encode("ascii")
        return f"{_encode(payload)}.{_encode(self._signature(payload, company, user))}"

    def read(self, token: str | None, company: UUID, user: UUID) -> tuple[str, ...]:
        """The fact keys HeroOS last asked about; empty for anything not valid now."""
        if not token or len(token) > MAX_TOKEN_CHARS or token.count(".") != 1:
            return ()
        body, signature = token.split(".")
        try:
            payload, given = _decode(body), _decode(signature)
            if not hmac.compare_digest(given, self._signature(payload, company, user)):
                return ()
            data = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            return ()
        if not isinstance(data, dict) or data.get("v") != 1:
            return ()
        expires, positions = data.get("x"), data.get("t")
        if not isinstance(expires, int) or expires < self._now() or not isinstance(positions, list):
            return ()
        return tuple(
            self._facts[p]
            for p in positions
            if isinstance(p, int) and not isinstance(p, bool) and 0 <= p < len(self._facts)
        )
