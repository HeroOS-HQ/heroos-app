"""The Hannah AI demo (conversational, synthetic scenarios only): status and messages.

Same dependency chain as the document routes: a verified credential, an active
Membership, the ``company_admin`` role (checked again inside the transaction),
and a transaction that refuses every write. On top of that:

- the demo must be enabled (``HEROOS_HANNAH_DEMO_ENABLED``), and
- the caller's verified identity subject must be on the tester list
  (``HEROOS_HANNAH_TESTER_SUBJECTS``). An empty list admits no one, so a new
  self-registered founder (an administrator of their own Company) can't use it.

Routes:

- ``GET .../cases/{case}/assistant``: whether this caller can use the demo here
  (``available`` and a fixed ``reason``), for the composer.
- ``POST .../cases/{case}/assistant/messages``: the latest message and a
  bounded recent history in, one reply out. One provider request per message,
  never retried. The Case is only checked to exist for this Company: nothing
  about it is sent to the provider, and nothing is written. The chat is not
  case history, not ``case_facts`` and not a workflow action; the model gets no
  tools.

Nothing logs a message, history, reply, prompt, key or identity subject: logs
carry the outcome only.

Responses: 401 / 403 (also for a caller not on the tester list) / 404 (demo
disabled, or a Case that isn't one of this Company's) exactly as the Company
routes; 422 field locations only; 429 ``Too many requests`` (the tester's
limit or the provider's, with ``Retry-After``); 503 ``Not configured`` (no
provider key); 504 ``Timed out``; 502 ``Unavailable`` (any other provider
failure).
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StrictStr, StringConstraints, field_validator

from app.assistant.limits import SlidingWindowLimiter
from app.assistant.persona import HANNAH_SYSTEM_INSTRUCTION
from app.assistant.provider import AssistantError, ChatProvider, ChatTurn
from app.auth.dependencies import get_verified_identity
from app.auth.models import VerifiedIdentity
from app.repositories import workflows
from app.tenancy.dependencies import CompanyAdminReadOnlyDb

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies/{company_id}", tags=["assistant"])

MAX_MESSAGE_CHARS: Final = 2000
MAX_TURN_CHARS: Final = 4000
MAX_HISTORY_TURNS: Final = 12
# The most recent turns that fit this budget are sent (oldest dropped first),
# keeping each request well inside the provider's per-minute token limit.
MAX_HISTORY_CHARS: Final = 8000

NOTICE: Final = (
    "Hannah AI Demo — Use fictional employee scenarios only. Responses are exploratory and "
    "do not authorize disciplinary decisions."
)

Reason = Literal["disabled", "not_a_tester", "not_configured"]


@dataclass(frozen=True, slots=True)
class HannahDemo:
    """The demo's configuration, fixed at startup."""

    enabled: bool
    testers: frozenset[str]
    provider: ChatProvider | None
    limiter: SlidingWindowLimiter


def hannah_demo(request: Request) -> HannahDemo:
    demo: HannahDemo = request.app.state.hannah_demo
    return demo


Demo = Annotated[HannahDemo, Depends(hannah_demo)]
Identity = Annotated[VerifiedIdentity, Depends(get_verified_identity)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def require_hannah_tester(identity: Identity, demo: Demo) -> VerifiedIdentity:
    """The demo is on and this verified identity subject is on the tester list."""
    if not demo.enabled:
        raise _not_found()
    if identity.subject not in demo.testers:
        logger.info("Hannah demo refused: identity is not on the tester list")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return identity


Tester = Annotated[VerifiedIdentity, Depends(require_hannah_tester)]

# --- request and response models ------------------------------------------------------


def _plain_text(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    if any(ord(c) < 32 and c not in "\n\r\t" or ord(c) == 127 for c in value):
        raise ValueError("must not contain control characters")
    return value


class TurnIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: Annotated[StrictStr, StringConstraints(max_length=MAX_TURN_CHARS)]

    _content = field_validator("content")(_plain_text)


class MessageIn(BaseModel):
    """The employer's latest message and the recent conversation (browser memory only)."""

    model_config = ConfigDict(extra="forbid")

    message: Annotated[StrictStr, StringConstraints(max_length=MAX_MESSAGE_CHARS)]
    history: Annotated[list[TurnIn], Field(max_length=MAX_HISTORY_TURNS)] = []

    _message = field_validator("message")(_plain_text)


class AssistantStatusOut(BaseModel):
    available: bool
    reason: Reason | None
    notice: str


class AssistantReplyOut(BaseModel):
    reply: str
    provider: str
    model: str
    notice: str


def recent_turns(history: Sequence[TurnIn], message: str) -> list[ChatTurn]:
    """The newest history turns within ``MAX_HISTORY_CHARS``, then the message."""
    kept: list[ChatTurn] = []
    budget = MAX_HISTORY_CHARS
    for turn in reversed(history):
        budget -= len(turn.content)
        if budget < 0:
            break
        kept.append(ChatTurn(role=turn.role, content=turn.content))
    kept.reverse()
    # Start with a user turn, as a conversation does.
    while kept and kept[0].role != "user":
        kept.pop(0)
    return [*kept, ChatTurn(role="user", content=message)]


def _require_case(scope: CompanyAdminReadOnlyDb, case_id: UUID) -> None:
    if workflows.get_workflow_case(scope, case_id) is None:
        raise _not_found()


# --- routes ---------------------------------------------------------------------------


@router.get("/cases/{case_id}/assistant", response_model=AssistantStatusOut)
def get_assistant_status(
    case_id: UUID,
    scope: CompanyAdminReadOnlyDb,
    identity: Identity,
    demo: Demo,
) -> AssistantStatusOut:
    """Whether this administrator can talk to Hannah in this Case."""
    _require_case(scope, case_id)
    reason: Reason | None
    if not demo.enabled:
        reason = "disabled"
    elif identity.subject not in demo.testers:
        reason = "not_a_tester"
    elif demo.provider is None:
        reason = "not_configured"
    else:
        reason = None
    return AssistantStatusOut(available=reason is None, reason=reason, notice=NOTICE)


@router.post("/cases/{case_id}/assistant/messages", response_model=AssistantReplyOut)
def send_assistant_message(
    case_id: UUID,
    body: MessageIn,
    scope: CompanyAdminReadOnlyDb,
    tester: Tester,
    demo: Demo,
) -> AssistantReplyOut:
    """One message to Hannah; her reply. Nothing is stored and the Case doesn't change."""
    _require_case(scope, case_id)
    # Release the database connection before waiting on the provider.
    scope.session.rollback()
    provider = demo.provider
    if provider is None:
        logger.warning("Hannah demo unavailable: no provider key configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Not configured"
        )
    wait = demo.limiter.acquire(tester.subject)
    if wait is not None:
        logger.info("Hannah demo reply refused (outcome=tester_limit)")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers={"Retry-After": str(wait)},
        )
    turns = recent_turns(body.history, body.message)
    try:
        reply = provider.reply(HANNAH_SYSTEM_INSTRUCTION, turns)
    except AssistantError as exc:
        logger.warning(
            "Hannah demo reply failed (provider=%s, outcome=%s)", provider.name, exc.kind
        )
        if exc.kind == "rate_limited":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests",
                headers={"Retry-After": str(exc.retry_after or 60)},
            ) from None
        if exc.kind == "timeout":
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Timed out"
            ) from None
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Unavailable") from None
    logger.info(
        "Hannah demo reply (provider=%s, model=%s, outcome=ok, turns=%d)",
        provider.name,
        provider.model,
        len(turns),
    )
    return AssistantReplyOut(
        reply=reply, provider=provider.name, model=provider.model, notice=NOTICE
    )
