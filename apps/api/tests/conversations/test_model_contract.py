"""The stored vocabularies and bounds are the domain's; D6 states the same rules as the models."""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import get_args

from app.api.assistant import MAX_MESSAGE_CHARS
from app.assistant.gateway.proposals import MAX_NEXT_STEP_CHARS as MODEL_NEXT_STEP_CHARS
from app.assistant.gateway.proposals import MAX_REPLY_CHARS
from app.assistant.gateway.service import ConversationState
from app.db.models import assistant
from app.db.models.workflow import (
    ASSISTANT_STEP_KEY,
    SUBMISSION_ORIGINS,
    WORKFLOW_KEYS,
    WorkflowSubmission,
)
from app.evaluation.model import Availability, Matter, Presentation
from app.evaluation.presentation import OutcomeKind

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "8860b86ef2ba_ask_heroos_conversations.py"
)


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("d6", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stored_vocabularies_are_the_domains() -> None:
    assert assistant.MESSAGE_ROLES == ("founder", "heroos")
    assert set(assistant.CONVERSATION_STATES) == set(get_args(ConversationState))
    assert set(assistant.OUTCOME_KINDS) == set(get_args(OutcomeKind))
    assert set(assistant.PRESENTATIONS) == set(get_args(Presentation))
    assert set(assistant.MATTERS) == set(get_args(Matter))
    assert set(assistant.AVAILABILITIES) == set(get_args(Availability))
    assert SUBMISSION_ORIGINS == ("structured", "assistant")


def test_stored_bounds_hold_what_the_founder_and_heroos_can_send() -> None:
    assert assistant.MAX_FOUNDER_CHARS == MAX_MESSAGE_CHARS
    # A model reply plus the server's own appended question; fallbacks are fixed text.
    assert assistant.MAX_HEROOS_CHARS >= 4 * MAX_REPLY_CHARS
    assert assistant.MAX_NEXT_STEP_CHARS >= 3 * MODEL_NEXT_STEP_CHARS


def test_the_migration_states_the_models_rules() -> None:
    d6 = _migration()
    assert (d6.revision, d6.down_revision) == ("8860b86ef2ba", "671bbbfc74ae")
    for name in (
        "MESSAGE_ROLES",
        "CONVERSATION_STATES",
        "OUTCOME_KINDS",
        "PRESENTATIONS",
        "MATTERS",
        "AVAILABILITIES",
        "MAX_TURNS",
        "MAX_TITLE",
        "MAX_FOUNDER_CHARS",
        "MAX_HEROOS_CHARS",
        "MAX_NEXT_STEP_CHARS",
        "MAX_OUTCOME_BYTES",
        "MAX_CHECKPOINT_BYTES",
        "MAX_EVALUATION_BYTES",
    ):
        assert getattr(d6, name) == getattr(assistant, name), name
    assert d6.WORKFLOW_KEYS == WORKFLOW_KEYS
    assert d6.SUBMISSION_ORIGINS == SUBMISSION_ORIGINS
    assert d6.ASSISTANT_STEP_KEY == ASSISTANT_STEP_KEY
    assert d6.MESSAGE_SHAPE == assistant.MESSAGE_SHAPE
    # The API role may change a conversation's own state, and nothing else of it.
    assert set(d6.CONVERSATION_UPDATES) == {
        "case_id",
        "workflow_key",
        "title",
        "revision",
        "checkpoint",
        "updated_at",
    }
    assert set(d6.CONVERSATION_UPDATES) < {
        c.name for c in assistant.AssistantConversation.__table__.columns
    }


def test_every_existing_submission_is_structured() -> None:
    origin = WorkflowSubmission.__table__.columns["origin"]
    assert origin.server_default is not None
    assert str(origin.server_default.arg) == "structured"
    assert WorkflowSubmission.__table__.columns["source_message_id"].nullable
