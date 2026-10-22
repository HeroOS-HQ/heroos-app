"""Ask HeroOS turns that persist (M2-NEW-07): replay, load, answer, reconcile, record.

``AskConversations.run_turn`` handles one founder message from a Company
administrator. The browser sends only the message, its turn key, the
conversation id and the revision it last saw; everything else is the server's.

1. **Replay**: a ``turn_key`` already committed returns that turn, with no
   provider request. The same key with another message, conversation,
   revision or administrator is a conflict.
2. **Load** (a short read): the named conversation (another Company's is
   indistinguishable from none; a revision that moved on is a conflict before
   any model request), its latest visible messages, its checkpoint, its Case's
   facts and jurisdiction answer, and the Company Blueprint context. The
   transaction ends, and the connection is released, before the provider is
   called: no row is locked while a model answers.
3. **Answer**: the gateway (M2-NEW-05/06) starts from that server-side state
   (``FounderTurn.resume``), never from anything the browser holds, with the
   Case's authoritative workflow position (``FounderTurn.case``, M2-NEW-08:
   ``app.conversations.progress``). A provider failure writes nothing, so no
   empty conversation is ever stored.
4. **Record** (a short write), after confirming the administrator's role
   again: lock the conversation (a first turn creates it) and refuse a
   revision another turn consumed; lock the Case's workflow instance like
   every writer of it; reload the Case's facts, its workflow position and the Blueprint and
   **reconcile** (``AiGateway.reconcile``): the deterministic evaluation runs
   again on the current state, with no model request, and the freshest
   authoritative result is stored. The same result keeps the model's words;
   any other replaces them with the server's fixed text for the current
   result, except a weaker one that rests only on lost or less certain state,
   which never relaxes the stricter reply that was prepared. Then the
   turn, the two visible messages and the evaluation record are appended; the
   conversation's Case is started (its first turn: one conversation is one
   Case, chat-first) and takes its workflow at the threshold (``bridge``); the
   founder's newly established canonical facts go through the shared pipeline
   (``app.cases.mutation``); the active reviews, what the founder said that
   the Case could hold (``noted``, for the employer to save) and the next
   checkpoint are written.

Reads (``list_conversations``, ``conversation``, ``messages``) page by stable
keys and project the status (``status``) from the current authoritative state.
``save_noted`` is the employer's one explicit action that saves the noted
readings to the Case, through the same shared pipeline.

Nothing here selects a pathway, starts or completes a stage, records an
employer decision, creates a CaseSubject, closes a Case, deletes anything, or
stores a provider request or response, a prompt, a repair or the model's
reasoning.
"""

import json
import logging
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.assistant.gateway.service import (
    AiGateway,
    CaseContext,
    FounderTurn,
    GatewayReply,
    Reconciliation,
)
from app.assistant.provider import ChatTurn
from app.auth.exceptions import AuthorizationError
from app.auth.models import AuthenticatedCompanyContext
from app.auth.service import is_active_company_admin
from app.cases.mutation import (
    AssistantOrigin,
    CaseState,
    apply_case_fact_changes,
    evaluate_case,
    latest_fact_revisions,
)
from app.companies.blueprint import CompanyBlueprintContext, load_company_blueprint_context
from app.conversations import bridge
from app.conversations.checkpoint import (
    CaseView,
    Checkpoint,
    Resumed,
    Reviews,
    decode,
    encode,
    next_checkpoint,
    resume,
)
from app.conversations.progress import case_context, position
from app.conversations.status import Checks, ConversationStatus, NotedFact, project
from app.core.config import SensitiveScreening
from app.db.models import AssistantConversation, AssistantMessage, AssistantTurn
from app.db.models.assistant import MAX_EVALUATION_BYTES, MAX_FOUNDER_CHARS, MAX_TURNS
from app.evaluation.continuation import ReadResult
from app.evaluation.model import ConversationEvaluation, Value
from app.evaluation.snapshot import ExecutionSnapshot
from app.repositories import assistant_conversations as conversations
from app.repositories import cases, workflows
from app.tenancy.scope import CompanyScope, open_company_scope
from app.workflows.access import UNCLASSIFIED_CASE_TYPE
from app.workflows.definition import WorkflowDefinition, current_definition
from app.workflows.progression.bundle import RuleBundle

logger = logging.getLogger(__name__)

# The recent visible messages a turn reads back for the model (both roles; the gateway
# bounds them again by turns and characters). Older history stays in the product only.
HISTORY_MESSAGES: Final = 12
# The most turns (revisions) a conversation holds; a bound on storage, not a product rule.
MAX_REVISION: Final = MAX_TURNS
# A conversation's Case is created with a request key derived from its id (one Case each).
CASE_KEY_NAMESPACE: Final = uuid.UUID("6310dfcc-ffd6-4e5d-9010-d107045cdf35")
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


def case_request_key(conversation_id: UUID) -> UUID:
    return uuid.uuid5(CASE_KEY_NAMESPACE, str(conversation_id))


class InvalidMessage(ValueError):
    """A founder message HeroOS won't store (blank, too long, or with control characters)."""


def check_message(message: str) -> None:
    """The stored message's rules (``ck_assistant_messages_text``), before any work is done."""
    if not message.strip() or len(message) > MAX_FOUNDER_CHARS:
        raise InvalidMessage("length")
    if any(unicodedata.category(c) == "Cc" and c not in "\t\n\r" for c in message):
        raise InvalidMessage("control_character")


class ConversationNotFound(LookupError):
    """No such conversation in the caller's Company (identical for another Company's)."""


class ConversationConflict(Exception):
    """A turn key reused for another request, or a revision another turn consumed."""


class NothingNoted(LookupError):
    """No reading is waiting to be saved to the conversation's Case (or it has no workflow)."""


@dataclass(frozen=True, slots=True)
class TurnRequest:
    message: str
    # Client-generated per send attempt; a retry sends the same key.
    turn_key: UUID
    # None: the first turn of a new conversation (``expected_revision`` 0).
    conversation_id: UUID | None = None
    # The conversation revision the browser last saw.
    expected_revision: int = 0


@dataclass(frozen=True, slots=True)
class StoredMessage:
    id: UUID
    sequence: int
    role: str
    content: str
    safe_next_step: str | None
    conversation_state: str | None
    outcome: Mapping[str, Any] | None
    created_at: datetime
    # Server-side only (the API shows "you" or "another administrator", never an id).
    actor_user_id: UUID | None


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    id: UUID
    title: str | None
    revision: int
    case_id: UUID | None
    case_title: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TurnResult:
    conversation_id: UUID
    turn_id: UUID
    sequence: int
    case_id: UUID | None
    founder: StoredMessage
    heroos: StoredMessage
    # A committed turn returned again for the same request.
    replayed: bool = False
    summary: ConversationSummary | None = None
    status: ConversationStatus | None = None


@dataclass(frozen=True, slots=True)
class ConversationPage:
    items: tuple[ConversationSummary, ...]
    # Pass as ``before`` for the next (older) page; None at the end.
    next_before: str | None


@dataclass(frozen=True, slots=True)
class MessagePage:
    messages: tuple[StoredMessage, ...]
    # Pass as ``before`` for the previous (older) page; None at the start.
    next_before: int | None


@dataclass(frozen=True, slots=True)
class ConversationView:
    summary: ConversationSummary
    status: ConversationStatus
    page: MessagePage


@dataclass(frozen=True, slots=True)
class _Loaded:
    """What a turn read about its conversation before the provider was called."""

    conversation_id: UUID | None = None
    workflow: str | None = None
    history: tuple[ChatTurn, ...] = ()
    stored: object | None = None
    case: CaseView | None = None
    # M2-NEW-08: the Case's workflow position when the turn started (read-only for the AI).
    case_context: CaseContext | None = None


def _noted(stored: object | None) -> dict[str, str]:
    """The conversation's noted readings (already said; never trusted), from its checkpoint."""
    checkpoint = decode(stored)
    return {} if checkpoint is None else {k: str(v) for k, v in checkpoint.noted.items()}


class _Resume:
    """The gateway's ``resume``: the persisted state, for the snapshot the turn took."""

    def __init__(self, loaded: _Loaded, company: CompanyBlueprintContext) -> None:
        self._loaded = loaded
        self._company = company_jurisdiction(company)
        self.called = False
        self.resumed = Resumed(ReadResult(None, "missing", True))

    def __call__(self, snapshot: ExecutionSnapshot) -> ReadResult:
        loaded = self._loaded
        self.called = True
        self.resumed = resume(
            snapshot,
            stored=loaded.stored,
            workflow=loaded.workflow,
            case=loaded.case,
            company_jurisdiction=self._company,
        )
        return self.resumed.read


@dataclass(slots=True)
class _Recorded:
    result: TurnResult
    case_created: bool = False
    workflow_attached: bool = False
    facts: int = 0
    reconciliation: Reconciliation = "kept"
    checkpoint: str = "ok"


def company_jurisdiction(company: CompanyBlueprintContext) -> str | None:
    """The Blueprint's confirmed employment jurisdiction while guidance is allowed."""
    confirmed = company.jurisdiction
    return confirmed.employment_jurisdiction if confirmed.guidance_allowed else None


def _stored(message: AssistantMessage) -> StoredMessage:
    return StoredMessage(
        id=message.id,
        sequence=message.sequence,
        role=message.role,
        content=message.content,
        safe_next_step=message.safe_next_step,
        conversation_state=message.conversation_state,
        outcome=message.outcome,
        created_at=message.created_at,
        actor_user_id=message.actor_user_id,
    )


def _outcome(reply: GatewayReply) -> dict[str, object] | None:
    """The outcome card exactly as shown (the server's words; never a rule or a trace)."""
    card = reply.outcome
    if card is None:
        return None
    return {
        "kind": card.kind,
        "title": card.title,
        "message": card.message,
        "items": [{"kind": item.kind, "text": item.text} for item in card.items],
    }


def _size(data: Mapping[str, object]) -> int:
    return len(json.dumps(data, separators=(",", ":"), sort_keys=True).encode())


def evaluation_record(evaluation: ConversationEvaluation) -> dict[str, object]:
    """``ConversationEvaluation.record()``, bounded: Conditions that decided nothing go first."""
    record = evaluation.record()
    if _size(record) <= MAX_EVALUATION_BYTES:
        return record
    conditions: list[dict[str, object]] = record["conditions"]  # type: ignore[assignment]
    kept = [c for c in conditions if c["status"] in ("fired", "unknown") or c["action"]]
    record = {**record, "conditions": kept, "conditions_omitted": len(conditions) - len(kept)}
    if _size(record) > MAX_EVALUATION_BYTES:
        raise ValueError("the evaluation record exceeds its bound")
    return record


def _evaluation_fields(
    evaluation: ConversationEvaluation, reply: GatewayReply, snapshot: ExecutionSnapshot
) -> dict[str, object]:
    return {
        "evaluation_schema": evaluation.schema,
        "availability": evaluation.availability,
        "matter": evaluation.matter,
        "workflow_key": evaluation.workflow,
        "presentation": evaluation.presentation,
        "outcome": None if reply.outcome is None else reply.outcome.kind,
        "has_review_requirement": any(r.required for r in evaluation.reviews),
        "multiple_matters": bridge.multiple_matters(evaluation, reply.handoff),
        "snapshot_id": snapshot.id,
        "knowledge_runtime_digest": None
        if snapshot.knowledge is None
        else snapshot.knowledge.runtime_digest,
        "profile_digest": None if snapshot.profile is None else snapshot.profile.digest,
        "record": evaluation_record(evaluation),
        "withdrawn_actions": list(reply.handoff.withdrawn_actions),
    }


def conversation_cursor(conversation: AssistantConversation) -> str:
    """A keyset cursor (activity time in microseconds, and id) for the conversation list."""
    updated = conversation.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    micros = (updated - _EPOCH) // timedelta(microseconds=1)
    return f"{micros}.{conversation.id.hex}"


def parse_conversation_cursor(cursor: str) -> tuple[datetime, UUID]:
    """The inverse of ``conversation_cursor`` (the API checks its shape first)."""
    micros, _, ident = cursor.partition(".")
    return _EPOCH + timedelta(microseconds=int(micros)), UUID(hex=ident)


class AskConversations:
    """Persistent Ask HeroOS turns for one deployment (its gateway and installed rules)."""

    def __init__(
        self,
        gateway: AiGateway,
        *,
        policy: SensitiveScreening,
        rules: RuleBundle | None,
    ) -> None:
        self._gateway = gateway
        self._policy = policy
        self._rules = rules

    # --- a turn --------------------------------------------------------------------------

    def run_turn(
        self, session: Session, context: AuthenticatedCompanyContext, request: TurnRequest
    ) -> TurnResult:
        """One founder message and HeroOS's reply, stored together or not at all.

        Raises ``InvalidMessage``, ``GatewayFailure`` (nothing written),
        ``ConversationNotFound``, ``ConversationConflict`` and
        ``AuthorizationError`` (the administrator role ended while the provider
        answered).
        """
        check_message(request.message)
        if request.conversation_id is None and request.expected_revision != 0:
            raise ConversationConflict()
        scope = open_company_scope(session, context)
        replayed = self._replay(scope, context, request)
        if replayed is not None:
            return self._finish(scope, replayed)
        loaded = self._load(scope, request)
        company = load_company_blueprint_context(scope, context)
        # End the read and release the connection before waiting on the provider.
        session.rollback()
        state = _Resume(loaded, company)
        reply = self._gateway.respond(
            company,
            FounderTurn(
                request.message,
                loaded.history,
                resume=state,
                case=loaded.case_context,
                noted=_noted(loaded.stored),
            ),
        )

        scope = open_company_scope(session, context)
        if not is_active_company_admin(session, context):
            session.rollback()
            raise AuthorizationError("company administrator role no longer active")
        try:
            recorded = self._record(scope, context, request, loaded, reply, state.resumed)
            scope.commit()
        except IntegrityError:
            # A request with this turn key committed first: that request was this one.
            scope.rollback()
            replayed = self._replay(scope, context, request)
            if replayed is not None:
                return self._finish(scope, replayed)
            raise ConversationConflict() from None
        except BaseException:
            scope.rollback()
            raise
        # Counts and categories only: never a message, fact, value or title.
        logger.info(
            "Ask HeroOS turn recorded (company_id=%s, new_conversation=%s, case_created=%s, "
            "workflow_attached=%s, facts=%d, checkpoint=%s, reconciliation=%s)",
            scope.company_id,
            loaded.conversation_id is None,
            recorded.case_created,
            recorded.workflow_attached,
            recorded.facts,
            recorded.checkpoint,
            recorded.reconciliation,
        )
        return self._finish(scope, recorded.result)

    def _finish(self, scope: CompanyScope, result: TurnResult) -> TurnResult:
        """The turn with its conversation's summary and current status (a short read)."""
        conversation = conversations.get_conversation(scope, result.conversation_id)
        assert conversation is not None  # a conversation is never deleted
        summary = self._summaries(scope, [conversation])[0]
        status = self._status(scope, conversation)
        # Everything is read: end the transaction (no row attribute is touched after this).
        scope.session.rollback()
        return replace(result, case_id=summary.case_id, summary=summary, status=status)

    def _replay(
        self, scope: CompanyScope, context: AuthenticatedCompanyContext, request: TurnRequest
    ) -> TurnResult | None:
        """The committed turn of this request key, or None; a conflict if it was another request."""
        turn = conversations.find_turn(scope, request.turn_key)
        if turn is None:
            return None
        messages = conversations.turn_messages(scope, turn.id)
        founder = next(m for m in messages if m.role == "founder")
        heroos = next(m for m in messages if m.role == "heroos")
        same_conversation = (
            turn.sequence == 1
            if request.conversation_id is None
            else turn.conversation_id == request.conversation_id
        )
        if (
            not same_conversation
            or turn.sequence != request.expected_revision + 1
            or turn.actor_user_id != context.user_id
            or founder.content != request.message
        ):
            raise ConversationConflict()
        return TurnResult(
            conversation_id=turn.conversation_id,
            turn_id=turn.id,
            sequence=turn.sequence,
            case_id=None,
            founder=_stored(founder),
            heroos=_stored(heroos),
            replayed=True,
        )

    def _case_view(
        self, scope: CompanyScope, item: workflows.WorkflowCase
    ) -> tuple[CaseView, CaseState]:
        state = evaluate_case(scope, item, self._policy, self._rules)
        view = CaseView(
            answers=dict(state.answers),
            revisions=latest_fact_revisions(state.submissions),
            jurisdiction=state.intake.jurisdiction.status,
        )
        return view, state

    def _load(self, scope: CompanyScope, request: TurnRequest) -> _Loaded:
        if request.conversation_id is None:
            return _Loaded()
        conversation = conversations.get_conversation(scope, request.conversation_id)
        if conversation is None:
            raise ConversationNotFound()
        if conversation.revision != request.expected_revision:
            # Another turn completed since the browser read it: no model request for this one.
            raise ConversationConflict()
        history = tuple(
            ChatTurn("user" if m.role == "founder" else "assistant", m.content)
            for m in conversations.recent_messages(scope, conversation.id, limit=HISTORY_MESSAGES)
        )
        case = None
        context = None
        item = (
            None
            if conversation.case_id is None
            else workflows.get_workflow_case(scope, conversation.case_id)
        )
        if item is not None:  # a Case whose workflow isn't known yet has no position
            case, state = self._case_view(scope, item)
            context = self._case_context(scope, conversation, state)
        return _Loaded(
            conversation_id=conversation.id,
            workflow=conversation.workflow_key,
            history=history,
            stored=conversation.checkpoint,
            case=case,
            case_context=context,
        )

    def _reviews(self, scope: CompanyScope, conversation: AssistantConversation) -> Reviews:
        """The active reviews (the checkpoint's, or rebuilt from the turn records)."""
        checkpoint = decode(conversation.checkpoint)
        if checkpoint is not None:
            return checkpoint.reviews
        return Reviews.replay(conversations.review_history(scope, conversation.id))

    def _case_context(
        self, scope: CompanyScope, conversation: AssistantConversation, state: CaseState
    ) -> CaseContext:
        return case_context(state, reviews=self._reviews(scope, conversation))

    def _record(
        self,
        scope: CompanyScope,
        context: AuthenticatedCompanyContext,
        request: TurnRequest,
        loaded: _Loaded,
        reply: GatewayReply,
        first: Resumed,
    ) -> _Recorded:
        if loaded.conversation_id is None:
            conversation = conversations.create_conversation(
                scope,
                conversation_id=uuid.uuid4(),
                user_id=context.user_id,
                checkpoint=encode(Checkpoint(versions="")),
            )
        else:
            locked = conversations.get_conversation(scope, loaded.conversation_id, for_update=True)
            if locked is None:  # pragma: no cover - a conversation is never deleted
                raise ConversationNotFound()
            if locked.revision != request.expected_revision:
                # This reply answered a conversation another turn has since moved on.
                raise ConversationConflict()
            conversation = locked
        case_created = False
        if conversation.case_id is None:
            # One conversation is one Case: its first turn starts it, before its workflow is
            # known. A conversation stored before chat-first Cases gets its Case here too.
            self._start_case(scope, conversation)
            case_created = True
        # The Case's instance (None until its workflow is known), locked like every writer of
        # it: from here to the commit only.
        assert conversation.case_id is not None
        item = workflows.get_workflow_case(scope, conversation.case_id, for_update=True)
        case_state = None
        fresh_case = None
        fresh_context = None
        if item is not None:
            fresh_case, case_state = self._case_view(scope, item)
            # The Case's position now: another administrator may have moved it meanwhile.
            fresh_context = self._case_context(scope, conversation, case_state)
        company = load_company_blueprint_context(scope, context)
        fresh = _Resume(replace(loaded, case=fresh_case, case_context=fresh_context), company)
        reply, reconciliation = self._gateway.reconcile(
            company,
            FounderTurn(
                request.message,
                loaded.history,
                resume=fresh,
                case=fresh_context,
                noted=_noted(conversation.checkpoint),
            ),
            reply,
        )
        resumed = fresh.resumed if fresh.called else first
        handoff = reply.handoff
        evaluation, snapshot, next_state = handoff.evaluation, handoff.snapshot, reply.next_state
        assert evaluation is not None and snapshot is not None and next_state is not None

        sequence = conversation.revision + 1
        turn = conversations.record_turn(
            scope,
            conversation,
            sequence=sequence,
            turn_key=request.turn_key,
            user_id=context.user_id,
        )
        founder = conversations.record_message(
            scope,
            turn,
            sequence=2 * sequence - 1,
            role="founder",
            actor_user_id=context.user_id,
            content=request.message,
        )
        heroos = conversations.record_message(
            scope,
            turn,
            sequence=2 * sequence,
            role="heroos",
            content=reply.reply,
            safe_next_step=reply.safe_next_step,
            conversation_state=reply.state,
            outcome=_outcome(reply),
        )
        conversations.record_evaluation(
            scope, turn, **_evaluation_fields(evaluation, reply, snapshot)
        )

        blended = bridge.multiple_matters(evaluation, handoff)
        if blended:
            # Separate matters: nothing this turn established is carried or saved.
            prior = resumed.read.state
            next_state = replace(next_state, engine={} if prior is None else dict(prior.engine))
        attached = False
        today = datetime.now(UTC).date()
        if item is None:
            definition = bridge.case_definition(
                evaluation, handoff, conversation_workflow=conversation.workflow_key, has_case=False
            )
            if definition is not None:
                item = self._attach_workflow(scope, conversation, definition, context)
                case_state = None
                attached = True
        if item is not None and not blended and evaluation.workflow == item.instance.workflow_key:
            definition = current_definition(item.instance.workflow_key)
            title = (
                None
                if definition is None
                else bridge.better_title(item.case.title, handoff, definition, today)
            )
            if title is not None:
                item.case.title = conversation.title = title

        case_answers: dict[str, object] | None = None
        case_revision: int | None = None
        facts = 0
        earlier_checkpoint = decode(conversation.checkpoint)
        noted: dict[str, Value] = (
            {} if earlier_checkpoint is None else dict(earlier_checkpoint.noted)
        )
        if item is not None:
            case_answers, case_revision, facts, fresh_noted = self._apply_facts(
                scope,
                item,
                case_state,
                evaluation,
                snapshot,
                founder,
                turn,
                context,
                first.from_case | resumed.from_case,
                blended,
                # The founder's own words that established the matter become its narrative.
                narrative=request.message if attached else None,
            )
            # A turn about the Case's matter says what is noted now; any other keeps it.
            noted = (
                dict(fresh_noted)
                if fresh_noted is not None
                else {k: v for k, v in noted.items() if case_answers.get(k) != v}
            )
        earlier = resumed.reviews
        if earlier is None:
            # The checkpoint couldn't be read: rebuilt from the records, never forgotten.
            earlier = Reviews.replay(conversations.review_history(scope, conversation.id))
        reviews = earlier.after(evaluation, handoff.withdrawn_actions)
        workflow = conversation.workflow_key
        if workflow is not None and next_state.workflow not in (None, workflow):
            # Another workflow's state never replaces the conversation's own (reviews advance).
            kept = earlier_checkpoint or Checkpoint(versions="")
            stored = encode(replace(kept, reviews=reviews))
        else:
            stored = encode(
                replace(
                    next_checkpoint(
                        snapshot,
                        next_state,
                        resumed=resumed,
                        workflow=workflow,
                        case_answers=case_answers,
                        case_revision=case_revision,
                        company_jurisdiction=company_jurisdiction(company),
                        reviews=reviews,
                    ),
                    noted=noted,
                )
            )
        conversation.checkpoint = stored
        conversation.revision = sequence
        # The last completed turn (the list's order and cursor), to the microsecond.
        conversation.updated_at = datetime.now(UTC)
        scope.session.flush()
        result = TurnResult(
            conversation_id=conversation.id,
            turn_id=turn.id,
            sequence=turn.sequence,
            case_id=conversation.case_id,
            founder=_stored(founder),
            heroos=_stored(heroos),
        )
        return _Recorded(
            result,
            case_created=case_created,
            workflow_attached=attached,
            facts=facts,
            reconciliation=reconciliation,
            checkpoint="rebuilt" if resumed.rebuilt else "ok",
        )

    def _start_case(self, scope: CompanyScope, conversation: AssistantConversation) -> None:
        """The conversation's one Case, before anyone knows what the matter is."""
        case = cases.create_case(
            scope, case_type=UNCLASSIFIED_CASE_TYPE, title=bridge.NEW_CASE_TITLE
        )
        conversation.case_id = case.id
        conversation.title = case.title

    def _attach_workflow(
        self,
        scope: CompanyScope,
        conversation: AssistantConversation,
        definition: WorkflowDefinition,
        context: AuthenticatedCompanyContext,
    ) -> workflows.WorkflowCase:
        """The conversation's Case takes its workflow (keyed by the conversation, once)."""
        assert conversation.case_id is not None
        case = cases.get_case(scope, conversation.case_id)
        assert case is not None  # a conversation's Case can't be deleted (no cascade)
        item = workflows.attach_workflow(
            scope,
            case,
            definition,
            request_key=case_request_key(conversation.id),
            user_id=context.user_id,
        )
        conversation.workflow_key = item.instance.workflow_key
        return item

    def _apply_facts(
        self,
        scope: CompanyScope,
        item: workflows.WorkflowCase,
        state: CaseState | None,
        evaluation: ConversationEvaluation,
        snapshot: ExecutionSnapshot,
        founder: AssistantMessage,
        turn: AssistantTurn,
        context: AuthenticatedCompanyContext,
        from_case: frozenset[str],
        blended: bool,
        *,
        narrative: str | None = None,
    ) -> tuple[dict[str, object], int, int, dict[str, str] | None]:
        """The founder's new canonical facts through the shared pipeline; the Case after it,
        and what the founder said that the Case could hold (None: this turn wasn't about it)."""
        if state is None:
            state = evaluate_case(scope, item, self._policy, self._rules)
        answers = dict(state.answers)
        revision = item.instance.revision
        execution = snapshot.execution(item.instance.workflow_key)
        if execution is None or blended or evaluation.workflow != item.instance.workflow_key:
            return answers, revision, 0, None
        today = datetime.now(UTC).date()
        open_steps = state.intake.available_steps
        changes = bridge.fact_changes(
            evaluation,
            execution,
            state.definition,
            current=state.answers,
            open_steps=open_steps,
            from_case=from_case,
            today=today,
        )
        if narrative is not None:
            changes.update(
                bridge.narrative_change(
                    state.definition,
                    narrative,
                    evaluation,
                    current={**state.answers, **changes},
                    open_steps=open_steps,
                    today=today,
                )
            )
        noted = bridge.noted_facts(
            evaluation,
            execution,
            state.definition,
            current={**state.answers, **changes},
            open_steps=open_steps,
            today=today,
        )
        if not changes:
            return answers, revision, 0, noted
        applied = apply_case_fact_changes(
            scope,
            item,
            state,
            origin=AssistantOrigin(founder.id),
            changes=changes,
            expected_revision=revision,
            idempotency_key=turn.id,
            user_id=context.user_id,
            policy=self._policy,
            bundle=self._rules,
        )
        if applied is None:  # pragma: no cover - the instance is locked
            raise ConversationConflict()
        return {**answers, **changes}, applied.revision, len(changes), noted

    # --- the employer saves what was noted ------------------------------------------------

    def save_noted(
        self,
        session: Session,
        context: AuthenticatedCompanyContext,
        conversation_id: UUID,
        *,
        expected_revision: int,
        confirmed: frozenset[str],
    ) -> tuple[ConversationSummary, ConversationStatus]:
        """Saves what the founder said that the Case could hold: the employer's explicit action.

        ``confirmed``: the noted items the employer ticked, by their label; the
        others are discarded (not saved). The values are the server's own (the
        checkpoint's canonical readings, checked again against the Case now),
        never the browser's. They go through the shared pipeline as an Ask
        HeroOS submission of the conversation's latest founder message. Raises
        ``ConversationNotFound``, ``ConversationConflict`` (the conversation
        moved on) and ``NothingNoted``.
        """
        scope = open_company_scope(session, context)
        try:
            conversation = conversations.get_conversation(scope, conversation_id, for_update=True)
            if conversation is None:
                raise ConversationNotFound()
            if conversation.revision != expected_revision:
                raise ConversationConflict()
            checkpoint = decode(conversation.checkpoint)
            item = (
                None
                if conversation.case_id is None
                else workflows.get_workflow_case(scope, conversation.case_id, for_update=True)
            )
            founder = conversations.latest_message(scope, conversation.id, "founder")
            if checkpoint is None or not checkpoint.noted or item is None or founder is None:
                raise NothingNoted()
            state = evaluate_case(scope, item, self._policy, self._rules)
            accepted = bridge.accepted_values(
                checkpoint.noted,
                state.definition,
                current=state.answers,
                open_steps=state.intake.available_steps,
                today=datetime.now(UTC).date(),
            )
            labels = bridge.noted_labels(accepted, state.definition)
            changes = {k: v for k, v in accepted.items() if labels.get(k) in confirmed}
            if changes:
                applied = apply_case_fact_changes(
                    scope,
                    item,
                    state,
                    origin=AssistantOrigin(founder.id),
                    changes=changes,
                    expected_revision=item.instance.revision,
                    idempotency_key=uuid.uuid4(),
                    user_id=context.user_id,
                    policy=self._policy,
                    bundle=self._rules,
                )
                if applied is None:  # pragma: no cover - the instance is locked
                    raise ConversationConflict()
            # Saved (or no longer applicable): nothing stays noted. Not a turn: no new revision.
            conversation.checkpoint = encode(replace(checkpoint, noted={}))
            scope.session.flush()
            scope.commit()
        except BaseException:
            scope.rollback()
            raise
        logger.info(
            "Ask HeroOS noted facts saved (company_id=%s, facts=%d)",
            scope.company_id,
            len(changes),
        )
        found = conversations.get_conversation(scope, conversation_id)
        assert found is not None  # a conversation is never deleted
        summary, status = self._summaries(scope, [found])[0], self._status(scope, found)
        scope.session.rollback()
        return summary, status

    # --- reads -----------------------------------------------------------------------

    def list_conversations(
        self,
        scope: CompanyScope,
        *,
        limit: int,
        before: str | None = None,
        case_id: UUID | None = None,
    ) -> ConversationPage:
        """The Company's conversations, most recently active first (keyset pages).

        ``case_id``: only the conversation that Case is attached to (one page, at most one).
        """
        if case_id is not None:
            found = conversations.find_case_conversation(scope, case_id)
            return ConversationPage(tuple(self._summaries(scope, [found] if found else [])), None)
        rows = list(
            conversations.list_conversations(
                scope,
                limit=limit + 1,
                before=None if before is None else parse_conversation_cursor(before),
            )
        )
        more = len(rows) > limit
        rows = rows[:limit]
        return ConversationPage(
            tuple(self._summaries(scope, rows)),
            conversation_cursor(rows[-1]) if more and rows else None,
        )

    def conversation(
        self, scope: CompanyScope, conversation_id: UUID, *, limit: int
    ) -> ConversationView:
        """One conversation: its summary, current status and latest messages."""
        found = conversations.get_conversation(scope, conversation_id)
        if found is None:
            raise ConversationNotFound()
        return ConversationView(
            self._summaries(scope, [found])[0],
            self._status(scope, found),
            self.messages(scope, conversation_id, limit=limit),
        )

    def messages(
        self, scope: CompanyScope, conversation_id: UUID, *, limit: int, before: int | None = None
    ) -> MessagePage:
        """A page of visible messages, oldest first; ``before`` a message sequence."""
        if conversations.get_conversation(scope, conversation_id) is None:
            raise ConversationNotFound()
        rows = conversations.recent_messages(scope, conversation_id, limit=limit, before=before)
        first = rows[0].sequence if rows else None
        return MessagePage(
            tuple(_stored(m) for m in rows),
            first if first is not None and first > 1 else None,
        )

    def _summaries(
        self, scope: CompanyScope, rows: Sequence[AssistantConversation]
    ) -> list[ConversationSummary]:
        titles = conversations.case_titles(
            scope, [r.case_id for r in rows if r.case_id is not None]
        )
        return [
            ConversationSummary(
                id=r.id,
                title=r.title,
                revision=r.revision,
                case_id=r.case_id,
                case_title=None if r.case_id is None else titles.get(r.case_id),
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    def _checks(self, snapshot: ExecutionSnapshot, workflow: str | None) -> Checks:
        """The deterministic checks as the runtime is now (technical; never a lifecycle)."""
        if self._gateway.reason is not None:
            return "unavailable"
        if workflow is None:
            return "not_applicable"
        return "ready" if snapshot.availability(workflow) == "ready" else "unavailable"

    def _status(
        self, scope: CompanyScope, conversation: AssistantConversation
    ) -> ConversationStatus:
        snapshot = self._gateway.snapshot()
        latest = conversations.latest_evaluation(scope, conversation.id)
        workflow = conversation.workflow_key
        if workflow is None and latest is not None and latest.matter == "supported":
            workflow = latest.workflow_key
        case_hold: bool | None = None
        title = None
        where = None
        jurisdiction = [None if latest is None else latest.record.get("jurisdiction_state")]
        item = (
            None
            if conversation.case_id is None
            else workflows.get_workflow_case(scope, conversation.case_id)
        )
        noted: tuple[NotedFact, ...] = ()
        if conversation.case_id is not None and item is None:
            # A Case whose workflow isn't known yet: in progress, and no workflow until it has one.
            case_hold = False
            workflow = None
        if item is not None:
            state = evaluate_case(scope, item, self._policy, self._rules)
            checkpoint = decode(conversation.checkpoint)
            if checkpoint is not None and checkpoint.noted:
                noted = tuple(
                    NotedFact(label, answer)
                    for label, answer in bridge.noted_view(
                        bridge.accepted_values(
                            checkpoint.noted,
                            state.definition,
                            current=state.answers,
                            open_steps=state.intake.available_steps,
                            today=datetime.now(UTC).date(),
                        ),
                        state.definition,
                    )
                )
            hold = state.intake.hold
            # Only a whole-matter hold pauses the Case; a jurisdiction pause is attention.
            case_hold = hold is not None and hold.kind == "specialist_review"
            jurisdiction.append(state.intake.jurisdiction.status)
            title = state.definition.title
            where = position(state)
        elif workflow is not None:
            definition = current_definition(workflow)
            title = None if definition is None else definition.title
        reviews = self._reviews(scope, conversation)
        heroos = conversations.latest_message(scope, conversation.id, "heroos")
        knowledge = snapshot.knowledge
        return project(
            case_hold=case_hold,
            jurisdiction_states=jurisdiction,
            workflow=workflow,
            workflow_title=title,
            reviews=reviews,
            latest_record=None if latest is None else latest.record,
            latest_outcome=None
            if heroos is None or heroos.outcome is None
            else str(heroos.outcome.get("kind")),
            checks=self._checks(snapshot, workflow),
            action_titles={} if knowledge is None else {o.id: o.title for o in knowledge.options},
            position=where,
            noted=noted,
        )
