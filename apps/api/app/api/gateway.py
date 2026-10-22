"""Ask HeroOS (M2-NEW-05/06/07): persistent conversations at Company level.

The founder explains a situation in their own words; HeroOS answers from the
approved knowledge runtime (``app.assistant.gateway``) and keeps the visible
conversation (``app.conversations``). Every route goes through the same chain
as the other administrator routes: a verified credential, an active
Membership and the ``company_admin`` role, checked again inside the
transaction. The Company context is the canonical ``CompanyBlueprintContext``,
loaded server-side. The conversation belongs to the Company: any of its
administrators can read and continue it.

The browser is thin. A message carries only the founder's text, a
client-generated ``turn_key``, the ``conversation_id`` (none for a new one)
and the ``expected_revision`` it last saw. Nothing else is accepted
(``extra="forbid"``): not history, facts, a workflow, a pathway, a
jurisdiction, a Case, an outcome, an evaluation, a profile, a digest or a
continuation. The server rebuilds the context from the Blueprint, the Case's
facts, the conversation's checkpoint and its recent visible messages. A
resource id identifies; it never authorizes.

Routes:

- ``GET /companies/{id}/assistant``: whether Ask HeroOS can answer here.
- ``POST /companies/{id}/assistant/messages``: one turn. 200 with the
  conversation (summary and current status) and the turn's two visible
  messages; the same ``turn_key`` again replays the committed turn (no model
  request); with another message, conversation or revision it is 409.
- ``GET /companies/{id}/assistant/conversations``: the Company's
  conversations, most recently active first (``before``/``next_before``).
- ``GET /companies/{id}/assistant/conversations/{conversation_id}``: one
  conversation, its status and its latest messages.
- ``GET .../conversations/{conversation_id}/messages``: older messages
  (``before`` a message sequence).

A message's author is relative to the viewer (``you``, ``another_administrator``,
``heroos``), never a person's id or identity. Nothing internal reaches the
browser: no understanding, knowledge, Condition, rule, binding, profile,
evaluation record, checkpoint, digest, provider body or prompt.

Responses: 401 / 403 as the Company routes; 404 ``Not found`` (an unknown
conversation, another Company's, or the gateway disabled for a new turn); 409
``Conflict``; 422 field locations only; 429 ``Too many requests`` with
``Retry-After``; 503 ``Not configured`` / ``Knowledge unavailable``; 504
``Timed out``; 502 ``Unavailable``. A failed turn stores nothing.
"""

import logging
from datetime import datetime
from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.api.assistant import MAX_MESSAGE_CHARS
from app.assistant.gateway.service import (
    AiGateway,
    ConversationState,
    GatewayFailure,
    GatewayReason,
)
from app.auth.dependencies import CompanyAdminContext, forbidden
from app.auth.exceptions import AuthorizationError
from app.conversations.service import (
    MAX_REVISION,
    AskConversations,
    ConversationConflict,
    ConversationNotFound,
    ConversationSummary,
    InvalidMessage,
    StoredMessage,
    TurnRequest,
    check_message,
)
from app.conversations.status import ConversationStatus
from app.tenancy.dependencies import CompanyAdminDb, CompanyAdminReadOnlyDb

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies/{company_id}", tags=["assistant"])

# Page sizes (a bound on the response, not a product rule).
DEFAULT_CONVERSATIONS: Final = 20
MAX_CONVERSATIONS: Final = 50
DEFAULT_MESSAGES: Final = 30
MAX_MESSAGES: Final = 100
# The conversation list cursor: activity time in microseconds, and the id.
CONVERSATION_CURSOR: Final = r"^[0-9]{1,20}\.[0-9a-f]{32}$"


def ai_gateway(request: Request) -> AiGateway:
    gateway: AiGateway = request.app.state.ai_gateway
    return gateway


Gateway = Annotated[AiGateway, Depends(ai_gateway)]


def ask_conversations(request: Request, gateway: Gateway) -> AskConversations:
    return AskConversations(
        gateway,
        policy=request.app.state.sensitive_screening,
        rules=request.app.state.rule_bundle,
    )


Conversations = Annotated[AskConversations, Depends(ask_conversations)]


def _message_text(value: str) -> str:
    try:
        check_message(value)
    except InvalidMessage as invalid:
        raise ValueError(f"invalid ({invalid})") from None
    return value


class MessageIn(BaseModel):
    """One founder message. Nothing else: the server holds everything that decides anything."""

    model_config = ConfigDict(extra="forbid")

    # None: the first message of a new conversation.
    conversation_id: UUID | None = None
    # The conversation revision the browser last saw (0 for a new conversation).
    expected_revision: Annotated[StrictInt, Field(ge=0, le=MAX_REVISION)]
    # Client-generated per send attempt; a retry sends the same key.
    turn_key: UUID
    message: Annotated[StrictStr, StringConstraints(max_length=MAX_MESSAGE_CHARS)]

    _message = field_validator("message")(_message_text)

    @model_validator(mode="after")
    def _new_conversation_starts_at_zero(self) -> "MessageIn":
        if self.conversation_id is None and self.expected_revision != 0:
            raise ValueError("a new conversation starts at revision 0")
        return self


class GatewayStatusOut(BaseModel):
    available: bool
    reason: GatewayReason | None
    notice: str | None


class OutcomeItemOut(BaseModel):
    kind: Literal["guidance", "warning", "block", "expert_review"]
    text: str


class OutcomeOut(BaseModel):
    """The deterministic outcome as shown, in the server's words (never a rule or a trace)."""

    kind: Literal["guidance", "warning", "block", "expert_review", "unavailable"]
    title: str
    message: str
    items: list[OutcomeItemOut]


class MessageOut(BaseModel):
    sequence: int
    # Relative to the viewer: never a person's id, email or identity.
    author: Literal["you", "another_administrator", "heroos"]
    text: str
    safe_next_step: str | None
    # HeroOS messages only: how the turn was handled.
    conversation_state: ConversationState | None
    outcome: OutcomeOut | None
    created_at: datetime


class CaseLinkOut(BaseModel):
    id: UUID
    title: str


class WorkflowOut(BaseModel):
    key: str
    title: str | None


class ExpertReviewOut(BaseModel):
    active: bool
    scope: Literal["action", "matter"] | None
    # The decisions it holds, by title.
    actions: list[str]
    # Whether HeroOS can take an Expert Review request now (a current capability).
    service_available: bool


class AttentionOut(BaseModel):
    needs_information: bool
    # Jurisdiction-specific guidance waits for the employer to confirm the jurisdiction.
    jurisdiction: Literal["needs_confirmation"] | None
    expert_review: ExpertReviewOut


class StatusOut(BaseModel):
    """Separate dimensions, never one enum: an action's review doesn't pause the Case."""

    lifecycle: Literal["in_progress", "paused"] | None
    workflow: WorkflowOut | None
    attention: AttentionOut
    checks: Literal["ready", "unavailable", "not_applicable"]
    latest_outcome: Literal["guidance", "warning", "block", "expert_review", "unavailable", "none"]


class ConversationSummaryOut(BaseModel):
    id: UUID
    # A safe server-chosen title (never a name); None until the conversation has a Case.
    title: str | None
    case: CaseLinkOut | None
    created_at: datetime
    updated_at: datetime


class ConversationOut(ConversationSummaryOut):
    # Send it back as ``expected_revision`` with the next message.
    revision: int
    status: StatusOut


class TurnOut(BaseModel):
    conversation: ConversationOut
    # The founder's message and HeroOS's reply, in order.
    messages: list[MessageOut]
    replayed: bool


class ConversationListOut(BaseModel):
    items: list[ConversationSummaryOut]
    next_before: str | None


class MessagePageOut(BaseModel):
    messages: list[MessageOut]
    # The ``before`` of the previous (older) page; None at the start.
    next_before: int | None


class ConversationDetailOut(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]
    next_before: int | None


FAILURES: Final[dict[str, tuple[int, str]]] = {
    "not_configured": (status.HTTP_503_SERVICE_UNAVAILABLE, "Not configured"),
    "knowledge_unavailable": (status.HTTP_503_SERVICE_UNAVAILABLE, "Knowledge unavailable"),
    "rate_limited": (status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests"),
    "timeout": (status.HTTP_504_GATEWAY_TIMEOUT, "Timed out"),
    "unavailable": (status.HTTP_502_BAD_GATEWAY, "Unavailable"),
    "invalid_output": (status.HTTP_502_BAD_GATEWAY, "Unavailable"),
}


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _message_out(message: StoredMessage, viewer: UUID) -> MessageOut:
    if message.role == "heroos":
        author: Literal["you", "another_administrator", "heroos"] = "heroos"
    else:
        author = "you" if message.actor_user_id == viewer else "another_administrator"
    card = message.outcome
    return MessageOut(
        sequence=message.sequence,
        author=author,
        text=message.content,
        safe_next_step=message.safe_next_step,
        conversation_state=message.conversation_state,  # type: ignore[arg-type]  # CHECK
        outcome=None
        if card is None
        else OutcomeOut(
            kind=card["kind"],
            title=card["title"],
            message=card["message"],
            items=[OutcomeItemOut(kind=i["kind"], text=i["text"]) for i in card["items"]],
        ),
        created_at=message.created_at,
    )


def _status_out(value: ConversationStatus) -> StatusOut:
    review = value.expert_review
    return StatusOut(
        lifecycle=value.lifecycle,
        workflow=None
        if value.workflow is None
        else WorkflowOut(key=value.workflow, title=value.workflow_title),
        attention=AttentionOut(
            needs_information=value.needs_information,
            jurisdiction=value.jurisdiction,
            expert_review=ExpertReviewOut(
                active=review.active,
                scope=review.scope,
                actions=list(review.actions),
                service_available=review.service_available,
            ),
        ),
        checks=value.checks,
        latest_outcome=value.latest_outcome,
    )


def _summary_out(summary: ConversationSummary) -> ConversationSummaryOut:
    return ConversationSummaryOut(
        id=summary.id,
        title=summary.title,
        case=None
        if summary.case_id is None or summary.case_title is None
        else CaseLinkOut(id=summary.case_id, title=summary.case_title),
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


def _conversation_out(summary: ConversationSummary, value: ConversationStatus) -> ConversationOut:
    return ConversationOut(
        **_summary_out(summary).model_dump(), revision=summary.revision, status=_status_out(value)
    )


@router.get("/assistant", response_model=GatewayStatusOut)
def get_gateway_status(scope: CompanyAdminReadOnlyDb, gateway: Gateway) -> GatewayStatusOut:
    """Whether Ask HeroOS can answer for this administrator's Company."""
    reason = gateway.reason
    return GatewayStatusOut(
        available=reason is None,
        reason=reason,
        notice=gateway.notice if reason is None else None,
    )


@router.post("/assistant/messages", response_model=TurnOut)
def send_gateway_message(
    body: MessageIn,
    scope: CompanyAdminDb,
    context: CompanyAdminContext,
    gateway: Gateway,
    service: Conversations,
) -> TurnOut:
    """One founder message and HeroOS's reply, stored together (or nothing, on failure)."""
    if gateway.reason == "disabled":
        raise _not_found()
    request = TurnRequest(
        message=body.message,
        turn_key=body.turn_key,
        conversation_id=body.conversation_id,
        expected_revision=body.expected_revision,
    )
    try:
        result = service.run_turn(scope.session, context, request)
    except InvalidMessage:
        raise RequestValidationError(
            [{"type": "value_error", "loc": ("body", "message"), "msg": "invalid"}]
        ) from None
    except ConversationNotFound:
        raise _not_found() from None
    except ConversationConflict:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflict") from None
    except AuthorizationError:
        raise forbidden() from None
    except GatewayFailure as failure:
        code, detail = FAILURES[failure.kind]
        headers = (
            {"Retry-After": str(failure.retry_after or 60)}
            if failure.kind == "rate_limited"
            else None
        )
        raise HTTPException(status_code=code, detail=detail, headers=headers) from None
    assert result.summary is not None and result.status is not None
    return TurnOut(
        conversation=_conversation_out(result.summary, result.status),
        messages=[
            _message_out(result.founder, context.user_id),
            _message_out(result.heroos, context.user_id),
        ],
        replayed=result.replayed,
    )


@router.get("/assistant/conversations", response_model=ConversationListOut)
def list_conversations(
    scope: CompanyAdminReadOnlyDb,
    service: Conversations,
    limit: Annotated[int, Query(ge=1, le=MAX_CONVERSATIONS)] = DEFAULT_CONVERSATIONS,
    # The ``next_before`` of the previous page.
    before: Annotated[str | None, Query(max_length=60, pattern=CONVERSATION_CURSOR)] = None,
    # Only the conversation this Case is attached to (a Case has at most one).
    case_id: UUID | None = None,
) -> ConversationListOut:
    """The Company's conversations, most recently active first (or one Case's)."""
    if case_id is not None and before is not None:
        raise HTTPException(status_code=422, detail="A Case's conversation is a single page.")
    page = service.list_conversations(scope, limit=limit, before=before, case_id=case_id)
    return ConversationListOut(
        items=[_summary_out(s) for s in page.items], next_before=page.next_before
    )


@router.get("/assistant/conversations/{conversation_id}", response_model=ConversationDetailOut)
def get_conversation(
    conversation_id: UUID,
    scope: CompanyAdminReadOnlyDb,
    context: CompanyAdminContext,
    service: Conversations,
    limit: Annotated[int, Query(ge=1, le=MAX_MESSAGES)] = DEFAULT_MESSAGES,
) -> ConversationDetailOut:
    """One conversation: its summary, current status and latest messages."""
    try:
        view = service.conversation(scope, conversation_id, limit=limit)
    except ConversationNotFound:
        raise _not_found() from None
    return ConversationDetailOut(
        conversation=_conversation_out(view.summary, view.status),
        messages=[_message_out(m, context.user_id) for m in view.page.messages],
        next_before=view.page.next_before,
    )


@router.get("/assistant/conversations/{conversation_id}/messages", response_model=MessagePageOut)
def list_conversation_messages(
    conversation_id: UUID,
    scope: CompanyAdminReadOnlyDb,
    context: CompanyAdminContext,
    service: Conversations,
    limit: Annotated[int, Query(ge=1, le=MAX_MESSAGES)] = DEFAULT_MESSAGES,
    # The ``next_before`` of the previous page (a message sequence).
    before: Annotated[int | None, Query(ge=2, le=2 * MAX_REVISION + 1)] = None,
) -> MessagePageOut:
    """Older visible messages of one conversation, oldest first within the page."""
    try:
        page = service.messages(scope, conversation_id, limit=limit, before=before)
    except ConversationNotFound:
        raise _not_found() from None
    return MessagePageOut(
        messages=[_message_out(m, context.user_id) for m in page.messages],
        next_before=page.next_before,
    )
