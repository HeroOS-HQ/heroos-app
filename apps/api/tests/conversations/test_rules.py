"""M2-NEW-07 Part 2: the pure rules behind persistence (no database, no model).

- a decision is withdrawn only by the founder's own explicit words in the current message;
- active reviews: only a fresh evaluation of that decision or an explicit withdrawal changes
  one, and they rebuild identically from the stored records;
- the status's dimensions are independent;
- a conversational fact is checked as a value, never by the founder's path through the form:
  an ungated step needs no navigation, a closed semantic gate holds, a stage checklist is
  never written, and a follow-up waits (kept in the checkpoint) until its premise is known.
"""

import json
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.assistant.gateway.catalog import routing_catalog
from app.assistant.gateway.proposals import ProposalError, check_evidence, parse_understanding
from app.conversations.bridge import fact_changes
from app.conversations.checkpoint import Resumed, Reviews, next_checkpoint
from app.conversations.status import UNNAMED_DECISION, project
from app.evaluation.continuation import ContinuationState, ReadResult
from app.evaluation.model import (
    ActionEvaluation,
    ConversationEvaluation,
    ReviewRequirement,
    TrustedFactState,
)
from app.evaluation.snapshot import FactSchema
from app.knowledge.bundle import KnowledgeBundle
from app.workflows.definition import (
    DISCIPLINARY_V2,
    Option,
    Question,
    Step,
    StepGate,
    WorkflowDefinition,
)
from tests.fixtures.evaluation import Artifacts
from tests.fixtures.gateway import understanding
from tests.knowledge.conftest import bundle, bundle_file  # noqa: F401  (pytest fixtures)

TODAY = date(2026, 10, 22)


# --- withdrawal ----------------------------------------------------------------------------------


def proposal(bundle: KnowledgeBundle, withdrawn: list[dict[str, Any]], current: int = 1) -> Any:  # noqa: F811
    data = understanding(topics=["dismissal_without_notice"])
    data["withdrawn_actions"] = withdrawn
    return parse_understanding(json.dumps(data), routing_catalog(bundle), current_turn=current)


def withdrawn(bundle: KnowledgeBundle, excerpt: str, turn: int, messages: list[str]) -> list[str]:  # noqa: F811
    parsed = proposal(
        bundle,
        [{"action": "opt-dismissal", "source_turn": turn, "support_excerpt": excerpt}],
        current=len(messages) - 1,
    )
    kept, _ = check_evidence(parsed, routing_catalog(bundle), messages, "")
    return [a.action for a in kept.withdrawn]


@pytest.mark.parametrize(
    ("message", "excerpt", "expected"),
    [
        ("We're no longer considering dismissal.", "no longer considering dismissal", True),
        ("We decided against dismissing her.", "decided against dismissing her", True),
        ("I don't want to fire her anymore.", "don't want to fire her", True),
        # A change of topic, a question or an excerpt that isn't the founder's words: nothing.
        ("Let's look at the investigation.", "look at the investigation", False),
        ("Should we dismiss her?", "dismiss her", False),
        ("We're no longer considering dismissal.", "we have dropped it", False),
    ],
)
def test_only_the_founders_explicit_words_withdraw_a_decision(
    bundle: KnowledgeBundle,  # noqa: F811
    message: str,
    excerpt: str,
    expected: bool,
) -> None:
    messages = ["Can I fire her today?", message]
    assert (withdrawn(bundle, excerpt, 1, messages) == ["opt-dismissal"]) is expected


def test_a_withdrawal_counts_only_from_the_current_message(bundle: KnowledgeBundle) -> None:  # noqa: F811
    messages = ["We're no longer considering dismissal.", "Can I fire her today?"]
    assert withdrawn(bundle, "no longer considering dismissal", 0, messages) == []


def test_a_withdrawal_names_a_catalog_decision_once(bundle: KnowledgeBundle) -> None:  # noqa: F811
    item = {"action": "opt-dismissal", "source_turn": 1, "support_excerpt": "no longer"}
    with pytest.raises(ProposalError, match="unknown_action"):
        proposal(bundle, [{**item, "action": "opt-made-up"}])
    with pytest.raises(ProposalError, match="duplicate_value"):
        proposal(bundle, [item, item])


# --- active reviews ------------------------------------------------------------------------------


def turn(*actions: tuple[str, bool], matter: str = "supported", matter_review: bool = False) -> Any:
    return ConversationEvaluation(
        availability="ready",
        matter=matter,  # type: ignore[arg-type]
        workflow="disciplinary",
        actions=tuple(
            ActionEvaluation(
                action=a,
                title=a,
                disposition="escalate" if required else "allow",
                reasons=(),
                missing=(),
                provisional=False,
                review=ReviewRequirement(True, "action", a, ()) if required else None,
                next_step="continue_methodology",
                conditions=(),
            )
            for a, required in actions
        ),
        reviews=(ReviewRequirement(True, "matter", None, ()),) if matter_review else (),
    )


def test_only_a_fresh_evaluation_or_a_withdrawal_ends_a_review() -> None:
    reviews = Reviews().after(turn(("opt-dismissal", True), ("opt-investigative", False)), ())
    assert reviews == Reviews(("opt-dismissal",), False)
    # A turn about something else changes nothing.
    assert reviews.after(turn(("opt-reminder", False)), ()) == reviews
    assert reviews.after(turn(matter="unclear"), ()) == reviews
    # A fresh evaluation of that decision that needs no review ends it.
    assert reviews.after(turn(("opt-dismissal", False)), ()) == Reviews()
    # So does an explicit withdrawal.
    assert reviews.after(turn(), ("opt-dismissal",)) == Reviews()


def test_a_matter_level_review_follows_the_current_matter() -> None:
    unsupported = Reviews().after(turn(matter="unsupported_hr", matter_review=True), ())
    assert unsupported.matter is True
    # "Thanks" (unclear) keeps it; a supported matter is the current state again.
    assert unsupported.after(turn(matter="unclear"), ()).matter is True
    assert unsupported.after(turn(matter="supported"), ()).matter is False


def test_reviews_rebuild_identically_from_the_records() -> None:
    turns = [
        (turn(("opt-dismissal", True)), ()),
        (turn(("opt-reminder", False)), ()),
        (turn(matter="unsupported_hr", matter_review=True), ()),
        (turn(), ("opt-dismissal",)),
        (turn(("opt-deduction", True)), ()),
    ]
    folded = Reviews()
    for evaluation, gone in turns:
        folded = folded.after(evaluation, gone)
    stored = [(evaluation.record(), list(gone)) for evaluation, gone in turns]
    # The fourth turn is a supported matter again: the matter-level review is over.
    assert Reviews.replay(stored) == folded == Reviews(("opt-deduction",), False)
    assert Reviews.replay(stored[:3]) == Reviews(("opt-dismissal",), True)


# --- the status's dimensions ------------------------------------------------------------------


def status(**overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "case_hold": False,
        "jurisdiction_states": ("resolved", None),
        "workflow": "disciplinary",
        "workflow_title": "Disciplinary",
        "reviews": Reviews(),
        "latest_record": {"missing": []},
        "latest_outcome": "guidance",
        "checks": "ready",
        "action_titles": {"opt-dismissal": "Dismissal without notice"},
        **overrides,
    }
    return project(**arguments)


def test_each_dimension_comes_from_its_own_source() -> None:
    base = status()
    assert (base.lifecycle, base.needs_information, base.expert_review.active) == (
        "in_progress",
        False,
        False,
    )
    review = status(reviews=Reviews(("opt-dismissal", "opt-unknown"), False)).expert_review
    assert (review.active, review.scope, review.actions) == (
        True,
        "action",
        ("Dismissal without notice", UNNAMED_DECISION),
    )
    # None of them moves another.
    assert status(reviews=Reviews(("opt-dismissal",), False)).lifecycle == "in_progress"
    assert status(checks="unavailable").lifecycle == "in_progress"
    assert status(latest_outcome="block").lifecycle == "in_progress"
    assert status(latest_record={"missing": [{"key": "x"}]}).needs_information is True
    assert status(case_hold=True).lifecycle == "paused"
    assert status(case_hold=None).lifecycle is None
    assert base.jurisdiction is None


@pytest.mark.parametrize(
    "states",
    [
        ("case_confirmation_outdated", "resolved"),
        ("case_not_sure", None),
        ("resolved", "conversation_conflict"),
        (None, "company_unconfirmed"),
    ],
)
def test_a_jurisdiction_to_confirm_is_attention_never_a_paused_case(states: Any) -> None:
    """Only what depends on the jurisdiction waits; the Case itself goes on."""
    waiting = status(jurisdiction_states=states)
    assert waiting.lifecycle == "in_progress"
    assert (waiting.jurisdiction, waiting.needs_information) == ("needs_confirmation", True)
    # A specialist-review hold (another jurisdiction applies, say) holds the whole matter.
    assert status(jurisdiction_states=("case_different",), case_hold=True).lifecycle == "paused"
    assert status(jurisdiction_states=("case_different",)).jurisdiction is None
    assert status(latest_outcome="approved").latest_outcome == "none"
    assert status(reviews=Reviews((), True)).expert_review.scope == "matter"


# --- a fact's value, never the founder's path through the form ------------------------------------


def fake_execution(**schemas: FactSchema) -> Any:
    return SimpleNamespace(schemas=schemas)


def trusted(**facts: str) -> ConversationEvaluation:
    return ConversationEvaluation(
        availability="ready",
        matter="supported",
        workflow="disciplinary",
        facts=TrustedFactState(engine=facts, sources=dict.fromkeys(facts, "direct_answer")),
    )


def test_an_ungated_step_needs_no_navigation(artifacts: Artifacts) -> None:
    execution = artifacts.snapshot().execution("disciplinary")
    changes = fact_changes(
        trusted(employee_aware_of_relevant_policy="yes"),
        execution,  # type: ignore[arg-type]
        DISCIPLINARY_V2,
        current={},  # nothing answered in the form, no step opened
        open_steps=(),
        from_case=frozenset(),
        today=TODAY,
    )
    assert changes == {"context.policy_awareness": "yes"}


def test_a_closed_semantic_gate_holds_and_a_stage_checklist_is_never_written() -> None:
    gated = WorkflowDefinition(
        key="disciplinary",
        version=99,
        title="Disciplinary",
        case_type="disciplinary",
        welcome_title="x",
        welcome="x",
        steps=(
            Step(
                "gated",
                "Gated",
                "x",
                (Question("gated.q", "choice", "Q?", "Q", options=(Option("yes", "Yes"),)),),
                gate=StepGate.COMPANY_JURISDICTION_CONFIRMED,
            ),
        ),
        not_available=(),
    )
    execution = fake_execution(
        gated=FactSchema("gated", "Gated", "yes_no", (Option("yes", "Yes"),), question="gated.q"),
        stage=FactSchema("stage", "Stage", "yes_no", (Option("yes", "Yes"),), question="stage.q"),
    )
    evaluation = trusted(gated="yes", stage="yes")

    def changes(open_steps: tuple[str, ...]) -> dict[str, str]:
        return fact_changes(
            evaluation,
            execution,
            gated,
            current={},
            open_steps=open_steps,
            from_case=frozenset(),
            today=TODAY,
        )

    assert changes(()) == {}
    # Open gate: the definition's own question only (the checklist key isn't one of them).
    assert changes(("gated",)) == {"gated.q": "yes"}


def test_a_follow_up_waits_in_the_checkpoint_until_its_premise_is_known(
    artifacts: Artifacts,
) -> None:
    snapshot = artifacts.snapshot()
    state = ContinuationState(
        workflow="disciplinary", engine={"employee_aware_of_relevant_policy": "yes"}
    )
    # Not yet saved to the Case (say its follow-up premise is unknown): the checkpoint keeps it.
    kept = next_checkpoint(
        snapshot,
        state,
        resumed=Resumed(ReadResult(state, None, True)),
        workflow="disciplinary",
        case_answers={},
        case_revision=1,
        company_jurisdiction="uae_federal",
        reviews=Reviews(),
    )
    assert kept.state.engine == {"employee_aware_of_relevant_policy": "yes"}
