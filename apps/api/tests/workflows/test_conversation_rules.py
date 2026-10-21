"""The rule bundle's conversation section and numeric comparisons (M2-NEW-06).

Comparisons are three-valued like every predicate (anything but a whole
number is UNKNOWN) and allowed in conversation rules only. The section is
validated as strictly as the rest of the bundle.
"""

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest

from app.workflows.conditions import Tri
from app.workflows.progression import predicates
from app.workflows.progression.bundle import RuleBundleError, parse_bundle
from tests.fixtures.evaluation import disciplinary_rule_bundle


def parse(data: dict[str, Any]):  # type: ignore[no-untyped-def]
    content = json.dumps(data).encode()
    return parse_bundle(content, file_sha256=hashlib.sha256(content).hexdigest())


def context(**answers: object) -> predicates.Context:
    return predicates.Context(answers, frozenset())


@pytest.mark.parametrize(
    ("raw", "answers", "expected"),
    [
        ({"compare": "a", "op": "gt", "value": 9}, {"a": 10}, Tri.TRUE),
        ({"compare": "a", "op": "gt", "value": 9}, {"a": 9}, Tri.FALSE),
        ({"compare": "a", "op": "le", "value": 9}, {"a": 9}, Tri.TRUE),
        ({"compare": "a", "op": "gt", "value": 9}, {}, Tri.UNKNOWN),
        ({"compare": "a", "op": "gt", "value": 9}, {"a": "not_sure"}, Tri.UNKNOWN),
        ({"compare": "a", "op": "gt", "value": 9}, {"a": True}, Tri.UNKNOWN),
        ({"compare": "a", "op": "gt", "field": "b"}, {"a": 10, "b": 9}, Tri.TRUE),
        ({"compare": "a", "op": "gt", "field": "b"}, {"a": 10}, Tri.UNKNOWN),
        ({"not": {"compare": "a", "op": "eq", "value": 1}}, {}, Tri.UNKNOWN),
    ],
)
def test_comparisons_are_three_valued(raw: dict[str, Any], answers: dict[str, object],
                                      expected: Tri) -> None:  # fmt: skip
    predicate = predicates.parse(raw, "$", comparisons=True)
    assert predicates.evaluate(predicate, context(**answers)) is expected


def test_comparisons_name_their_inputs() -> None:
    predicate = predicates.parse({"compare": "a", "op": "gt", "field": "b"}, "$", comparisons=True)
    assert predicates.fact_keys(predicate) == ("a", "b")
    assert predicates.compared_keys(predicate) == ("a", "b")
    assert predicates.unknown_keys(predicate, context(a=1)) == ("b",)


@pytest.mark.parametrize(
    "raw",
    [
        {"compare": "a", "op": "between", "value": 1},
        {"compare": "a", "op": "gt"},
        {"compare": "a", "op": "gt", "value": 1, "field": "b"},
        {"compare": "a", "op": "gt", "value": 1.5},
        {"compare": "a", "op": "gt", "value": "9"},
        {"compare": "a", "op": "gt", "field": "a"},
        {"compare": "a", "op": "gt", "value": 10**9},
    ],
)
def test_malformed_comparisons_are_refused(raw: dict[str, Any]) -> None:
    with pytest.raises(predicates.PredicateError):
        predicates.parse(raw, "$", comparisons=True)


def test_a_stage_rule_never_compares_numbers() -> None:
    with pytest.raises(predicates.PredicateError):
        predicates.parse({"compare": "a", "op": "gt", "value": 1}, "$")
    data = disciplinary_rule_bundle()
    del data["conversation"]
    stage = data["jurisdictions"]["uae_federal"]["pathways"][0]["stages"][0]
    stage.setdefault("start_rules", []).append(
        {
            "key": "x_compare",
            "action": "warn",
            "when": {"compare": "x", "op": "gt", "value": 1},
            "provisional": False,
            "message": {"title": "T", "body": "B"},
        }  # fmt: skip
    )
    with pytest.raises(RuleBundleError, match="invalid_condition"):
        parse(data)


def test_the_conversation_section_parses_and_is_optional() -> None:
    bundle = parse(disciplinary_rule_bundle())
    assert bundle.conversation is not None
    program = bundle.conversation.jurisdictions["uae_federal"]
    rule = program.rule("fictional_cap")
    assert rule is not None and rule.follow_up is not None
    assert rule.follow_up.when == "employer_insists" and rule.follow_up.action == "block"
    assert set(program.actions) == {"opt-suspension", "opt-warning"}
    count = bundle.conversation.fact("proposed_suspension_days")
    assert count is not None and count.kind == "count" and count.maximum == 365
    without = disciplinary_rule_bundle()
    del without["conversation"]
    assert parse(without).conversation is None
    # The section is part of the content digest.
    assert parse(without).digest != bundle.digest


def _cap(data: dict[str, Any]) -> dict[str, Any]:
    rule: dict[str, Any] = data["conversation"]["jurisdictions"]["uae_federal"]["rules"][0]
    return rule


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (
            lambda d: d["conversation"]["facts"].append(
                {"key": "context.location", "kind": "yes_no"}
            ),
            "fact_shadows_question",
        ),
        (
            lambda d: d["conversation"]["facts"].append({"key": "x", "kind": "text"}),
            "invalid_fact_kind",
        ),
        (
            lambda d: d["conversation"]["facts"].append({"key": "x", "kind": "count", "max": 0}),
            "invalid_fact_kind",
        ),
        (
            lambda d: d["conversation"]["facts"].append({"key": "x", "kind": "choice"}),
            "invalid_fact_kind",
        ),
        (
            lambda d: d["conversation"]["facts"].append(d["conversation"]["facts"][0]),
            "duplicate_key",
        ),
        (
            lambda d: _cap(d).update(when={"answer": "screening.sick_leave", "in": ["yes"]}),
            "sensitive_answer_referenced",
        ),
        (
            lambda d: _cap(d).update(when={"answer": "nowhere", "in": ["yes"]}),
            "unknown_answer_referenced",
        ),
        (
            lambda d: _cap(d).update(
                when={"compare": "given_opportunity_to_explain", "op": "gt", "value": 1}
            ),
            "comparison_not_numeric",
        ),
        (
            lambda d: _cap(d).update(when={"stage_completed": "x"}),
            "stage_referenced_in_conversation",
        ),
        (
            lambda d: _cap(d).update(follow_up={"action": "warn", "when": "employer_insists"}),
            "invalid_follow_up",
        ),
        (
            lambda d: _cap(d).update(follow_up={"action": "block", "when": "condition_specific"}),
            "invalid_follow_up",
        ),
        (
            lambda d: _cap(d).update(follow_up={"action": "block", "when": "whenever"}),
            "invalid_follow_up",
        ),
        (
            lambda d: d["conversation"]["jurisdictions"]["uae_federal"]["rules"].append(
                deepcopy(_cap(d))
            ),
            "duplicate_rule",
        ),
        (
            lambda d: d["conversation"]["jurisdictions"].update(mars={"rules": [], "actions": []}),
            "unsupported_jurisdiction",
        ),
    ],  # fmt: skip
)
def test_the_conversation_section_is_strict(change: Any, code: str) -> None:
    data = disciplinary_rule_bundle()
    change(data)
    with pytest.raises(RuleBundleError) as refused:
        parse(data)
    assert refused.value.code == code
