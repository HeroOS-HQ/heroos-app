"""What the Hannah demo needs from a chat model, independent of the provider.

A provider takes a fixed system instruction and the recent turns and returns
one reply. It raises ``AssistantError`` with a fixed kind on any failure; the
provider's own error text never leaves its adapter. Replacing GroqCloud (for
example with Anthropic) means writing another class with this shape.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

FailureKind = Literal["rate_limited", "timeout", "unavailable"]


@dataclass(frozen=True, slots=True)
class ChatTurn:
    role: Literal["user", "assistant"]
    content: str


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
