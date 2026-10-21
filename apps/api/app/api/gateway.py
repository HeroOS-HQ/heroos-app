"""Ask HeroOS: the controlled AI conversation gateway (M2-NEW-05), at Company level.

No Case is needed: the founder explains a situation in their own words and
HeroOS answers from the approved knowledge runtime (``app.assistant.gateway``).

Every request goes through the same chain as the other administrator routes,
all before any model request: a verified credential, an active Membership,
the ``company_admin`` role (checked again inside the transaction) and a
transaction that refuses every write. The Company context is the canonical
``CompanyBlueprintContext`` only, loaded server-side; nothing the client
sends names a company, jurisdiction, provider, model or URL. The database
connection is released before the provider is called.

Routes:

- ``GET /companies/{id}/assistant``: whether the gateway can answer here
  (``available``, a fixed ``reason`` and an optional notice), for the page.
- ``POST /companies/{id}/assistant/messages``: the founder's message, a bounded
  recent conversation (browser memory only) and the opaque ``continuation``
  of the previous reply in; HeroOS's reply out: ``reply``, an optional
  ``safe_next_step``, a ``conversation_state`` (``responded``, ``clarifying``
  or ``outside_approved_guidance``: how the turn was handled), the
  ``outcome`` HeroOS's deterministic checks decided (M2-NEW-06: Guidance,
  Warning, Block or Expert Review with a title, a message and one line per
  requested step, or ``unavailable`` when the checks can't run; null when
  there is none) and the next ``continuation`` (encrypted, opaque). Nothing
  else: no understanding, knowledge, Condition, rule, binding, profile,
  evaluation trace, source, digest, provider body or prompt reaches the
  browser, and nothing the browser sends can choose or change the outcome.

Nothing is stored: not the conversation, its facts, a Case or a decision.

Responses: 401 / 403 exactly as the Company routes; 404 while the gateway is
disabled; 422 field locations only; 429 ``Too many requests`` (an account or
service limit, or the provider's, with ``Retry-After``); 503 ``Not
configured`` or ``Knowledge unavailable`` (no model request is made); 504
``Timed out``; 502 ``Unavailable`` (any other provider failure, or output that
stayed invalid after one repair).
"""

import logging
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StrictStr, StringConstraints, field_validator

from app.api.assistant import MAX_HISTORY_TURNS, MAX_MESSAGE_CHARS, TurnIn, _plain_text
from app.assistant.gateway.service import (
    AiGateway,
    ConversationState,
    FounderTurn,
    GatewayFailure,
    GatewayReason,
)
from app.assistant.provider import ChatTurn
from app.auth.dependencies import CompanyAdminContext, forbidden
from app.auth.exceptions import AuthorizationError
from app.companies.blueprint import load_company_blueprint_context
from app.evaluation.continuation import MAX_TOKEN_CHARS
from app.tenancy.dependencies import CompanyAdminReadOnlyDb

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies/{company_id}", tags=["assistant"])

# An opaque token's shape only: the current encrypted form, or an earlier signed one, which
# the codec rejects as lost state (re-confirmed), so a deploy never breaks a conversation.
CONTINUATION_PATTERN: Final = r"^[A-Za-z0-9_-]{1,40}(?:\.[A-Za-z0-9_-]{1,2380}){1,2}$"


def ai_gateway(request: Request) -> AiGateway:
    gateway: AiGateway = request.app.state.ai_gateway
    return gateway


Gateway = Annotated[AiGateway, Depends(ai_gateway)]


class GatewayMessageIn(BaseModel):
    """The founder's message, the recent conversation and the previous reply's continuation."""

    model_config = ConfigDict(extra="forbid")

    message: Annotated[StrictStr, StringConstraints(max_length=MAX_MESSAGE_CHARS)]
    history: Annotated[list[TurnIn], Field(max_length=MAX_HISTORY_TURNS)] = []
    continuation: (
        Annotated[
            StrictStr,
            StringConstraints(max_length=MAX_TOKEN_CHARS, pattern=CONTINUATION_PATTERN),
        ]
        | None
    ) = None

    _message = field_validator("message")(_plain_text)


class GatewayStatusOut(BaseModel):
    available: bool
    reason: GatewayReason | None
    notice: str | None


class OutcomeItemOut(BaseModel):
    kind: Literal["guidance", "warning", "block", "expert_review"]
    text: str


class OutcomeOut(BaseModel):
    """The deterministic outcome, in the server's words (never a rule, Condition or trace)."""

    kind: Literal["guidance", "warning", "block", "expert_review", "unavailable"]
    title: str
    message: str
    items: list[OutcomeItemOut]


class GatewayReplyOut(BaseModel):
    reply: str
    safe_next_step: str | None
    conversation_state: ConversationState
    outcome: OutcomeOut | None
    continuation: str


FAILURES: Final[dict[str, tuple[int, str]]] = {
    "not_configured": (status.HTTP_503_SERVICE_UNAVAILABLE, "Not configured"),
    "knowledge_unavailable": (status.HTTP_503_SERVICE_UNAVAILABLE, "Knowledge unavailable"),
    "rate_limited": (status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests"),
    "timeout": (status.HTTP_504_GATEWAY_TIMEOUT, "Timed out"),
    "unavailable": (status.HTTP_502_BAD_GATEWAY, "Unavailable"),
    "invalid_output": (status.HTTP_502_BAD_GATEWAY, "Unavailable"),
}


@router.get("/assistant", response_model=GatewayStatusOut)
def get_gateway_status(scope: CompanyAdminReadOnlyDb, gateway: Gateway) -> GatewayStatusOut:
    """Whether Ask HeroOS can answer for this administrator's Company."""
    reason = gateway.reason
    return GatewayStatusOut(
        available=reason is None,
        reason=reason,
        notice=gateway.notice if reason is None else None,
    )


@router.post("/assistant/messages", response_model=GatewayReplyOut)
def send_gateway_message(
    body: GatewayMessageIn,
    scope: CompanyAdminReadOnlyDb,
    context: CompanyAdminContext,
    gateway: Gateway,
) -> GatewayReplyOut:
    """One founder message; HeroOS's reply. Nothing is stored and nothing changes."""
    if gateway.reason == "disabled":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    try:
        company = load_company_blueprint_context(scope, context)
    except AuthorizationError:
        raise forbidden() from None
    # Release the database connection before waiting on the provider.
    scope.session.rollback()
    turn = FounderTurn(
        message=body.message,
        history=tuple(ChatTurn(role=t.role, content=t.content) for t in body.history),
        continuation=body.continuation,
    )
    try:
        result = gateway.respond(company, turn)
    except GatewayFailure as failure:
        code, detail = FAILURES[failure.kind]
        headers = (
            {"Retry-After": str(failure.retry_after or 60)}
            if failure.kind == "rate_limited"
            else None
        )
        raise HTTPException(status_code=code, detail=detail, headers=headers) from None
    card = result.outcome
    return GatewayReplyOut(
        reply=result.reply,
        safe_next_step=result.safe_next_step,
        conversation_state=result.state,
        outcome=None
        if card is None
        else OutcomeOut(
            kind=card.kind,
            title=card.title,
            message=card.message,
            items=[OutcomeItemOut(kind=i.kind, text=i.text) for i in card.items],
        ),
        continuation=result.continuation,
    )
