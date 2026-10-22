"""M2-NEW-07: commit-time reconciliation, runtime changes and separate matters.

While the model answers, nothing is locked; the Case can change (a form save)
before the turn is recorded. At commit the deterministic evaluation runs again
on the Case as it is then, with no model request, and the freshest
authoritative result is the one recorded:

- the same result keeps the model's words;
- a stricter result replaces them with the server's fixed text for that result;
- a weaker result on authoritative state (a prerequisite another administrator
  recorded) replaces the stale stricter reply with the fixed text for the
  current result;
- a weaker result only because something became less certain (a trusted fact
  now "Not sure", the jurisdiction no longer resolved, trust lost) never
  relaxes: the stricter reply stands and the next turn starts from the current
  state, re-confirming what was lost.

Also: a new execution profile or rule bundle never carries trusted state over
(rebuilt and re-confirmed, the Case's facts re-validated), a historical value the
current runtime doesn't accept stays history and is never used, and a separate
matter introduced in a Case's conversation never writes into that Case.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.assistant.gateway.service import FALLBACK_LEADS, AiGateway, _Turn, uncertainty
from app.auth.models import AuthenticatedCompanyContext
from app.cases.mutation import FormOrigin, apply_case_fact_changes, evaluate_case
from app.conversations.bridge import NARRATIVE_KEY
from app.conversations.checkpoint import decode
from app.conversations.service import AskConversations, TurnRequest
from app.db.models import (
    AssistantConversation,
    AssistantMessage,
    AssistantTurnEvaluation,
    CaseFact,
)
from app.evaluation.facts import PriorState
from app.evaluation.model import (
    ActionEvaluation,
    ConditionEvaluation,
    ConversationEvaluation,
    TrustedFactState,
)
from app.repositories import workflows
from app.tenancy.scope import open_company_scope
from app.workflows.definition import CASE_JURISDICTION_KEY
from tests.conversations.conftest import SAFE, Founder, add_admin, gateway
from tests.conversations.test_http import move_to_difc
from tests.evaluation.test_golden import understood
from tests.fixtures.evaluation import Artifacts
from tests.fixtures.gateway import ScriptedProvider, response

LATE = "My employee has been late three times this month. What should I do?"
POLICY = "employee_aware_of_relevant_policy"
QUESTION = "context.policy_awareness"
NEXT = "What should I do next?"
WARN = "Can I give him a written warning?"
FIRE = "Can I dismiss him without notice?"


def late(message: str = LATE, turn: int = 0, **kwargs: Any) -> dict[str, Any]:
    return understood(
        message, pathway="less_serious", topics=["workplace_reminder"], turn=turn, **kwargs
    )


def warn(message: str = WARN, turn: int = 0) -> dict[str, Any]:
    return late(message, turn, actions=[("opt-warning", "a written warning")])


def fire(message: str = FIRE, turn: int = 0) -> dict[str, Any]:
    return understood(
        message,
        pathway="serious",
        topics=["dismissal_without_notice"],
        actions=[("opt-dismissal", "dismiss him without notice")],
        turn=turn,
    )


def policy_prerequisite(artifacts: Artifacts) -> None:
    """The fictional written warning requires the Case-backed "standard explained" fact."""
    federal = artifacts.disciplinary["conversation"]["jurisdictions"]["uae_federal"]
    required = {"answer": QUESTION, "in": ["yes"]}
    for action in federal["actions"]:
        if action["action"] == "opt-warning":
            action["rules"][0]["require"] = required
    for rule in federal["rules"]:
        if rule["key"] == "heard_before_warning":
            rule["require"] = required
    artifacts.repin()


def form_save(
    db: sessionmaker[Session],
    context: AuthenticatedCompanyContext,
    case_id: uuid.UUID,
    answers: dict[str, object],
    step: str = "incident_context",
) -> None:
    """The employer's form save (the structured path), committed."""
    with db() as session:
        scope = open_company_scope(session, context)
        item = workflows.get_workflow_case(scope, case_id, for_update=True)
        assert item is not None
        state = evaluate_case(scope, item, "disabled", None)
        applied = apply_case_fact_changes(
            scope,
            item,
            state,
            origin=FormOrigin(step),
            changes=answers,
            expected_revision=item.instance.revision,
            idempotency_key=uuid.uuid4(),
            user_id=context.user_id,
            policy="disabled",
            bundle=None,
        )
        assert applied is not None
        scope.commit()


class During:
    """The real gateway; ``action`` runs while its model request is in flight."""

    def __init__(self, inner: AiGateway, action: Callable[[], None]) -> None:
        self._inner, self._action = inner, action

    def respond(self, company: Any, turn: Any) -> Any:
        reply = self._inner.respond(company, turn)
        self._action()
        return reply

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def concurrent_turn(
    db: sessionmaker[Session],
    founder: Founder,
    message: str,
    proposal: Any,
    action: Callable[[], None],
    targets: tuple[str, ...] = ("q1",),
) -> tuple[Any, ScriptedProvider]:
    chat = ScriptedProvider(proposal, response(SAFE, list(targets)))
    service = AskConversations(
        During(gateway(founder.evaluation, chat), action),  # type: ignore[arg-type]
        policy="disabled",
        rules=None,
    )
    request = TurnRequest(message, uuid.uuid4(), founder.conversation_id, founder.revision)
    with db() as session:
        result = service.run_turn(session, founder.context, request)
    founder.revision = result.sequence
    return result, chat


def last_record(db: sessionmaker[Session]) -> dict[str, Any]:
    with db() as session:
        rows = session.scalars(
            select(AssistantTurnEvaluation.record).order_by(AssistantTurnEvaluation.created_at)
        ).all()
    return rows[-1]


# --- commit-time reconciliation ----------------------------------------------------------------


def test_a_stricter_result_at_commit_replaces_the_models_words(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    case_id = founder.say(LATE, late()).case_id
    assert case_id is not None
    # Prepared on "standard not known" (Guidance); meanwhile the form records "not explained".
    result, chat = concurrent_turn(
        db,
        founder,
        NEXT,
        late(NEXT, 1),
        lambda: form_save(db, alice_context, case_id, {QUESTION: "no"}),
    )
    assert len(chat.calls) == 2  # no third request to reconcile
    assert result.heroos.content.startswith(FALLBACK_LEADS["changed"])
    assert SAFE not in result.heroos.content
    assert result.heroos.outcome is not None and result.heroos.outcome["kind"] == "warning"
    record = last_record(db)
    assert record["presentation"] == "warning"
    assert record["facts"]["engine_trusted"][POLICY] == "no"


def test_a_prerequisite_recorded_meanwhile_turns_a_stale_block_into_guidance(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    policy_prerequisite(artifacts)
    founder = Founder(db, artifacts, alice_context)
    case_id = founder.say(LATE, late()).case_id
    assert case_id is not None
    form_save(db, alice_context, case_id, {QUESTION: "no"})
    blocked = founder.say(WARN, warn(WARN, 1)).heroos.outcome
    assert blocked is not None and blocked["kind"] == "block"
    # Prepared on "not explained" (Block); meanwhile another administrator records "explained".
    other = add_admin(db, alice_context.company_id)
    again = "And now, can I give him a written warning?"
    result, chat = concurrent_turn(
        db,
        founder,
        again,
        warn(again, 2),
        lambda: form_save(db, other, case_id, {QUESTION: "yes"}),
        # The Case already holds the answer when the turn starts: nothing is asked about it.
        targets=(),
    )
    assert len(chat.calls) == 2  # no third request to reconcile
    # The current, authoritative result is recorded; the stale Block's words are discarded.
    assert result.heroos.outcome is not None and result.heroos.outcome["kind"] == "guidance"
    assert result.heroos.content.startswith(FALLBACK_LEADS["changed"])
    assert SAFE not in result.heroos.content
    record = last_record(db)
    assert record["presentation"] == "guidance"
    assert record["facts"]["engine_trusted"][POLICY] == "yes"
    assert [a["disposition"] for a in record["actions"]] == ["allow"]


def test_an_authoritative_change_meanwhile_relaxes_a_warning(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    case_id = founder.say(LATE, late()).case_id
    assert case_id is not None
    form_save(db, alice_context, case_id, {QUESTION: "no"})
    # Prepared on "not explained" (Warning); meanwhile the form records "explained".
    result, _ = concurrent_turn(
        db,
        founder,
        NEXT,
        late(NEXT, 1),
        lambda: form_save(db, alice_context, case_id, {QUESTION: "yes"}),
    )
    assert result.heroos.outcome is not None and result.heroos.outcome["kind"] == "guidance"
    assert result.heroos.content.startswith(FALLBACK_LEADS["changed"])
    assert last_record(db)["presentation"] == "guidance"


def test_a_fact_made_uncertain_meanwhile_never_relaxes_a_warning(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    case_id = founder.say(LATE, late()).case_id
    assert case_id is not None
    form_save(db, alice_context, case_id, {QUESTION: "no"})
    # Prepared on "not explained" (Warning); meanwhile the answer becomes "Not sure". On
    # its own the current evaluation would be Guidance: less known, never less strict.
    result, _ = concurrent_turn(
        db,
        founder,
        NEXT,
        late(NEXT, 1),
        lambda: form_save(db, alice_context, case_id, {QUESTION: "not_sure"}),
    )
    assert result.heroos.outcome is not None and result.heroos.outcome["kind"] == "warning"
    assert last_record(db)["presentation"] == "warning"
    with db() as session:
        (conversation,) = session.scalars(select(AssistantConversation)).all()
    checkpoint = decode(conversation.checkpoint)
    # The next turn starts from the Case as it is now.
    assert checkpoint is not None and checkpoint.state.engine.get(POLICY) != "no"
    founder.say("Thanks.", late("Thanks.", 2))
    assert last_record(db)["facts"]["engine_trusted"][POLICY] == "not_sure"


def test_a_fact_made_uncertain_meanwhile_never_relaxes_a_block(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    policy_prerequisite(artifacts)
    founder = Founder(db, artifacts, alice_context)
    case_id = founder.say(LATE, late()).case_id
    assert case_id is not None
    form_save(db, alice_context, case_id, {QUESTION: "no"})
    result, _ = concurrent_turn(
        db,
        founder,
        WARN,
        warn(WARN, 1),
        lambda: form_save(db, alice_context, case_id, {QUESTION: "not_sure"}),
    )
    assert result.heroos.outcome is not None and result.heroos.outcome["kind"] == "block"
    record = last_record(db)
    assert record["presentation"] == "block"
    assert [a["disposition"] for a in record["actions"]] == ["block"]


def test_an_unresolved_jurisdiction_meanwhile_never_relaxes_an_expert_review(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    case_id = founder.say(LATE, late()).case_id
    assert case_id is not None
    # Prepared on the resolved jurisdiction (Expert Review for the dismissal); meanwhile the
    # Case's jurisdiction is answered "Not sure". Unresolved, the dismissal would only be held
    # for the jurisdiction (Block): uncertainty never loosens the review.
    result, _ = concurrent_turn(
        db,
        founder,
        FIRE,
        fire(FIRE, 1),
        lambda: form_save(
            db, alice_context, case_id, {CASE_JURISDICTION_KEY: "not_sure"}, "jurisdiction"
        ),
    )
    assert result.heroos.outcome is not None and result.heroos.outcome["kind"] == "expert_review"
    assert last_record(db)["presentation"] == "expert_review"
    with db() as session:
        (conversation,) = session.scalars(select(AssistantConversation)).all()
    checkpoint = decode(conversation.checkpoint)
    # The review stays active; the next turn starts from the unresolved jurisdiction.
    assert checkpoint is not None and checkpoint.reviews.actions == ("opt-dismissal",)
    assert checkpoint.state.jurisdiction == "not_sure"
    founder.say(FIRE, fire(FIRE, 2))
    latest = last_record(db)
    assert latest["jurisdiction_state"] == "case_not_sure" and latest["jurisdiction"] is None


def test_a_held_reply_never_carries_trust_lost_at_commit(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    case_id = founder.say(LATE, late()).case_id
    assert case_id is not None
    form_save(db, alice_context, case_id, {QUESTION: "no"})
    # The Company's jurisdiction changes while the model answers: the Warning prepared under
    # the old one stands, but nothing trusted under it is carried into the new one.
    result, _ = concurrent_turn(
        db, founder, NEXT, late(NEXT, 1), lambda: move_to_difc(db, alice_context.company_id)
    )
    assert result.heroos.outcome is not None and result.heroos.outcome["kind"] == "warning"
    with db() as session:
        (conversation,) = session.scalars(select(AssistantConversation)).all()
    checkpoint = decode(conversation.checkpoint)
    assert checkpoint is not None and checkpoint.company_jurisdiction == "difc"
    assert checkpoint.state.reconfirm is True


def test_an_unrelated_change_keeps_the_models_words(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    case_id = founder.say(LATE, late()).case_id
    assert case_id is not None
    result, _ = concurrent_turn(
        db,
        founder,
        NEXT,
        late(NEXT, 1),
        lambda: form_save(db, alice_context, case_id, {"incident.history": "new"}, "initial_facts"),
    )
    # The model's words are kept. The question asked last turn (and not answered by this message)
    # isn't asked again at once.
    assert result.heroos.content == SAFE
    assert result.heroos.outcome is not None and result.heroos.outcome["kind"] == "guidance"


# --- runtime changes ----------------------------------------------------------------------------


@pytest.mark.parametrize("change", ["profile", "rule_bundle"])
def test_a_new_runtime_never_carries_trusted_state_over(
    db: sessionmaker[Session],
    artifacts: Artifacts,
    alice_context: AuthenticatedCompanyContext,
    change: str,
) -> None:
    founder = Founder(db, artifacts, alice_context)
    founder.say(LATE, late())
    founder.say("Yes.", late("Yes.", 1))
    if change == "profile":
        artifacts.profile["version"] = "synthetic.2"
    else:
        artifacts.disciplinary["version"] = "synthetic.2"
        artifacts.profile["workflows"][0]["rule_bundle"]["version"] = "synthetic.2"
        artifacts.repin()
    founder.evaluation = artifacts.service()
    founder.say(NEXT, late(NEXT, 2))
    with db() as session:
        (conversation,) = session.scalars(select(AssistantConversation)).all()
    checkpoint = decode(conversation.checkpoint)
    assert checkpoint is not None and checkpoint.state.reconfirm is True
    # The Case's fact is still the record, re-validated against the current runtime.
    record = last_record(db)
    assert record["facts"]["engine_trusted"][POLICY] == "yes"
    assert record["facts"]["sources"][POLICY] == "continuation"


def test_a_historical_value_the_current_runtime_rejects_stays_history(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    case_id = founder.say(LATE, late()).case_id
    with db() as session:
        instance = session.scalar(
            text("SELECT id FROM workflow_instances WHERE case_id = :c"), {"c": case_id.hex}
        )
        submission = uuid.uuid4()
        # A value an earlier definition allowed, which the current schema doesn't.
        session.execute(
            text(
                "INSERT INTO workflow_submissions (id, company_id, instance_id, step_key, "
                "revision, idempotency_key, submitted_by_user_id, origin) VALUES "
                "(:id, :company, :instance, 'incident_context', 2, :key, :user, 'structured')"
            ),
            {
                "id": submission.hex,
                "company": alice_context.company_id.hex,
                "instance": instance,
                "key": uuid.uuid4().hex,
                "user": alice_context.user_id.hex,
            },
        )
        session.execute(
            text(
                "INSERT INTO case_facts (id, company_id, instance_id, submission_id, fact_key, "
                "value) VALUES (:id, :company, :instance, :submission, :key, '\"maybe\"')"
            ),
            {
                "id": uuid.uuid4().hex,
                "company": alice_context.company_id.hex,
                "instance": instance,
                "submission": submission.hex,
                "key": QUESTION,
            },
        )
        # After the narrative (chat-first Case), the Case's first submission.
        session.execute(text("UPDATE workflow_instances SET revision = 2"))
        session.commit()
    founder.say(NEXT, late(NEXT, 1))
    assert POLICY not in last_record(db)["facts"]["engine_trusted"]
    with db() as session:
        assert [f.value for f in session.scalars(select(CaseFact)).all()] == [LATE, "maybe"]


# --- separate matters ---------------------------------------------------------------------------


def test_a_separate_matter_never_writes_into_the_case(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: AuthenticatedCompanyContext
) -> None:
    founder = Founder(db, artifacts, alice_context)
    case_id = founder.say(LATE, late()).case_id
    said = "No. Also a different employee took money from the till."
    result = founder.say(said, late(said, 1, uncertainties=["multiple_matters"]))
    assert result.case_id == case_id
    with db() as session:
        # Only the first message's narrative: nothing of the other matter reaches the Case.
        facts = session.scalars(select(CaseFact)).all()
        assert [(f.fact_key, f.value) for f in facts] == [(NARRATIVE_KEY, LATE)]
        (conversation,) = session.scalars(select(AssistantConversation)).all()
        assert session.scalar(select(AssistantTurnEvaluation.multiple_matters).limit(1).offset(1))
        heroos = session.scalars(
            select(AssistantMessage).where(AssistantMessage.role == "heroos")
        ).all()
    checkpoint = decode(conversation.checkpoint)
    assert checkpoint is not None and POLICY not in checkpoint.state.engine
    assert last_record(db)["next_step"] == "choose_matter"
    assert len(heroos) == 2


# --- what counts as uncertainty -----------------------------------------------------------------


def _turn(evaluation: ConversationEvaluation, *, reconfirm: bool = False) -> Any:
    return _Turn(evaluation, None, None, PriorState(), reconfirm)


def _ready(**kwargs: Any) -> ConversationEvaluation:
    defaults: dict[str, Any] = {
        "jurisdiction": "uae_federal",
        "jurisdiction_state": "resolved",
        "facts": TrustedFactState(engine={POLICY: "no"}),
    }
    return ConversationEvaluation("ready", "supported", "disciplinary", **{**defaults, **kwargs})


def _caution(status: Any) -> ConditionEvaluation:
    return ConditionEvaluation(
        condition="EX-FED-POLICY", category="executable", status=status, initial="warn",
        action="warn", follow_up="not_applicable", reasons=(), missing=(), provisional=False,
        linked_actions=(),
    )  # fmt: skip


def _step(disposition: Any) -> ActionEvaluation:
    return ActionEvaluation(
        action="opt-warning", title="Written warning", disposition=disposition, reasons=(),
        missing=(), provisional=False, review=None, next_step="continue_methodology",
        conditions=(),
    )  # fmt: skip


@pytest.mark.parametrize(
    ("fresh", "reconfirm", "reason"),
    [
        (_ready(facts=TrustedFactState(engine={POLICY: "yes"})), False, None),
        (
            ConversationEvaluation("rule_bundle_missing", "supported", "disciplinary"),
            False,
            "unavailable",
        ),
        (_ready(), True, "trust_lost"),
        (_ready(jurisdiction=None, jurisdiction_state="case_not_sure"), False, "jurisdiction"),
        (_ready(jurisdiction="difc"), False, "jurisdiction"),
        (_ready(facts=TrustedFactState()), False, "fact_lost"),
        (_ready(facts=TrustedFactState(engine={POLICY: "not_sure"})), False, "fact_lost"),
        (_ready(conditions=(_caution("unknown"),)), False, "unverifiable"),
        (_ready(actions=(_step("unknown"),)), False, "unverifiable"),
    ],
)
def test_only_less_certain_state_counts_as_uncertainty(
    fresh: ConversationEvaluation, reconfirm: bool, reason: str | None
) -> None:
    prepared = _ready(conditions=(_caution("fired"),), actions=(_step("block"),))
    assert uncertainty(_turn(fresh, reconfirm=reconfirm), _turn(prepared)) == reason
