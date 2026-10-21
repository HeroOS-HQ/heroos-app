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


@dataclass(frozen=True, slots=True)
class Completion:
    """One structured completion: the raw text (unvalidated) and reported usage."""

    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class AssistantError(Exception):
    """The provider gave no usable reply. ``kind`` is all a caller may show."""

    def __init__(self, kind: FailureKind, *, retry_after: int | None = None) -> None:
        super().__init__(kind)
        self.kind: FailureKind = kind
        self.retry_after = retry_after


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
