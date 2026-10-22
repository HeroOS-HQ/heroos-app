"""M2-NEW-08: an employer decision's prerequisites may read the Case's formal record.

The fictional penalty notice (``opt-outcome``, UAE Federal) needs a completed
meeting or check-in stage, and that stage's checklist answer that the employee
was heard: the Case's own records, never the founder's words. They apply only
under the jurisdiction the Case's progression runs under. A decision asked
about hypothetically is evaluated the same way and marked so, and is never
asked whether the employer "still intends" it.
"""

from typing import Any

import pytest

from app.evaluation.evaluator import EvaluationRequest, evaluate_conversation
from app.evaluation.model import CaseProgress, TrustedFactState, TwoState
from app.evaluation.presentation import CASE_STEP_NOTE, NEXT_STEPS, outcome, outcome_view
from app.workflows.conditions import Tri
from tests.fixtures.evaluation import Artifacts

FED, DIFC = "uae_federal", "difc"
MEETING = frozenset({"test_notice", "test_meeting"})
HEARD = {"progress.test_meeting.meeting_held": "yes"}


def evaluate(artifacts: Artifacts, **request: Any) -> Any:
    base: dict[str, Any] = {
        "matter": "supported",
        "workflow": "disciplinary",
        "company_jurisdiction": FED,
        "clarification": "confirmed",
        "requested": ("opt-outcome",),
    }
    return evaluate_conversation(artifacts.snapshot(), EvaluationRequest(**{**base, **request}))


@pytest.mark.parametrize(
    ("progress", "disposition"),
    [
        (None, "block"),  # no Case: no stage is completed, nothing is known
        (CaseProgress(FED), "block"),
        (CaseProgress(FED, MEETING), "block"),  # investigated, but not heard
        (CaseProgress(FED, frozenset(), HEARD), "block"),  # heard, but no completed stage
        (CaseProgress(FED, MEETING, HEARD), "allow"),
        # The same records under another jurisdiction never count here.
        (CaseProgress(DIFC, MEETING, HEARD), "block"),
        (CaseProgress(None, MEETING, HEARD), "block"),
    ],
    ids=["no_case", "nothing", "no_response", "no_stage", "recorded", "other", "unresolved"],
)
def test_only_the_cases_own_record_in_its_jurisdiction_satisfies_a_case_step(
    artifacts: Artifacts, progress: CaseProgress | None, disposition: str
) -> None:
    evaluation = evaluate(artifacts, progress=progress)
    (action,) = evaluation.actions
    assert action.disposition == disposition
    if disposition == "block":
        assert action.next_step == "complete_case_step"
        # A checklist answer is the Case's to record: never a question for the chat.
        assert action.missing == ()
        assert not [m for m in evaluation.missing if m.key.startswith("progress.")]
        assert evaluation.next_step == "complete_case_step"
        card = outcome(evaluation)
        assert card is not None and CASE_STEP_NOTE in card.message
    record = evaluation.record()
    assert record["case_progress"] == (
        None
        if progress is None
        else {
            "jurisdiction": progress.jurisdiction,
            "applied": progress.jurisdiction == FED,
            "completed": sorted(progress.completed),
            "checklist_answers": len(progress.checklist),
        }
    )


def test_the_founders_words_never_satisfy_a_case_step(artifacts: Artifacts) -> None:
    # Even an ENGINE_TRUSTED "the investigation is complete" is not the Case's record.
    facts = TrustedFactState(
        engine={"investigation_completed": "yes", "given_opportunity_to_explain": "yes"},
        sources={
            "investigation_completed": "direct_answer",
            "given_opportunity_to_explain": "direct_answer",
        },
    )
    (action,) = evaluate(artifacts, facts=facts, progress=CaseProgress(FED)).actions
    assert action.disposition == "block" and action.next_step == "complete_case_step"


def test_a_complete_case_step_is_said_plainly(artifacts: Artifacts) -> None:
    assert "case's own workflow stages" in NEXT_STEPS["complete_case_step"]
    assert "not from the chat" in NEXT_STEPS["complete_case_step"]


def test_a_what_if_is_evaluated_marked_and_never_asked_about_intention(
    artifacts: Artifacts,
) -> None:
    facts = TrustedFactState(
        engine={
            "proposed_suspension_days": 20,
            "investigation_completed": "yes",
            "given_opportunity_to_explain": "yes",
        },
        sources=dict.fromkeys(
            ("proposed_suspension_days", "investigation_completed", "given_opportunity_to_explain"),
            "direct_answer",
        ),
    )
    hypothetical = evaluate(
        artifacts,
        requested=(),
        hypothetical=("opt-suspension",),
        facts=facts,
        topics=("disciplinary_suspension",),
    )
    (action,) = hypothetical.actions
    assert action.hypothetical is True and action.disposition == "warn"
    # The cap's caution applies, but "do you still intend to go ahead?" is never asked of a
    # "what if".
    assert not [m for m in hypothetical.missing if m.kind == "insistence"]
    assert hypothetical.record()["actions"][0]["hypothetical"] is True
    view, _ = outcome_view(hypothetical, outcome(hypothetical))
    assert view is not None and view["steps"][0]["asked"] == "hypothetically"

    intended = evaluate(
        artifacts,
        requested=("opt-suspension",),
        facts=facts,
        topics=("disciplinary_suspension",),
    )
    (action,) = intended.actions
    assert action.hypothetical is False
    assert [m.kind for m in intended.missing] == ["insistence"]
    # Asked both ways in one message, the intention wins.
    both = evaluate(
        artifacts,
        requested=("opt-suspension",),
        hypothetical=("opt-suspension",),
        facts=facts,
        topics=("disciplinary_suspension",),
        two_state={"fictional_cap": TwoState("fictional_cap", True, True, Tri.FALSE)},
    )
    assert [a.hypothetical for a in both.actions] == [False]
