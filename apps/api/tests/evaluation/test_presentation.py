"""The outcome card, the safe next step and the contradiction check (M2-NEW-06)."""

import pytest

from app.evaluation.evaluator import EvaluationRequest, evaluate_conversation
from app.evaluation.model import (
    ActionEvaluation,
    ConversationEvaluation,
    ReviewRequirement,
    TrustedFactState,
)
from app.evaluation.presentation import (
    NEXT_STEPS,
    PROVISIONAL,
    fallback_reply,
    outcome,
    outcome_contradiction,
    outcome_view,
)
from app.evaluation.snapshot import ExecutionSnapshot
from tests.fixtures.evaluation import Artifacts

READY = {"given_opportunity_to_explain": "yes", "investigation_completed": "yes"}


def run(
    snapshot: ExecutionSnapshot,
    facts: dict[str, object],
    *requested: str,
    jurisdiction: str | None = "uae_federal",
    **extra: object,
) -> ConversationEvaluation:
    return evaluate_conversation(
        snapshot,
        EvaluationRequest(
            matter="supported",
            workflow="disciplinary",
            company_jurisdiction=jurisdiction,
            facts=TrustedFactState(engine=facts),
            requested=requested,
            **extra,  # type: ignore[arg-type]
        ),
    )


def held(disposition: str) -> ConversationEvaluation:
    review = ReviewRequirement(True, "action", "x", ()) if disposition == "escalate" else None
    step = ActionEvaluation(
        "x",
        "Dismissal without notice",
        disposition,
        (),
        (),
        False,
        review,  # type: ignore[arg-type]
        "obtain_specialist_review",
        (),
    )
    presentation = {
        "escalate": "expert_review",
        "block": "block",
        "warn": "warning",
        "allow": "guidance",
    }[disposition]
    return ConversationEvaluation(
        availability="ready",
        matter="supported",
        actions=(step,),
        reviews=() if review is None else (review,),
        presentation=presentation,  # type: ignore[arg-type]
    )


def test_expert_review_is_a_requirement_never_a_ticket(artifacts: Artifacts) -> None:
    card = outcome(run(artifacts.snapshot(), READY, "opt-dismissal"))
    assert card is not None and card.kind == "expert_review" and card.title == "Expert Review"
    text = card.message.lower()
    assert "specialist review is required before" in text
    for promise in ("ticket", "submitted", "sent to", "jj", "will respond", "assigned", "shortly"):
        assert promise not in text


def test_block_is_about_the_step_never_the_conversation(artifacts: Artifacts) -> None:
    card = outcome(run(artifacts.snapshot(), {}, "opt-warning"))
    assert card is not None and card.kind == "block"
    assert card.title.startswith("Not yet: ") and "Don't take this step yet" in card.message
    assert "cannot proceed" not in card.message.lower().replace("can't safely proceed", "")
    assert "heroos can't proceed" not in card.message.lower()


def test_a_caution_under_review_is_never_stated_as_law(artifacts: Artifacts) -> None:
    evaluation = run(
        artifacts.snapshot(),
        {"employee_aware_of_relevant_policy": "no"},
        topics=("workplace_reminder",),
    )
    card = outcome(evaluation)
    assert card is not None and card.kind == "warning" and PROVISIONAL in card.message


def test_several_steps_keep_their_own_lines(artifacts: Artifacts) -> None:
    card = outcome(run(artifacts.snapshot(), READY, "opt-dismissal", "opt-investigative"))
    assert card is not None and card.kind == "expert_review"
    assert [i.kind for i in card.items] == ["expert_review", "guidance"]


def test_technical_unavailability_is_not_an_outcome() -> None:
    card = outcome(ConversationEvaluation(availability="incompatible_versions", matter="supported"))
    assert card is not None and card.kind == "unavailable" and card.items == ()
    view, texts = outcome_view(
        ConversationEvaluation(availability="incompatible_versions", matter="supported"), card
    )
    assert view == {"state": "checks_unavailable", "meaning": view["meaning"]} and texts == ()  # type: ignore[index]


def test_the_safe_next_step_is_never_a_sanction() -> None:
    for text in NEXT_STEPS.values():
        lowered = text.lower()
        for sanction in ("dismiss", "terminate", "fire ", "suspend", "deduct", "issue a warning"):
            assert sanction not in lowered


@pytest.mark.parametrize(
    ("disposition", "text", "problem"),
    [
        ("block", "You can go ahead and dismiss them.", "contradicts_hold"),
        ("block", "You may proceed.", "contradicts_hold"),
        ("block", "It's fine to go ahead with the dismissal.", "contradicts_hold"),
        ("escalate", "No specialist review is needed.", "contradicts_review"),
        ("escalate", "You don't need any specialist review for this.", "contradicts_review"),
        ("escalate", "Expert review isn't required here.", "contradicts_review"),
        ("warn", "There's nothing you need to address.", "contradicts_caution"),
        ("warn", "You're all clear.", "contradicts_caution"),
        ("warn", "No concerns apply here.", "contradicts_caution"),
    ],
)
def test_a_reply_undoing_the_outcome_is_caught(disposition: str, text: str, problem: str) -> None:
    assert outcome_contradiction([text], held(disposition)) == problem


@pytest.mark.parametrize(
    ("disposition", "text"),
    [
        ("escalate", "You can go ahead with the investigation meeting while you wait for review."),
        ("escalate", "Don't take this step without specialist review."),
        ("block", "Once the employee has been heard, you can decide what happens next."),
        ("warn", "There's one caution to address before you decide."),
        ("allow", "You can go ahead and talk to him about it."),
    ],
)
def test_a_reply_explaining_the_outcome_passes(disposition: str, text: str) -> None:
    assert outcome_contradiction([text], held(disposition)) is None


def test_the_fallback_keeps_the_deterministic_result(artifacts: Artifacts) -> None:
    evaluation = run(artifacts.snapshot(), READY, "opt-dismissal")
    card = outcome(evaluation)
    text = fallback_reply(evaluation, card, lead="", question="What happened?", provider_note=True)
    assert "couldn't put together a fuller reply" in text
    assert card is not None and card.message in text and text.endswith("What happened?")
