"""From a turn to its Case: the threshold, the title and which facts may enter it (pure)."""

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.assistant.gateway.service import Handoff
from app.conversations.bridge import case_definition, case_title, fact_changes
from app.evaluation.model import ConversationEvaluation, FactSource, TrustedFactState, Value
from app.evaluation.snapshot import FactSchema
from app.workflows.definition import DISCIPLINARY_V2, Option
from tests.fixtures.evaluation import PROBATION, Artifacts

POLICY = "employee_aware_of_relevant_policy"
QUESTION = "context.policy_awareness"
STEPS = ("initial_facts", "incident_context")
TODAY = date(2026, 10, 22)


def handoff(**overrides: Any) -> Handoff:
    fields: dict[str, Any] = {
        "intent": "supported_hr",
        "workflow": "disciplinary",
        "pathway_candidate": None,
        "topics": (),
        "established": (),
        "tentative": (),
        "uncertainties": (),
        "summary": None,
        "knowledge_status": None,
        "jurisdiction": None,
        "review_required": (),
        "asked": (),
        "runtime_bundle_digest": None,
    }
    return Handoff(**{**fields, **overrides})


def evaluation(
    engine: dict[str, Value] | None = None,
    sources: dict[str, FactSource] | None = None,
    **overrides: Any,
) -> ConversationEvaluation:
    facts = TrustedFactState(engine=engine or {}, sources=sources or {})
    fields: dict[str, Any] = {
        "availability": "ready",
        "matter": "supported",
        "workflow": "disciplinary",
        "facts": facts,
    }
    return ConversationEvaluation(**{**fields, **overrides})


# --- the threshold ------------------------------------------------------------------------------


def test_a_supported_matter_of_an_established_workflow_becomes_a_case() -> None:
    found = case_definition(evaluation(), handoff(), conversation_workflow=None, has_case=False)
    assert found is DISCIPLINARY_V2
    # Even while the deterministic checks are unavailable: the workflow is established.
    unavailable = evaluation(availability="execution_profile_missing")
    assert case_definition(unavailable, handoff(), conversation_workflow=None, has_case=False)


@pytest.mark.parametrize(
    ("result", "context", "kwargs"),
    [
        (evaluation(matter="unclear", workflow=None), handoff(), {}),
        (evaluation(matter="unsupported_hr", workflow=None), handoff(), {}),
        (evaluation(matter="outside_product_scope", workflow=None), handoff(), {}),
        (evaluation(matter="confidential_request", workflow=None), handoff(), {}),
        (evaluation(multiple_matters=True), handoff(), {}),
        (evaluation(), handoff(uncertainties=("multiple_matters",)), {}),
        (evaluation(workflow=PROBATION), handoff(), {}),
        (evaluation(), handoff(), {"has_case": True}),
        (evaluation(), handoff(), {"conversation_workflow": PROBATION}),
        (None, handoff(), {}),
    ],
    ids=[
        "unclear",
        "other_hr",
        "not_hr",
        "confidential",
        "several_matters",
        "several_matters_unevaluated",
        "no_definition",
        "already_has_a_case",
        "another_workflow",
        "no_evaluation",
    ],
)
def test_anything_else_stays_a_conversation(
    result: ConversationEvaluation | None, context: Handoff, kwargs: dict[str, Any]
) -> None:
    arguments = {"conversation_workflow": None, "has_case": False, **kwargs}
    assert case_definition(result, context, **arguments) is None


# --- the title ------------------------------------------------------------------------------------


def test_a_title_is_a_neutral_matter_label_or_the_workflow_and_date() -> None:
    assert case_title(handoff(topics=("misconduct_level",)), DISCIPLINARY_V2, TODAY) == (
        "Conduct concern"
    )
    # A topic about an employer decision or sanction never becomes a title.
    for topics in (("dismissal_without_notice",), ("salary_deduction",), ()):
        assert case_title(handoff(topics=topics), DISCIPLINARY_V2, TODAY) == (
            "Disciplinary case · 22 Oct"
        )
    # Nor the AI's pathway candidate or summary.
    named = handoff(pathway_candidate="serious", summary="[SYNTHETIC] Ahmed took cash")
    assert case_title(named, DISCIPLINARY_V2, TODAY) == "Disciplinary case · 22 Oct"


# --- the facts ------------------------------------------------------------------------------------


@pytest.fixture
def execution(artifacts: Artifacts) -> Any:
    found = artifacts.snapshot().execution("disciplinary")
    assert found is not None
    return found


def test_a_newly_trusted_canonical_value_becomes_a_case_fact(execution: Any) -> None:
    for source in ("direct_answer", "confirmation"):
        result = evaluation({POLICY: "yes"}, {POLICY: source})  # type: ignore[dict-item]
        changes = fact_changes(
            result,
            execution,
            DISCIPLINARY_V2,
            current={},
            open_steps=STEPS,
            from_case=frozenset(),
            today=TODAY,
        )
        assert changes == {QUESTION: "yes"}


@pytest.mark.parametrize(
    ("engine", "sources", "current", "steps", "from_case"),
    [
        # A Blueprint value is context, never a Case fact.
        ({POLICY: "yes"}, {POLICY: "blueprint"}, {}, STEPS, ()),
        # The Case's own value, carried into the turn.
        ({POLICY: "yes"}, {POLICY: "continuation"}, {}, STEPS, (POLICY,)),
        # Unchanged: never stored again.
        ({POLICY: "yes"}, {POLICY: "direct_answer"}, {QUESTION: "yes"}, STEPS, ()),
        # A conversation-control fact with no Case question.
        ({"proposed_suspension_days": 20}, {"proposed_suspension_days": "confirmation"}, {},
         STEPS, ()),
        # Not an option of the question.
        ({POLICY: "maybe"}, {POLICY: "direct_answer"}, {}, STEPS, ()),
    ],
    ids=["blueprint", "from_case", "unchanged", "no_question", "not_an_option"],
)  # fmt: skip
def test_nothing_else_becomes_a_case_fact(
    execution: Any,
    engine: dict[str, Value],
    sources: dict[str, FactSource],
    current: dict[str, object],
    steps: tuple[str, ...],
    from_case: tuple[str, ...],
) -> None:
    changes = fact_changes(
        evaluation(engine, sources),
        execution,
        DISCIPLINARY_V2,
        current=current,
        open_steps=steps,
        from_case=frozenset(from_case),
        today=TODAY,
    )
    assert changes == {}


def test_an_earlier_turns_trusted_fact_is_saved_once_a_case_exists(execution: Any) -> None:
    changes = fact_changes(
        evaluation({POLICY: "no"}, {POLICY: "continuation"}),
        execution,
        DISCIPLINARY_V2,
        current={},
        open_steps=STEPS,
        from_case=frozenset(),
        today=TODAY,
    )
    assert changes == {QUESTION: "no"}


def test_the_forms_own_validator_decides_and_sensitive_questions_never_qualify() -> None:
    documented = (Option("yes", "Yes"), Option("verbal_only", "No"), Option("not_sure", "?"))
    fake = SimpleNamespace(
        schemas={
            "documented": FactSchema(
                "documented",
                "Documented",
                "choice",
                documented,
                question="history.documented_action",
            ),
            "complaint": FactSchema(
                "complaint", "Complaint", "yes_no", (), question="screening.recent_complaint"
            ),
        }
    )
    result = evaluation(
        {"documented": "yes", "complaint": "yes"},
        {"documented": "direct_answer", "complaint": "direct_answer"},
    )
    steps = (*STEPS, "safety_screening")

    def changes(current: dict[str, object]) -> dict[str, str]:
        return fact_changes(
            result,
            fake,  # type: ignore[arg-type]
            DISCIPLINARY_V2,
            current=current,
            open_steps=steps,
            from_case=frozenset(),
            today=TODAY,
        )

    # Asked only after an earlier raised issue (AskWhen), exactly like the form.
    assert changes({}) == {}
    assert changes({"incident.history": "raised_before"}) == {"history.documented_action": "yes"}
