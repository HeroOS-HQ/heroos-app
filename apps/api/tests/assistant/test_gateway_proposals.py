"""Strict validation of what the model proposes (M2-NEW-05), on the fictional bundle's catalog.

Covers: the routing catalog comes from the installed bundle only; unknown
or unresolved routes; fact keys, provenance, turns and excerpts; the founder's
words as the only evidence; and the response object's closed shape.
"""

import json
from typing import Any

import pytest

from app.assistant.gateway.catalog import routing_catalog
from app.assistant.gateway.proposals import (
    MAX_REPLY_CHARS,
    ProposalError,
    check_evidence,
    parse_response,
    parse_understanding,
)
from app.knowledge.bundle import KnowledgeBundle
from tests.fixtures.gateway import fact, response, understanding

MESSAGES = [
    "One of my staff was late on Monday and Tuesday.",
    "I already explained the standard to him last week.",
]


def parse(bundle: KnowledgeBundle, data: dict[str, Any] | str, current: int = 1) -> Any:
    text = data if isinstance(data, str) else json.dumps(data)
    return parse_understanding(text, routing_catalog(bundle), current_turn=current)


def code(bundle: KnowledgeBundle, data: dict[str, Any] | str, current: int = 1) -> str:
    with pytest.raises(ProposalError) as error:
        parse(bundle, data, current)
    return error.value.code


# --- the catalog ----------------------------------------------------------------------


def test_the_catalog_is_the_installed_bundle_and_nothing_else(bundle: KnowledgeBundle) -> None:
    catalog = routing_catalog(bundle)
    view = catalog.model_view()
    assert [w["key"] for w in view["supported_workflows"]] == ["disciplinary"]  # type: ignore[index]
    workflow = catalog.workflow("disciplinary")
    assert workflow is not None
    assert [p.key for p in workflow.pathways] == ["less_serious", "serious"]
    assert {t.key for t in workflow.topics} == {t.key for t in bundle.topics}
    for unpublished in ("probation", "recruitment", "performance"):
        assert unpublished not in json.dumps(view)
    # Only keys, titles and labels: no ids, sources, digests or content.
    flat = json.dumps(view)
    for private in ("EX0", "EX-", "rule-", bundle.runtime_digest, "source", "sha256"):
        assert private not in flat


def test_the_catalog_never_offers_sensitive_blueprint_or_jurisdiction_facts(
    bundle: KnowledgeBundle,
) -> None:
    facts = routing_catalog(bundle).facts
    assert "employment_jurisdiction" not in facts  # only the Blueprint's confirmation counts
    assert "headcount" not in facts  # the Blueprint holds it
    assert "dismissal_without_notice_considered" not in facts  # sensitive
    assert "given_opportunity_to_explain" in facts


# --- routes ---------------------------------------------------------------------------


def test_a_valid_understanding_is_accepted(bundle: KnowledgeBundle) -> None:
    proposal = parse(
        bundle,
        understanding(
            pathway="less_serious",
            topics=["workplace_reminder"],
            facts=[
                fact("employee_aware_of_relevant_policy", "yes", "explained the standard", turn=1)
            ],
            uncertainties=["approximate_details"],
            summary="[SYNTHETIC] Lateness on two days.",
        ),
    )
    assert proposal.workflow == "disciplinary" and proposal.pathway == "less_serious"
    assert proposal.topics == ("workplace_reminder",)
    assert proposal.facts[0].establishes


@pytest.mark.parametrize("intent", ["unclear", "other_hr", "unsupported", "confidential_request"])
def test_an_unresolved_route_is_valid(bundle: KnowledgeBundle, intent: str) -> None:
    proposal = parse(bundle, understanding(intent=intent))
    assert proposal.workflow is None and proposal.pathway is None and proposal.topics == ()


def test_supported_without_a_workflow_is_valid_and_stays_unresolved(
    bundle: KnowledgeBundle,
) -> None:
    assert parse(bundle, understanding(workflow=None)).workflow is None


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"workflow_candidate": "probation"}, "unknown_workflow"),
        ({"workflow_candidate": "recruitment"}, "unknown_workflow"),
        ({"pathway_candidate": "gross_misconduct"}, "unknown_pathway"),
        ({"topics": ["workplace_reminder", "workplace_reminder"]}, "duplicate_value"),
        ({"topics": ["deadlines", "formal_warning", "penalty_notice", "workplace_reminder"]},
         "too_many"),
        ({"intent": "hr"}, "unknown_value"),
        ({"intent": "other_hr"}, "inconsistent_intent"),
        ({"uncertainties": ["guilty"]}, "unknown_value"),
        ({"schema_version": "heroos.understanding/2"}, "unknown_schema"),
        ({"case_summary": "x" * 301}, "bad_length"),
        ({"condition_candidates": ["EX-FED-CAP"]}, "unknown_field"),
        ({"final_outcome": "block"}, "unknown_field"),
        ({"sanction": "written_warning"}, "unknown_field"),
        ({"jurisdiction": "difc"}, "unknown_field"),
    ],
)  # fmt: skip
def test_unknown_or_unauthorized_content_is_refused(
    bundle: KnowledgeBundle, change: dict[str, Any], expected: str
) -> None:
    data = understanding(pathway="less_serious") | change
    assert code(bundle, data) == expected


def test_a_topic_outside_the_catalog_is_left_out_never_failing_the_turn(
    bundle: KnowledgeBundle,
) -> None:
    """Live dev-stack run: a model's own word for the matter ("absenteeism") is a hint, unused."""
    data = understanding(pathway="less_serious", topics=["absenteeism", "workplace_reminder"])
    assert parse(bundle, data).topics == ("workplace_reminder",)
    assert parse(bundle, understanding(pathway="less_serious", topics=[42])).topics == ()


def test_a_pathway_without_a_workflow_is_refused(bundle: KnowledgeBundle) -> None:
    data = understanding(workflow=None) | {"pathway_candidate": "serious"}
    assert code(bundle, data) == "unknown_pathway"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("not json", "invalid_json"),
        ("[]", "expected_object"),
        ('{"a": 1, "a": 2}', "duplicate_key"),
        ('{"schema_version": NaN}', "invalid_number"),
        ("{}", "missing_field"),
    ],
)
def test_malformed_output_is_refused(bundle: KnowledgeBundle, text: str, expected: str) -> None:
    assert code(bundle, text) == expected


# --- facts ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"provenance": "assistant_message"}, "unknown_value"),
        ({"provenance": "general_knowledge"}, "unknown_value"),
        ({"provenance": "web"}, "unknown_value"),
        ({"confidence": 0.9}, "unknown_value"),
        ({"confidence": "certain"}, "unknown_value"),
        ({"explicit_or_inferred": "assumed"}, "unknown_value"),
        ({"support_excerpt": "x" * 161}, "bad_length"),
        ({"proposed_value": ""}, "bad_length"),
        ({"proposed_value": "a\u0000b"}, "control_character"),
        ({"reasoning": "because"}, "unknown_field"),
    ],
)
def test_a_fact_proposal_must_have_the_exact_evidence_shape(
    bundle: KnowledgeBundle, change: dict[str, Any], expected: str
) -> None:
    proposal = fact("given_opportunity_to_explain", "yes", "explained", turn=1) | change
    assert code(bundle, understanding(facts=[proposal])) == expected


@pytest.mark.parametrize(
    "change",
    [
        {"source_turn": 5},
        {"source_turn": -1},
        {"source_turn": True},
        {"source_turn": None},
        {"provenance": "company_blueprint", "source_turn": 0},
    ],
)
def test_a_fact_citing_no_founder_message_is_left_out(
    bundle: KnowledgeBundle, change: dict[str, Any]
) -> None:
    """Its words can't be checked against any message, so it is dropped, not the whole turn."""
    kept = fact("employee_aware_of_relevant_policy", "yes", "explained the standard", turn=1)
    proposal = fact("given_opportunity_to_explain", "yes", "explained", turn=1) | change
    facts = parse(bundle, understanding(facts=[proposal, kept])).facts
    assert [f.fact_key for f in facts] == ["employee_aware_of_relevant_policy"]


@pytest.mark.parametrize(
    ("provenance", "turn", "expected"),
    [
        ("prior_user_message", 1, "current_user_message"),
        ("current_user_message", 0, "prior_user_message"),
    ],
)
def test_a_founder_facts_provenance_follows_the_turn_it_cites(
    bundle: KnowledgeBundle, provenance: str, turn: int, expected: str
) -> None:
    """The evidence check then looks for the excerpt in exactly that message."""
    proposal = fact("given_opportunity_to_explain", "yes", "explained", turn=turn)
    proposal |= {"provenance": provenance}
    (parsed,) = parse(bundle, understanding(facts=[proposal])).facts
    assert (parsed.provenance, parsed.source_turn) == (expected, turn)


def _checked(bundle: KnowledgeBundle, *facts: dict[str, Any], blueprint: str = "") -> Any:
    proposal = parse(bundle, understanding(facts=list(facts)))
    return check_evidence(proposal, routing_catalog(bundle), MESSAGES, blueprint)


def test_only_facts_the_founders_own_words_support_are_kept(bundle: KnowledgeBundle) -> None:
    kept, dropped = _checked(
        bundle,
        fact(
            "employee_aware_of_relevant_policy", "yes", "I already EXPLAINED the  standard", turn=1
        ),
        # Not in that message (it is in the other one).
        fact("misconduct_level", "minor", "late on Monday", turn=1),
        # Words the founder never wrote.
        fact("investigation_completed", "yes", "the investigation is complete", turn=1),
        # A key the bundle doesn't know, or a sensitive one, is never accepted.
        fact("repeated_misconduct", "yes", "already explained", turn=1),
        fact("dismissal_without_notice_considered", "yes", "already explained", turn=1),
    )
    assert [f.fact_key for f in kept.facts] == ["employee_aware_of_relevant_policy"]
    assert dropped == 4


def test_a_bare_answer_answers_only_the_question_heroos_just_asked(bundle: KnowledgeBundle) -> None:
    """Found live: an earlier "Yes" (to one question) was read as the answer to the next one."""
    policy = "employee_aware_of_relevant_policy"
    reading = fact(policy, "yes", "Yes", turn=1)
    context = fact("misconduct_level", "minor", "late again", turn=0)
    catalog = routing_catalog(bundle)

    def kept(messages: list[str], answering: str | None) -> list[str]:
        proposal = parse(bundle, understanding(facts=[reading, context]))
        checked, _ = check_evidence(proposal, catalog, messages, "", answering=answering)
        return [f.fact_key for f in checked.facts]

    late = "My employee has been late again."
    # The answer to the question HeroOS just asked, in the current message: kept.
    assert kept([late, "Yes."], policy) == [policy, "misconduct_level"]
    # Not what HeroOS asked, or an earlier message: no evidence of which question it answers.
    assert kept([late, "Yes."], None) == ["misconduct_level"]
    assert kept([late, "Yes.", "What now?"], policy) == ["misconduct_level"]


def test_an_earlier_founder_message_can_be_cited(bundle: KnowledgeBundle) -> None:
    kept, dropped = _checked(
        bundle,
        fact("misconduct_level", "minor", "late on Monday and Tuesday", turn=0,
             provenance="prior_user_message"),
    )  # fmt: skip
    assert dropped == 0 and kept.facts[0].source_turn == 0


def test_a_blueprint_fact_must_be_in_the_blueprint_view(bundle: KnowledgeBundle) -> None:
    blueprint_fact = fact(
        "policy_timeframe", "ten working days", "appeals within ten working days",
        turn=None, provenance="company_blueprint",
    )  # fmt: skip
    kept, dropped = _checked(bundle, blueprint_fact)
    assert kept.facts == () and dropped == 1
    kept, dropped = _checked(
        bundle, blueprint_fact, blueprint="Our handbook: appeals within ten working days."
    )
    assert dropped == 0 and kept.facts[0].provenance == "company_blueprint"


@pytest.mark.parametrize(
    ("basis", "confidence", "establishes"),
    [("explicit", "high", True), ("explicit", "medium", True), ("explicit", "low", False),
     # Said, but imprecise ("last week"): never a known value, however confident.
     ("approximate", "high", False), ("approximate", "medium", False),
     ("inferred", "high", False)],
)  # fmt: skip
def test_only_an_explicit_confident_statement_establishes_a_fact(
    bundle: KnowledgeBundle, basis: str, confidence: str, establishes: bool
) -> None:
    proposal = parse(
        bundle,
        understanding(
            facts=[fact("misconduct_level", "minor", "late", basis=basis, confidence=confidence)]
        ),
        current=0,
    )
    assert proposal.facts[0].establishes is establishes


# --- the grounded response ------------------------------------------------------------


def test_a_valid_response_is_accepted() -> None:
    parsed = parse_response(json.dumps(response("Hello.", ["q1"], "Write down the dates.")), ["q1"])
    assert parsed.reply == "Hello." and parsed.target_ids == ("q1",)
    assert parsed.safe_next_step == "Write down the dates."
    minimal = parse_response(
        json.dumps({"schema_version": "heroos.response/1", "reply": "Hi."}), []
    )
    assert minimal.target_ids == () and minimal.safe_next_step is None


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (response("Hi.", ["q3"]), "unknown_target"),
        (response("Hi.", ["employee_aware_of_relevant_policy"]), "unknown_target"),
        (response(""), "bad_length"),
        (response("x" * (MAX_REPLY_CHARS + 1)), "bad_length"),
        (response("Hi.", step="x" * 301), "bad_length"),
        (response("Hi.") | {"status": "supported"}, "unknown_field"),
        (response("Hi.") | {"outcome": "block"}, "unknown_field"),
        (response("Hi.") | {"review_required": True}, "unknown_field"),
        (response("Hi.") | {"jurisdiction": "difc"}, "unknown_field"),
        (response("Hi.") | {"knowledge_refs": ["EX01"]}, "unknown_field"),
        (response("Hi.") | {"schema_version": "x"}, "unknown_schema"),
    ],
)
def test_the_response_has_no_room_for_outcomes_or_references(
    data: dict[str, Any], expected: str
) -> None:
    with pytest.raises(ProposalError) as error:
        parse_response(json.dumps(data), ["q1"])
    assert error.value.code == expected


def test_the_sentence_around_an_excerpt_is_the_founders_whole_sentence() -> None:
    from app.assistant.gateway.proposals import FactProposal, sentence_of

    messages = [
        "Hi. I think her manager gave her a verbal warning once, but I'd need to check! Thanks",
    ]
    proposal = FactProposal(
        "verbal_warnings_reported", "yes", "high", "current_user_message", 0,
        "gave her a verbal warning once", "explicit",
    )  # fmt: skip
    assert sentence_of(messages, proposal) == (
        " i think her manager gave her a verbal warning once, but i'd need to check"
    )
    missing = FactProposal(
        "verbal_warnings_reported", "yes", "high", "current_user_message", 0, "not there",
        "explicit",
    )  # fmt: skip
    assert sentence_of(messages, missing) == "not there"


@pytest.mark.parametrize(
    ("words", "answering", "otherwise"),
    [
        # Only "don't know" (plus filler) is a bare answer: it answers the question just asked.
        ("No idea, I'd have to check.", True, False),
        ("not sure tbh", True, False),
        # Saying what they don't know stands on its own.
        ("I wasn't there, my manager might know", True, True),
        # Another answer is never "not sure" about the question asked.
        ("i havent said anything to her yet", False, False),
        ("No, nobody has heard from him.", False, False),
    ],
)
def test_not_sure_is_kept_only_from_words_that_say_so(
    bundle: KnowledgeBundle, words: str, answering: bool, otherwise: bool
) -> None:
    catalog = routing_catalog(bundle)
    key = "employee_aware_of_relevant_policy"
    proposal = parse(bundle, understanding(facts=[fact(key, "not_sure", words)]), current=0)
    asked, _ = check_evidence(proposal, catalog, [words], "", answering=key)
    unasked, _ = check_evidence(proposal, catalog, [words], "")
    assert (bool(asked.facts), bool(unasked.facts)) == (answering, otherwise)
