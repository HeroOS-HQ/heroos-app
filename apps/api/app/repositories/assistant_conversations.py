"""Company-scoped persistence of Ask HeroOS conversations (M2-NEW-07).

Every function takes a ``CompanyScope`` and filters by ``scope.company_id``;
PostgreSQL RLS enforces the same boundary underneath. Functions flush but
never commit. Turns, messages and evaluations are append-only; a
conversation's own state (revision, Case attachment, workflow, title,
checkpoint) is updated only on the row its turn locked.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, tuple_

from app.db.models import (
    AssistantConversation,
    AssistantMessage,
    AssistantTurn,
    AssistantTurnEvaluation,
    Case,
)
from app.tenancy.scope import CompanyScope


def create_conversation(
    scope: CompanyScope, *, conversation_id: UUID, user_id: UUID, checkpoint: Mapping[str, Any]
) -> AssistantConversation:
    """A new conversation (its first turn is recorded in the same transaction)."""
    conversation = AssistantConversation(
        id=conversation_id,
        company_id=scope.company_id,
        created_by_user_id=user_id,
        revision=0,
        checkpoint=dict(checkpoint),
    )
    scope.session.add(conversation)
    scope.session.flush()
    return conversation


def get_conversation(
    scope: CompanyScope, conversation_id: UUID, *, for_update: bool = False
) -> AssistantConversation | None:
    """The conversation, optionally locking it: turns of one conversation run one at a time."""
    query = select(AssistantConversation).where(
        AssistantConversation.company_id == scope.company_id,
        AssistantConversation.id == conversation_id,
    )
    if for_update:
        query = query.with_for_update()
    return scope.session.scalar(query)


def find_case_conversation(scope: CompanyScope, case_id: UUID) -> AssistantConversation | None:
    """The conversation a Case is attached to (at most one)."""
    return scope.session.scalar(
        select(AssistantConversation).where(
            AssistantConversation.company_id == scope.company_id,
            AssistantConversation.case_id == case_id,
        )
    )


def list_conversations(
    scope: CompanyScope, *, limit: int, before: tuple[datetime, UUID] | None = None
) -> Sequence[AssistantConversation]:
    """The Company's conversations, most recently active first; ``before`` is a keyset cursor."""
    query = select(AssistantConversation).where(
        AssistantConversation.company_id == scope.company_id
    )
    if before is not None:
        query = query.where(
            tuple_(AssistantConversation.updated_at, AssistantConversation.id) < tuple_(*before)
        )
    return scope.session.scalars(
        query.order_by(
            AssistantConversation.updated_at.desc(), AssistantConversation.id.desc()
        ).limit(limit)
    ).all()


def find_turn(scope: CompanyScope, turn_key: UUID) -> AssistantTurn | None:
    """The turn a request key already produced (idempotency, first turns included)."""
    return scope.session.scalar(
        select(AssistantTurn).where(
            AssistantTurn.company_id == scope.company_id, AssistantTurn.turn_key == turn_key
        )
    )


def record_turn(
    scope: CompanyScope,
    conversation: AssistantConversation,
    *,
    sequence: int,
    turn_key: UUID,
    user_id: UUID,
) -> AssistantTurn:
    """Append a turn. Raises IntegrityError for a reused key or a sequence already taken."""
    turn = AssistantTurn(
        company_id=scope.company_id,
        conversation_id=conversation.id,
        sequence=sequence,
        turn_key=turn_key,
        actor_user_id=user_id,
    )
    scope.session.add(turn)
    scope.session.flush()
    return turn


def record_message(
    scope: CompanyScope,
    turn: AssistantTurn,
    *,
    sequence: int,
    role: str,
    content: str,
    actor_user_id: UUID | None = None,
    safe_next_step: str | None = None,
    conversation_state: str | None = None,
    outcome: Mapping[str, Any] | None = None,
) -> AssistantMessage:
    """Append one visible message of a turn, exactly as shown."""
    message = AssistantMessage(
        company_id=scope.company_id,
        conversation_id=turn.conversation_id,
        turn_id=turn.id,
        sequence=sequence,
        role=role,
        actor_user_id=actor_user_id,
        content=content,
        safe_next_step=safe_next_step,
        conversation_state=conversation_state,
        outcome=None if outcome is None else dict(outcome),
    )
    scope.session.add(message)
    scope.session.flush()
    return message


def turn_messages(scope: CompanyScope, turn_id: UUID) -> list[AssistantMessage]:
    """A turn's messages in order (the founder's, then HeroOS's)."""
    return list(
        scope.session.scalars(
            select(AssistantMessage)
            .where(
                AssistantMessage.company_id == scope.company_id,
                AssistantMessage.turn_id == turn_id,
            )
            .order_by(AssistantMessage.sequence)
        ).all()
    )


def recent_messages(
    scope: CompanyScope, conversation_id: UUID, *, limit: int, before: int | None = None
) -> list[AssistantMessage]:
    """The newest ``limit`` messages (before sequence ``before``, if given), oldest first.

    Ordered by the stable message sequence: messages appended later never move
    an older page.
    """
    query = select(AssistantMessage).where(
        AssistantMessage.company_id == scope.company_id,
        AssistantMessage.conversation_id == conversation_id,
    )
    if before is not None:
        query = query.where(AssistantMessage.sequence < before)
    newest = scope.session.scalars(
        query.order_by(AssistantMessage.sequence.desc()).limit(limit)
    ).all()
    return list(reversed(newest))


def latest_message(
    scope: CompanyScope, conversation_id: UUID, role: str
) -> AssistantMessage | None:
    return scope.session.scalar(
        select(AssistantMessage)
        .where(
            AssistantMessage.company_id == scope.company_id,
            AssistantMessage.conversation_id == conversation_id,
            AssistantMessage.role == role,
        )
        .order_by(AssistantMessage.sequence.desc())
        .limit(1)
    )


def record_evaluation(
    scope: CompanyScope, turn: AssistantTurn, **fields: Any
) -> AssistantTurnEvaluation:
    """Append the deterministic evaluation of a turn (at most one per turn)."""
    row = AssistantTurnEvaluation(
        company_id=scope.company_id,
        conversation_id=turn.conversation_id,
        turn_id=turn.id,
        **fields,
    )
    scope.session.add(row)
    scope.session.flush()
    return row


def turn_evaluation(scope: CompanyScope, turn_id: UUID) -> AssistantTurnEvaluation | None:
    return scope.session.scalar(
        select(AssistantTurnEvaluation).where(
            AssistantTurnEvaluation.company_id == scope.company_id,
            AssistantTurnEvaluation.turn_id == turn_id,
        )
    )


def latest_evaluation(scope: CompanyScope, conversation_id: UUID) -> AssistantTurnEvaluation | None:
    """The evaluation of the conversation's latest turn."""
    return scope.session.scalar(
        select(AssistantTurnEvaluation)
        .join(
            AssistantTurn,
            (AssistantTurn.company_id == AssistantTurnEvaluation.company_id)
            & (AssistantTurn.id == AssistantTurnEvaluation.turn_id),
        )
        .where(
            AssistantTurnEvaluation.company_id == scope.company_id,
            AssistantTurnEvaluation.conversation_id == conversation_id,
        )
        .order_by(AssistantTurn.sequence.desc())
        .limit(1)
    )


def review_history(
    scope: CompanyScope, conversation_id: UUID
) -> list[tuple[Mapping[str, object], list[str]]]:
    """Every turn's evaluation record and withdrawn decisions, in order (to rebuild reviews)."""
    rows = scope.session.execute(
        select(AssistantTurnEvaluation.record, AssistantTurnEvaluation.withdrawn_actions)
        .join(
            AssistantTurn,
            (AssistantTurn.company_id == AssistantTurnEvaluation.company_id)
            & (AssistantTurn.id == AssistantTurnEvaluation.turn_id),
        )
        .where(
            AssistantTurnEvaluation.company_id == scope.company_id,
            AssistantTurnEvaluation.conversation_id == conversation_id,
        )
        .order_by(AssistantTurn.sequence)
    ).all()
    return [(record, list(withdrawn)) for record, withdrawn in rows]


def case_titles(scope: CompanyScope, case_ids: Sequence[UUID]) -> dict[UUID, str]:
    """The titles of the given Cases (one query for a page of conversations)."""
    if not case_ids:
        return {}
    rows = scope.session.execute(
        select(Case.id, Case.title).where(
            Case.company_id == scope.company_id, Case.id.in_(list(case_ids))
        )
    ).all()
    return {case_id: title for case_id, title in rows}
