"""What HeroOS needs from a chat model, independent of the provider.

A provider takes a fixed system instruction and the recent turns and returns
one reply. It raises ``AssistantError`` with a fixed kind on any failure; the
provider's own error text never leaves its adapter. Replacing GroqCloud (for
example with Anthropic) means writing another class with this shape.

``ChatProvider`` is the Hannah demo's free-text reply. ``StructuredChatProvider``
adds what the Ask HeroOS gateway (M2-NEW-05) needs on top: one JSON object per
request, with the caller's temperature, completion budget and timeout, and
the token usage the provider reports (for operational telemetry only). The
gateway validates every object itself; the provider is never trusted to.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

FailureKind = Literal["rate_limited", "timeout", "unavailable"]


@dataclass(frozen=True, slots=True)
class ChatTurn:
    role: Literal["user", "assistant"]
    content: str
    # The start of the turn that is the same across requests (server-built reference data, never
    # founder text or per-request state), sent before ``content``: a provider may cache it.
    stable: str = ""

    @property
    def text(self) -> str:
        """The whole turn as one text (a provider that doesn't cache sends this)."""
        return f"{self.stable}\n{self.content}" if self.stable else self.content


@dataclass(frozen=True, slots=True)
class Completion:
    """One structured completion: the raw text (unvalidated) and reported usage."""

    text: str
    # All input tokens, cached or not.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    # Of the input: read from the provider's prompt cache, and written to it (None: not reported).
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None


class AssistantError(Exception):
    """The provider gave no usable reply. ``kind`` is all a caller may show."""

    def __init__(
        self, kind: FailureKind, *, retry_after: int | None = None, status: int | None = None
    ) -> None:
        super().__init__(kind)
        self.kind: FailureKind = kind
        self.retry_after = retry_after
        # The provider's HTTP status when it refused the request (adapters only; never shown).
        self.status = status


class ChatProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    def reply(self, system: str, turns: Sequence[ChatTurn]) -> str:
        """One inference request; no retries (each one spends the provider quota)."""
        ...


class StructuredChatProvider(ChatProvider, Protocol):
    def complete_json(
        self,
        system: str,
        turns: Sequence[ChatTurn],
        *,
        temperature: float,
        max_completion_tokens: int,
        timeout: float,
    ) -> Completion:
        """One request for one JSON object; no retries, no tools, no retrieval."""
        ...
