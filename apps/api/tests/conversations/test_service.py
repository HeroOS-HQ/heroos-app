"""M2-NEW-07 Part 1: persisted Ask HeroOS turns, through the real gateway (SQLite stand-ins).

- the first completed turn creates the conversation; a provider failure stores nothing;
- a retried turn key replays the committed turn, never a second conversation or Case;
  the same key for another request is a conflict;
- chat-first Case: the first completed turn starts the conversation's one Case (a bare
  "New case" below the workflow threshold); a workflow attaches to that same Case only at
  the threshold (supported HR, an established workflow with a definition, one matter),
  with a safe title and no CaseSubject; the founder's message that established the matter
  (never a bare answer) becomes its narrative;
- only canonical ENGINE_TRUSTED facts reach the Case, through the shared pipeline, with
  their founder message as provenance; nothing is repeated; corrections append;
- no turn selects a pathway, moves a stage or records a decision;
- each turn's evaluation is its own record, separate from ``workflow_evaluations``;
- nothing of the provider exchange is stored beyond what the founder saw;
- the conversation belongs to the Company: another administrator continues it; another
  Company can't see it; a turn that completed meanwhile, or a role that ended, writes nothing.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.assistant.gateway.prompts import RESPONSE_INSTRUCTION, UNDERSTANDING_INSTRUCTION
from app.assistant.gateway.service import GatewayFailure, snapshot_versions
from app.assistant.provider import AssistantError
from app.auth.exceptions import AuthorizationError
from app.auth.models import AuthenticatedCompanyContext
from app.conversations.bridge import NARRATIVE_KEY, NEW_CASE_TITLE
from app.conversations.checkpoint import decode
from app.conversations.service import (
    AskConversations,
    ConversationConflict,
    ConversationNotFound,
    InvalidMessage,
    TurnRequest,
    case_request_key,
)
from app.db.models import (
    AssistantConversation,
    AssistantMessage,
    AssistantTurn,
    AssistantTurnEvaluation,
    Case,
    CaseFact,
    Membership,
    WorkflowEvaluation,
    WorkflowInstance,
    WorkflowProgressEvent,
    WorkflowSubmission,
)
from app.evaluation.facts import Asked
from app.evaluation.model import EVALUATION_SCHEMA
from app.workflows.progress import FactRecord, latest_answers
from tests.auth.conftest import SeedData
from tests.auth.test_workflow_api import (  # noqa: F401  (pytest fixtures)
    admin_alice,
    alice,
    client,
)
from tests.conversations.conftest import (
    ASSISTANT_TABLES,
    SAFE,
    SAFE_ASKING_POLICY,
    Founder,
    add_admin,
    counts,
    gateway,
)
from tests.evaluation.test_golden import understood
from tests.fixtures.evaluation import PROBATION, Artifacts, rule_bundle
from tests.fixtures.gateway import ScriptedProvider, fact, response, understanding

LATE = "My employee has been late three times this month. What should I do?"
POLICY = "employee_aware_of_relevant_policy"
POLICY_QUESTION = "context.policy_awareness"


def late(message: str = LATE, **kwargs: Any) -> dict[str, Any]:
    return understood(message, pathway="less_serious", topics=["workplace_reminder"], **kwargs)


def rows(db: sessionmaker[Session], model: Any, **where: Any) -> list[Any]:
    with db() as session:
        query = select(model)
        for column, value in where.items():
            query = query.where(getattr(model, column) == value)
        found = list(session.scalars(query).all())
        session.expunge_all()
        return found


def case_answers(db: sessionmaker[Session], case_id: uuid.UUID) -> dict[str, object]:
    with db() as session:
        found = session.execute(
            select(WorkflowSubmission.revision, CaseFact.fact_key, CaseFact.value)
            .join(WorkflowSubmission, WorkflowSubmission.id == CaseFact.submission_id)
            .join(WorkflowInstance, WorkflowInstance.id == CaseFact.instance_id)
            .where(WorkflowInstance.case_id == case_id)
        ).all()
    return latest_answers(FactRecord(r, k, v) for r, k, v in found)


def today_title() -> str:
    today = datetime.now(UTC).date()
    return f"Disciplinary case · {today.day} {today:%b}"


# --- creation and failure --------------------------------------------------------------------


def test_the_first_completed_turn_creates_the_conversation_and_its_case(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    result = founder.say(LATE, late())

    (conversation,) = rows(db, AssistantConversation)
    assert conversation.id == result.conversation_id
    assert conversation.company_id == alice_context.company_id
    assert conversation.created_by_user_id == alice_context.user_id
    assert (conversation.revision, conversation.workflow_key) == (1, "disciplinary")
    assert conversation.case_id == result.case_id is not None
    (turn,) = rows(db, AssistantTurn)
    assert (turn.sequence, turn.actor_user_id) == (1, alice_context.user_id)
    messages = rows(db, AssistantMessage)
    assert [(m.sequence, m.role, m.actor_user_id) for m in messages] == [
        (1, "founder", alice_context.user_id),
        (2, "heroos", None),
    ]
    # Exactly what was shown.
    assert messages[0].content == LATE
    assert messages[1].content == SAFE_ASKING_POLICY == result.heroos.content
    assert messages[1].conversation_state == "responded"
    assert messages[1].outcome is not None and messages[1].outcome["kind"] == "guidance"
    assert set(messages[1].outcome) == {"kind", "title", "message", "items"}
    # The Case, created through the existing path and keyed by the conversation.
    (case,) = rows(db, Case)
    (instance,) = rows(db, WorkflowInstance)
    assert case.id == result.case_id and case.case_type == "disciplinary"
    assert case.title == conversation.title == today_title()
    assert case.subject_id is None
    assert instance.request_key == case_request_key(conversation.id)
    assert instance.created_by_user_id == alice_context.user_id
    # The founder's establishing words are the Case's narrative: its one fact so far.
    assert instance.revision == 1
    assert case_answers(db, case.id) == {NARRATIVE_KEY: LATE}
    # What HeroOS asked is what the next turn starts from.
    checkpoint = decode(conversation.checkpoint)
    assert checkpoint is not None
    assert checkpoint.versions == snapshot_versions(artifacts.snapshot())
    assert checkpoint.state.asked == (Asked("fact", POLICY),)
    assert checkpoint.state.workflow == "disciplinary"


def test_a_provider_failure_writes_nothing(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    empty = counts(db)
    with pytest.raises(GatewayFailure):
        founder.say(LATE, AssistantError("unavailable"))
    assert counts(db) == empty  # no empty conversation, no Case
    founder.say(LATE, late())
    before = counts(db)
    with pytest.raises(GatewayFailure):
        founder.say("Yes.", AssistantError("timeout"))
    assert counts(db) == before
    (conversation,) = rows(db, AssistantConversation)
    assert conversation.revision == 1


@pytest.mark.parametrize("message", ["", "   ", "x" * 2001, "bad\x00byte", "c1\x85control"])
def test_a_message_heroos_wont_store_is_refused_before_anything(
    db: sessionmaker[Session],
    artifacts: Artifacts,
    alice_context: AuthenticatedCompanyContext,
    message: str,
) -> None:
    founder = Founder(db, artifacts, alice_context)
    with pytest.raises(InvalidMessage):
        founder.say(message, late())
    assert founder.provider is not None and founder.provider.calls == []
    assert set(counts(db).values()) == {0}


# --- idempotency -------------------------------------------------------------------------------


def test_a_retried_first_turn_replays_and_never_creates_a_second_conversation(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    key = uuid.uuid4()
    first = founder.say(LATE, late(), turn_key=key, conversation_id=None)
    stored = counts(db)
    # The response was lost: the browser sends the same request again (still no conversation).
    again = founder.say(LATE, AssistantError("unavailable"), turn_key=key, conversation_id=None)
    assert founder.provider is not None and founder.provider.calls == []  # no provider request
    assert again.replayed and not first.replayed
    assert (again.conversation_id, again.turn_id, again.case_id) == (
        first.conversation_id,
        first.turn_id,
        first.case_id,
    )
    assert again.heroos == first.heroos and again.founder == first.founder
    assert counts(db) == stored
    # Also once the browser knows the conversation it created.
    known = founder.say(LATE, AssistantError("unavailable"), turn_key=key, revision=0)
    assert known.replayed and known.turn_id == first.turn_id


def test_a_reused_turn_key_for_another_request_is_a_conflict(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    key = uuid.uuid4()
    founder.say(LATE, late(), turn_key=key, conversation_id=None)
    other = Founder(db, artifacts, alice_context)
    other.say("He was late again today.", late("He was late again today."))
    stored = counts(db)
    with pytest.raises(ConversationConflict):
        founder.say("Something else.", late(), turn_key=key, conversation_id=None)
    with pytest.raises(ConversationConflict):
        founder.say(LATE, late(), turn_key=key, conversation_id=other.conversation_id)
    colleague = Founder(db, artifacts, add_admin(db, alice_context.company_id))
    with pytest.raises(ConversationConflict):
        colleague.say(LATE, late(), turn_key=key, conversation_id=None)
    assert counts(db) == stored


def test_another_turn_that_completed_meanwhile_is_a_conflict(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    founder.say(LATE, late())
    other_tab = Founder(db, artifacts, alice_context)
    other_tab.conversation_id, other_tab.revision = founder.conversation_id, founder.revision

    class Interleaved:
        """The other tab's turn commits while this turn waits on the provider."""

        def respond(self, company: Any, turn: Any) -> Any:
            other_tab.say("He was late again today.", late("He was late again today.", turn=1))
            provider = ScriptedProvider(late("Yes.", turn=1), response(SAFE, ["q1"]))
            return gateway(founder.evaluation, provider).respond(company, turn)

    service = AskConversations(Interleaved(), policy="disabled", rules=None)  # type: ignore[arg-type]
    request = TurnRequest("Yes.", uuid.uuid4(), founder.conversation_id, founder.revision)
    with db() as session, pytest.raises(ConversationConflict):
        service.run_turn(session, alice_context, request)
    (conversation,) = rows(db, AssistantConversation)
    assert conversation.revision == 2  # the first turn and the other tab's: nothing of this one
    assert len(rows(db, AssistantTurn)) == 2
    # Only the first turn's narrative: nothing of the turn that lost.
    assert [s.revision for s in rows(db, WorkflowSubmission)] == [1]


def test_a_role_that_ended_while_the_provider_answered_writes_nothing(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)

    class Demoting:
        def respond(self, company: Any, turn: Any) -> Any:
            with db() as session:
                session.execute(
                    update(Membership)
                    .where(Membership.id == alice_context.membership_id)
                    .values(role="member")
                )
                session.commit()
            provider = ScriptedProvider(late(), response(SAFE, ["q1"]))
            return gateway(founder.evaluation, provider).respond(company, turn)

    service = AskConversations(Demoting(), policy="disabled", rules=None)  # type: ignore[arg-type]
    with db() as session, pytest.raises(AuthorizationError):
        service.run_turn(session, alice_context, TurnRequest(LATE, uuid.uuid4()))
    assert set(counts(db).values()) == {0}


# --- ownership ---------------------------------------------------------------------------------


def test_another_administrator_continues_the_companys_conversation(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    first = founder.say(LATE, late())
    colleague = Founder(db, artifacts, add_admin(db, alice_context.company_id))
    colleague.conversation_id, colleague.revision = founder.conversation_id, founder.revision
    second = colleague.say("Yes.", late("Yes.", turn=1))
    assert (second.conversation_id, second.case_id, second.sequence) == (
        first.conversation_id,
        first.case_id,
        2,
    )
    turns = rows(db, AssistantTurn)
    assert [t.actor_user_id for t in turns] == [alice_context.user_id, colleague.context.user_id]
    (conversation,) = rows(db, AssistantConversation)
    assert conversation.created_by_user_id == alice_context.user_id
    # The colleague's direct answer to the question HeroOS asked alice is trusted.
    assert case_answers(db, first.case_id) == {  # type: ignore[arg-type]
        NARRATIVE_KEY: LATE,
        POLICY_QUESTION: "yes",
    }


def test_another_companys_conversation_is_not_found(
    db: sessionmaker[Session],
    artifacts: Artifacts,
    alice_context: AuthenticatedCompanyContext,
    seed: SeedData,
) -> None:
    founder = Founder(db, artifacts, alice_context)
    founder.say(LATE, late())
    stored = counts(db)
    with db() as session:
        bob_membership = session.scalar(select(Membership.id).where(Membership.user_id == seed.bob))
    bob = AuthenticatedCompanyContext(
        user_id=seed.bob, company_id=seed.company_b, membership_id=bob_membership, identity_id=None
    )
    intruder = Founder(db, artifacts, bob)
    with pytest.raises(ConversationNotFound):
        intruder.say("Yes.", late("Yes."), conversation_id=founder.conversation_id)
    with pytest.raises(ConversationNotFound):
        founder.say("Yes.", late("Yes."), conversation_id=uuid.uuid4())
    assert counts(db) == stored


# --- the Case and the workflow threshold -------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "proposal", "matter"),
    [
        ("I need help with an employee.", understanding(intent="unclear"), "unclear"),
        (
            "Help me plan staffing strategy for 2027.",
            understanding(intent="other_hr"),
            "unsupported_hr",
        ),
        ("Help debug JavaScript.", understanding(intent="unsupported"), "outside_product_scope"),
        (
            "I need to discipline one employee and hire a replacement.",
            understood(
                "I need to discipline one employee and hire a replacement.",
                topics=["workplace_reminder"],
                uncertainties=["multiple_matters"],
            ),
            "supported",
        ),
        (
            "Her trial ends soon and I want to end her employment.",
            understood(
                "Her trial ends soon and I want to end her employment.",
                workflow=PROBATION,
                topics=["trial_end"],
            ),
            "supported",
        ),
    ],
    ids=["unclear", "other_hr", "not_hr", "several_matters", "no_workflow_definition"],
)
def test_a_conversation_below_the_threshold_gets_a_bare_case_and_no_workflow(
    db: sessionmaker[Session],
    artifacts: Artifacts,
    alice_context: AuthenticatedCompanyContext,
    message: str,
    proposal: dict[str, Any],
    matter: str,
) -> None:
    result = Founder(db, artifacts, alice_context).say(message, proposal)
    (conversation,) = rows(db, AssistantConversation)
    (case,) = rows(db, Case)
    assert result.case_id == conversation.case_id == case.id is not None
    assert (case.case_type, case.title, case.subject_id) == ("unclassified", NEW_CASE_TITLE, None)
    assert (conversation.workflow_key, conversation.title) == (None, NEW_CASE_TITLE)
    # No workflow, so nothing of the founder's words is a Case fact.
    assert rows(db, WorkflowInstance) == [] and rows(db, WorkflowSubmission) == []
    (evaluation,) = rows(db, AssistantTurnEvaluation)
    assert evaluation.matter == matter


def test_a_supported_matter_attaches_its_workflow_to_the_conversations_one_case(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    opening = founder.say(
        "I need help with an employee.", understanding(intent="unclear", workflow=None)
    )
    assert opening.case_id is not None
    absent = "One employee hasn't come in for four days."
    attached = founder.say(absent, understood(absent, topics=["workplace_reminder"], turn=1))
    assert attached.case_id == opening.case_id
    later = "He was late again today."
    again = founder.say(later, understood(later, topics=["workplace_reminder"], turn=2))
    assert again.case_id == attached.case_id
    (case,) = rows(db, Case)
    (instance,) = rows(db, WorkflowInstance)
    assert (case.case_type, instance.case_id) == ("disciplinary", case.id)
    (conversation,) = rows(db, AssistantConversation)
    assert (conversation.case_id, conversation.revision) == (attached.case_id, 3)
    # The message that established the matter is its narrative, not the opening one.
    assert case_answers(db, case.id) == {NARRATIVE_KEY: absent}


def test_a_case_title_never_names_a_person_or_a_sanction(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    message = "I think Ahmed Khan took money from the till. Can I fire him today?"
    proposal = understood(
        message,
        pathway="serious",
        topics=["dismissal_without_notice"],
        actions=[("opt-dismissal", "fire him today")],
        summary="[SYNTHETIC] Ahmed Khan may have taken money",
    )
    result = Founder(db, artifacts, alice_context).say(message, proposal)
    (case,) = rows(db, Case)
    assert case.id == result.case_id
    assert case.title == today_title()
    # A CaseSubject is never created or linked from a name in free text.
    assert case.subject_id is None
    with db() as session:
        assert session.scalar(text("SELECT count(*) FROM case_subjects")) == 0


def test_a_matter_topic_gives_a_neutral_title(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    message = "A team member keeps ignoring the dress code."
    Founder(db, artifacts, alice_context).say(
        message, understood(message, topics=["misconduct_level", "workplace_reminder"])
    )
    (case,) = rows(db, Case)
    assert case.title == "Conduct concern"


# --- facts --------------------------------------------------------------------------------------


def test_a_direct_answer_reaches_the_case_through_the_shared_pipeline(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    first = founder.say(LATE, late())
    answer = founder.say("Yes.", late("Yes.", turn=1))
    assert first.case_id is not None and answer.case_id == first.case_id
    assert case_answers(db, first.case_id) == {NARRATIVE_KEY: LATE, POLICY_QUESTION: "yes"}
    narrative, submission = rows(db, WorkflowSubmission)
    assert narrative.source_message_id == first.founder.id and narrative.revision == 1
    assert submission.origin == "assistant"
    assert submission.step_key == "ask_heroos"
    # Provenance: a reference to the founder message that established it (no copy of its words).
    assert submission.source_message_id == answer.founder.id
    assert submission.submitted_by_user_id == alice_context.user_id
    assert submission.revision == 2
    (instance,) = rows(db, WorkflowInstance)
    assert instance.revision == 2
    # The same side effects as a form save: the intake evaluation trace of each submission.
    traces = rows(db, WorkflowEvaluation)
    assert [t.submission_id for t in traces] == [narrative.id, submission.id]
    # The Case now holds the fact: the checkpoint doesn't keep a second copy.
    (conversation,) = rows(db, AssistantConversation)
    checkpoint = decode(conversation.checkpoint)
    assert checkpoint is not None and POLICY not in checkpoint.state.engine
    assert checkpoint.case_revision == 2

    # A later turn starts from the Case's fact and stores nothing again.
    founder.say("What should I do next?", late("What should I do next?", turn=2))
    assert len(rows(db, WorkflowSubmission)) == 2
    record = rows(db, AssistantTurnEvaluation)[-1].record
    assert record["facts"]["engine_trusted"][POLICY] == "yes"
    assert record["facts"]["sources"][POLICY] == "continuation"


def test_facts_before_the_workflow_attaches_are_saved_when_it_does(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    # Several matters at first: a bare Case and no workflow, but HeroOS asks about the standard.
    message = "I need to discipline one employee and hire a replacement."
    opening = founder.say(
        message,
        understood(message, topics=["workplace_reminder"], uncertainties=["multiple_matters"]),
    )
    assert opening.case_id is not None and rows(db, WorkflowInstance) == []
    conversation = rows(db, AssistantConversation)[0]
    checkpoint = decode(conversation.checkpoint)
    assert checkpoint is not None and checkpoint.state.asked == (Asked("fact", POLICY),)
    # One matter, and a direct answer: the workflow attaches to the same Case with that fact.
    result = founder.say("Yes.", late("Yes.", turn=1))
    assert result.case_id == opening.case_id
    # "Yes." answered HeroOS's question: never the founder's account of what happened.
    assert case_answers(db, result.case_id) == {POLICY_QUESTION: "yes"}
    (submission,) = rows(db, WorkflowSubmission)
    assert submission.source_message_id == result.founder.id


def test_a_reply_to_heroos_question_never_becomes_the_narrative(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    """Found live: the workflow attached on the founder's hedged reply to HeroOS's question
    ("possibly, not sure"), which was saved as "What happened?"."""
    founder = Founder(db, artifacts, alice_context)
    message = "I need to discipline one employee and hire a replacement."
    founder.say(
        message,
        understood(message, topics=["workplace_reminder"], uncertainties=["multiple_matters"]),
    )
    (conversation,) = rows(db, AssistantConversation)
    asked = decode(conversation.checkpoint)
    assert asked is not None and asked.state.asked == (Asked("fact", POLICY),)
    reply = "possibly, not sure"
    result = founder.say(reply, late(reply, turn=1))
    assert result.case_id is not None and rows(db, WorkflowInstance) != []
    assert NARRATIVE_KEY not in case_answers(db, result.case_id)


@pytest.mark.parametrize(
    "stated",
    [
        # Clearly said, but only the AI's reading: conversational, never a Case fact.
        fact(POLICY, "yes", "I explained the attendance standard to him"),
        # Hedged: proposed.
        fact(POLICY, "yes", "I sort of explained the attendance standard", basis="inferred"),
    ],
    ids=["conversational", "proposed"],
)
def test_an_ai_reading_never_becomes_a_case_fact(
    db: sessionmaker[Session],
    artifacts: Artifacts,
    alice_context: AuthenticatedCompanyContext,
    stated: dict[str, Any],
) -> None:
    message = (
        "He's late a lot. I explained the attendance standard to him last month. "
        "I sort of explained the attendance standard."
    )
    result = Founder(db, artifacts, alice_context).say(message, late(message, facts=[stated]))
    assert result.case_id is not None
    # The founder's own words are the narrative; the AI's reading of them is no Case fact.
    assert case_answers(db, result.case_id) == {NARRATIVE_KEY: message}


def test_what_was_noted_stays_said_on_later_turns_and_is_never_asked_again(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    """Found live: a reading noted on one turn, which the next understanding didn't re-propose,
    was dropped from the noted list and asked for again."""
    founder = Founder(db, artifacts, alice_context)
    message = "He's late a lot. I explained the attendance standard to him last month."
    said = fact(POLICY, "yes", "I explained the attendance standard to him")
    founder.say(message, late(message, facts=[said]))
    (conversation,) = rows(db, AssistantConversation)
    noted = decode(conversation.checkpoint)
    assert noted is not None and noted.noted == {POLICY_QUESTION: "yes"}
    assert Asked("fact", POLICY) not in noted.state.asked

    # The next understanding doesn't mention it: still said (and noted), not asked, not trusted.
    later = founder.say("What should I do next?", late("What should I do next?", turn=1))
    assert later.case_id is not None
    (conversation,) = rows(db, AssistantConversation)
    checkpoint = decode(conversation.checkpoint)
    assert checkpoint is not None and checkpoint.noted == {POLICY_QUESTION: "yes"}
    assert Asked("fact", POLICY) not in checkpoint.state.asked
    record = rows(db, AssistantTurnEvaluation)[-1].record
    assert POLICY in record["facts"]["established_conversational"]
    assert POLICY not in record["facts"]["engine_trusted"]
    assert case_answers(db, later.case_id) == {NARRATIVE_KEY: message}


def test_a_question_the_founder_didnt_answer_is_not_asked_again_at_once(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    """Found live: the server re-appended the same question turn after turn while the founder
    talked about something else. HeroOS answers them first and may come back to it later."""
    founder = Founder(db, artifacts, alice_context)
    assert founder.say(LATE, late()).heroos.content == SAFE_ASKING_POLICY
    other = "Can he be suspended while I sort this out?"
    assert founder.say(other, late(other, turn=1), response(SAFE, [])).heroos.content == SAFE
    again = "And what about his contract?"
    # Asked again, it says it is still needed (never the same words again).
    assert founder.say(again, late(again, turn=2)).heroos.content == (
        f"{SAFE} One thing I still need to know: had the employee been told what was expected "
        "of them?"
    )


def test_a_contradiction_never_changes_the_case_and_corrections_append(
    db: sessionmaker[Session],
    artifacts: Artifacts,
    alice_context: AuthenticatedCompanyContext,
    client: TestClient,  # noqa: F811
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    founder = Founder(db, artifacts, alice_context)
    first = founder.say(LATE, late())
    founder.say("No.", late("No.", turn=1))
    assert first.case_id is not None
    assert case_answers(db, first.case_id) == {NARRATIVE_KEY: LATE, POLICY_QUESTION: "no"}

    # The founder now says otherwise: the AI's reading changes nothing in the Case, and the
    # Case's "no" stays out of the evaluation until a value is confirmed (voided).
    said = "Sorry, I did explain the attendance standard to him."
    founder.say(said, late(said, facts=[fact(POLICY, "yes", said[7:], turn=2)]))
    assert case_answers(db, first.case_id) == {NARRATIVE_KEY: LATE, POLICY_QUESTION: "no"}
    assert len(rows(db, CaseFact)) == 2
    checkpoint = decode(rows(db, AssistantConversation)[0].checkpoint)
    assert checkpoint is not None and checkpoint.voided == (POLICY,)
    founder.say("Anything else?", late("Anything else?", turn=3))
    record = rows(db, AssistantTurnEvaluation)[-1].record
    assert POLICY not in record["facts"]["engine_trusted"]

    # A correction through the step's form appends; the old fact stays; the latest wins.
    (instance,) = rows(db, WorkflowInstance)
    saved = client.put(
        f"/companies/{alice_context.company_id}/cases/{first.case_id}"
        "/workflow/steps/incident_context/answers",
        headers=admin_alice,
        json={
            "expected_revision": instance.revision,
            "submission_key": str(uuid.uuid4()),
            "answers": {POLICY_QUESTION: "yes"},
        },
    )
    assert saved.status_code == 200, saved.text
    assert [f.value for f in rows(db, CaseFact)] == [LATE, "no", "yes"]
    assert case_answers(db, first.case_id) == {NARRATIVE_KEY: LATE, POLICY_QUESTION: "yes"}
    assert [s.origin for s in rows(db, WorkflowSubmission)] == [
        "assistant",
        "assistant",
        "structured",
    ]
    # The newer Case fact is trusted again from the next turn on.
    founder.say("Thanks.", late("Thanks.", turn=4))
    record = rows(db, AssistantTurnEvaluation)[-1].record
    assert record["facts"]["engine_trusted"][POLICY] == "yes"


def test_an_answer_taken_back_is_voided_and_the_case_keeps_its_record(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    """Final blocker pass: an answer the Case holds, taken back with nothing in its place ("sorry,
    that was another employee"), stays out of the evaluation from then on (voided). The AI's
    reading never changes the Case: its append-only record keeps the answer until the employer
    records a newer one."""
    founder = Founder(db, artifacts, alice_context)
    first = founder.say(LATE, late())
    founder.say("No.", late("No.", turn=1))
    assert first.case_id is not None
    assert case_answers(db, first.case_id)[POLICY_QUESTION] == "no"
    back = "Sorry, that answer was about another employee."
    data = late(back, turn=2)
    data["withdrawn_facts"] = [
        {"fact_key": POLICY, "source_turn": 2, "support_excerpt": "about another employee"}
    ]
    founder.say(back, data)
    assert case_answers(db, first.case_id)[POLICY_QUESTION] == "no"
    checkpoint = decode(rows(db, AssistantConversation)[0].checkpoint)
    assert checkpoint is not None and checkpoint.voided == (POLICY,)
    founder.say("What now?", late("What now?", turn=3))
    record = rows(db, AssistantTurnEvaluation)[-1].record
    assert POLICY not in record["facts"]["engine_trusted"]


def test_no_turn_selects_a_pathway_moves_a_stage_or_records_a_decision(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context, rules=rule_bundle(artifacts.disciplinary))
    message = "I think she took money from the till. Can I fire her today?"
    founder.say(
        message,
        understood(
            message,
            pathway="serious",
            topics=["dismissal_without_notice"],
            actions=[("opt-dismissal", "fire her today")],
        ),
    )
    founder.say("Yes, I want to dismiss her.", late("Yes, I want to dismiss her.", turn=1))
    founder.say("Yes.", late("Yes.", turn=2))
    kinds = [e.kind for e in rows(db, WorkflowProgressEvent)]
    assert not {"pathway_selected", "stage_started", "stage_completed"} & set(kinds)
    assert counts(db)["workflow_decision_records"] == 0


# --- what is stored ---------------------------------------------------------------------------


def test_each_turn_keeps_its_own_evaluation_record(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    founder.say(LATE, late())
    assert len(rows(db, AssistantTurnEvaluation)) == 1
    assert len(rows(db, WorkflowEvaluation)) == 1  # the narrative's intake trace only
    founder.say("Yes.", late("Yes.", turn=1))
    evaluations = rows(db, AssistantTurnEvaluation)
    turns = rows(db, AssistantTurn)
    assert [e.turn_id for e in evaluations] == [t.id for t in turns]
    for row in evaluations:
        record = row.record
        assert record["schema"] == row.evaluation_schema == EVALUATION_SCHEMA
        assert (row.availability, row.matter, row.workflow_key, row.presentation) == (
            record["availability"],
            record["matter"],
            record["workflow"],
            record["presentation"],
        )
        assert row.outcome == "guidance" and row.has_review_requirement is False
        assert row.snapshot_id == artifacts.snapshot().id
        assert row.profile_digest is not None and len(row.profile_digest) == 64
        assert row.knowledge_runtime_digest is not None
    # Each submission's intake trace is the structured one, not the conversation record.
    traces = rows(db, WorkflowEvaluation)
    assert len(traces) == 2 and all("schema" not in t.results[0] for t in traces)


def test_nothing_of_the_provider_exchange_is_stored_beyond_what_was_shown(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    message = "He's late a lot. I explained the attendance standard to him last month."
    proposal = late(
        message,
        facts=[fact(POLICY, "yes", "I explained the attendance standard to him")],
        summary="[SYNTHETIC] SUMMARY-MARKER-7f3a late employee",
    )
    founder.say(message, proposal, response("Visible reply only."))
    founder.say("Thanks.", late("Thanks.", turn=1), response("Second visible reply."))
    stored = []
    with db() as session:
        for model in (*ASSISTANT_TABLES, Case, WorkflowSubmission, CaseFact):
            for row in session.scalars(select(model)).all():
                stored.append(
                    json.dumps(
                        {c.name: getattr(row, c.name) for c in model.__table__.columns},
                        default=str,
                    )
                )
    everything = "\n".join(stored)
    for private in (
        "SUMMARY-MARKER-7f3a",
        "fact_proposals",
        "support_excerpt",
        "schema_version",
        "workflow_candidate",
        "question_target_ids",
        "case_summary",
        UNDERSTANDING_INSTRUCTION[:60],
        RESPONSE_INSTRUCTION[:60],
        "fake-model",
        "TEST-APPROVAL-1",
        "approved_knowledge",
        "prompt_tokens",
    ):
        assert private not in everything, private
    # The founder's words are stored as their message and, as written, as the Case's
    # narrative (chat-first Case); never the AI's summary or reading of them.
    assert everything.count("I explained the attendance standard to him last month") == 2
    assert "Visible reply only." in everything and "Second visible reply." in everything


def test_history_comes_from_the_stored_conversation(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    founder.say(LATE, late())
    founder.say("Yes.", late("Yes.", turn=1))
    assert founder.provider is not None
    sent = founder.provider.phase("understanding")[0].data["founder_messages"]
    assert [m["text"] for m in sent] == [LATE, "Yes."]
    conversation = founder.provider.phase("response")[0].data["conversation"]
    assert conversation == [
        {"from": "founder", "text": LATE},
        {"from": "heroos", "text": SAFE_ASKING_POLICY},
    ]


def test_an_untrusted_checkpoint_is_rebuilt_from_the_case_and_reconfirmed(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    founder.say(LATE, late())
    founder.say("Yes.", late("Yes.", turn=1))
    with db() as session:
        session.execute(
            update(AssistantConversation).values(checkpoint={"schema": "tampered", "engine": {}})
        )
        session.commit()
    founder.say("What next?", late("What next?", turn=2))
    (conversation,) = rows(db, AssistantConversation)
    checkpoint = decode(conversation.checkpoint)
    assert checkpoint is not None and checkpoint.state.reconfirm
    # The Case's fact is the record: rebuilt, never lost.
    record = rows(db, AssistantTurnEvaluation)[-1].record
    assert record["facts"]["engine_trusted"][POLICY] == "yes"
