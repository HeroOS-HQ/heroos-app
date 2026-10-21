"""The fact trust pipeline and deterministic canonicalization (M2-NEW-06).

Only ENGINE_TRUSTED values enter a rule, and only the server makes a value
ENGINE_TRUSTED: a plain direct answer to the one question it asked, a
confirmation of its own canonical reading, or the Company Blueprint. The AI's
reading of the founder's words, even of real words, never is.
"""

import pytest

from app.evaluation.facts import (
    Asked,
    PriorState,
    StatedFact,
    canonical,
    contradicted,
    parse_count,
    parse_insistence,
    parse_yes_no,
    trust_facts,
)
from app.evaluation.model import TwoState
from app.evaluation.snapshot import FactSchema, WorkflowExecution
from app.workflows.conditions import Tri
from app.workflows.definition import DISCIPLINARY_V2
from tests.fixtures.evaluation import Artifacts

BLUEPRINT = {"employee_count": 12}


@pytest.fixture
def execution(artifacts: Artifacts) -> WorkflowExecution:
    found = artifacts.snapshot().execution("disciplinary")
    assert found is not None
    return found


def trust(execution: WorkflowExecution, message: str, *, stated=(), prior=None):  # type: ignore[no-untyped-def]
    return trust_facts(
        execution,
        stated=list(stated),
        message=message,
        prior=prior or PriorState(),
        blueprint=BLUEPRINT,
    )


# --- canonicalization: plain answers only -----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Yes.", "yes"),
        ("yes", "yes"),
        ("Yep", "yes"),
        ("Yes, he has.", "yes"),
        ("Yes, and he was late again today.", "yes"),
        ("No.", "no"),
        ("No, not yet.", "no"),
        ("Not sure", "not_sure"),
        ("I don't know", "not_sure"),
        ("I sort of spoke to him.", None),
        ("Yes, but only verbally.", None),
        ("Maybe", None),
        ("Yes, he didn't", None),
        ("No... well, yes", None),
        ("I spoke to him about it", None),
        ("He has", None),
        ("y" * 200, None),
    ],
)
def test_yes_no_answers(text: str, expected: str | None) -> None:
    assert parse_yes_no(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Eight.", 8),
        ("8", 8),
        ("8 days", 8),
        ("eight days", 8),
        ("twice", 2),
        ("20 working days", 20),
        ("He's been gone basically all week.", None),
        ("about 8", None),
        ("8 or 9", None),
        ("around eight days", None),
        ("a few days", None),
        ("more than 8", None),
        ("8-10", None),
        ("8 days, maybe 9", None),
        ("all week", None),
    ],
)
def test_exact_numbers_only(text: str, expected: int | None) -> None:
    assert parse_count(text) == expected


def test_a_count_above_its_bound_is_not_an_answer() -> None:
    assert parse_count("400", 365) is None and parse_count("365", 365) == 365


def test_choices_come_from_the_definition(execution: WorkflowExecution) -> None:
    question = DISCIPLINARY_V2.question("context.location")
    assert question is not None
    # The definition's own options: "Yes, at work or while working" / "No, outside work".
    location = FactSchema("incident_location", "Location", "choice", question.options)
    assert canonical(location, "No.") == "outside_work"
    assert canonical(location, "Yes") == "at_work"
    assert canonical(location, "No, outside work") == "outside_work"
    assert canonical(location, "Not sure") == "not_sure"
    assert canonical(location, "In the car park") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Yes", "insists"),
        ("Yes, I still want to go ahead.", "insists"),
        ("I still want to go ahead", "insists"),
        ("No", "declines"),
        ("OK, understood.", "acknowledged"),
        ("Understood", "acknowledged"),
        ("I WANT TO SUSPEND HIM FOR 20 DAYS!!!", None),
        ("Why?", None),
        ("I suppose I'll go ahead", None),
        ("I don't want to go ahead", None),
    ],
)
def test_insistence_is_explicit_never_tone(text: str, expected: str | None) -> None:
    assert parse_insistence(text) == expected


# --- the pipeline -------------------------------------------------------------------------------


def test_a_wrong_reading_of_real_words_is_never_trusted(execution: WorkflowExecution) -> None:
    """: "I did NOT speak to the employee", read by a bad model as "yes"."""
    words = "I did NOT speak to the employee."
    stated = [StatedFact("given_opportunity_to_explain", "yes", words, True, True)]
    assert contradicted("yes", words)
    result = trust(execution, words, stated=stated)
    assert "given_opportunity_to_explain" not in result.facts.engine
    assert result.facts.level("given_opportunity_to_explain") == "proposed"


def test_an_approximate_number_sets_no_threshold(execution: WorkflowExecution) -> None:
    """: "He's been gone all week" is never an exact number of days."""
    words = "He's been gone basically all week."
    stated = [StatedFact("proposed_suspension_days", "5", words, True, True)]
    result = trust(execution, words, stated=stated)
    assert "proposed_suspension_days" not in result.facts.engine
    assert result.facts.level("proposed_suspension_days") == "proposed"


def test_a_plain_answer_to_the_known_question_is_trusted(execution: WorkflowExecution) -> None:
    """: HeroOS asked one yes/no question; "Yes." is a canonical yes."""
    prior = PriorState(asked=(Asked("fact", "given_opportunity_to_explain"),))
    result = trust(execution, "Yes.", prior=prior)
    assert result.facts.engine["given_opportunity_to_explain"] == "yes"
    assert result.facts.sources["given_opportunity_to_explain"] == "direct_answer"
    assert result.answered
    counted = trust(
        execution, "Eight.", prior=PriorState(asked=(Asked("fact", "proposed_suspension_days"),))
    )
    assert counted.facts.engine["proposed_suspension_days"] == 8


def test_a_short_answer_means_nothing_without_one_known_question(
    execution: WorkflowExecution,
) -> None:
    assert "given_opportunity_to_explain" not in trust(execution, "Yes.").facts.engine
    two = PriorState(
        asked=(
            Asked("fact", "given_opportunity_to_explain"),
            Asked("fact", "investigation_completed"),
        )
    )
    assert not trust(execution, "Yes.", prior=two).facts.engine.get("investigation_completed")
    assert "given_opportunity_to_explain" not in trust(execution, "Yes.", prior=two).facts.engine


def test_heroos_own_words_are_never_evidence(execution: WorkflowExecution) -> None:
    """: only the founder's current message and trusted state count; replies never do."""
    result = trust(execution, "Thanks, that's helpful.", prior=PriorState())
    assert dict(result.facts.engine) == {"headcount": 12}
    assert result.facts.sources["headcount"] == "blueprint"


def test_the_newest_explicit_correction_controls(execution: WorkflowExecution) -> None:
    """: a different value stated now voids the trusted one until confirmed again."""
    prior = PriorState(engine={"proposed_suspension_days": 8})
    kept = trust(execution, "Fine.", prior=prior)
    assert kept.facts.engine["proposed_suspension_days"] == 8
    words = "Sorry, I meant 12 days."
    stated = [StatedFact("proposed_suspension_days", "12", "I meant 12 days", True, True)]
    corrected = trust(execution, words, stated=stated, prior=prior)
    assert "proposed_suspension_days" not in corrected.facts.engine
    assert corrected.facts.conversational["proposed_suspension_days"] == "12"
    # The same value restated keeps it.
    same = [StatedFact("proposed_suspension_days", "8", "8 days", True, True)]
    assert (
        trust(execution, "8 days", stated=same, prior=prior).facts.engine[
            "proposed_suspension_days"
        ]
        == 8
    )
    # An older statement doesn't void a newer trusted answer.
    old = [StatedFact("proposed_suspension_days", "12", "12 days", True, False)]
    assert (
        trust(execution, "Fine.", stated=old, prior=prior).facts.engine["proposed_suspension_days"]
        == 8
    )


def test_ambiguous_text_asks_never_guesses(execution: WorkflowExecution) -> None:
    """: a hedged answer to the known question is not a value."""
    prior = PriorState(asked=(Asked("fact", "given_opportunity_to_explain"),))
    result = trust(execution, "I sort of spoke to him.", prior=prior)
    assert "given_opportunity_to_explain" not in result.facts.engine
    assert not result.answered


def test_a_confirmation_trusts_only_the_servers_canonical_candidate(
    execution: WorkflowExecution,
) -> None:
    asked = Asked("confirm", "proposed_suspension_days", 20)
    confirmed = trust(execution, "Yes", prior=PriorState(asked=(asked,)))
    assert confirmed.facts.engine["proposed_suspension_days"] == 20
    assert confirmed.facts.sources["proposed_suspension_days"] == "confirmation"
    declined = trust(execution, "No", prior=PriorState(asked=(asked,)))
    assert "proposed_suspension_days" not in declined.facts.engine
    assert "proposed_suspension_days" in declined.declined


def test_insistence_and_acknowledgment_are_separate(execution: WorkflowExecution) -> None:
    shown = {"fictional_cap": TwoState("fictional_cap", True, False, Tri.FALSE)}
    asked = (Asked("insistence", "fictional_cap", "opt-suspension"),)
    understood = trust(execution, "Understood.", prior=PriorState(two_state=shown, asked=asked))
    state = understood.two_state["fictional_cap"]
    assert state.acknowledged and state.insists is Tri.FALSE
    insisted = trust(execution, "Yes.", prior=PriorState(two_state=shown, asked=asked))
    assert insisted.two_state["fictional_cap"].insists is Tri.TRUE
    shouted = trust(execution, "SUSPEND HIM!!!", prior=PriorState(two_state=shown, asked=asked))
    assert shouted.two_state["fictional_cap"].insists is Tri.FALSE


def test_sensitive_facts_are_never_typed_for_execution(execution: WorkflowExecution) -> None:
    assert "dismissal_without_notice_considered" not in execution.schemas
    prior = PriorState(asked=(Asked("fact", "dismissal_without_notice_considered"),))
    assert (
        "dismissal_without_notice_considered"
        not in trust(execution, "Yes", prior=prior).facts.engine
    )


def test_continued_values_are_revalidated(execution: WorkflowExecution) -> None:
    prior = PriorState(
        engine={
            "proposed_suspension_days": "lots",
            "unknown_fact": "yes",
            "given_opportunity_to_explain": "yes",
        }
    )
    engine = trust(execution, "ok", prior=prior).facts.engine
    assert engine == {"given_opportunity_to_explain": "yes", "headcount": 12}
