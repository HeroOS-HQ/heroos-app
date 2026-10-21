"""The real knowledge and execution profile, locally only (skipped in CI: they're never there).

Run on the server that holds the private artifacts:

    KNOWLEDGE_BUNDLE=/path/knowledge.json EXECUTION_PROFILE=/path/profile.json \\
        uv run pytest tests/evaluation/test_real_runtime.py

(The variables must not start with ``HEROOS_``: tests/conftest.py clears those.)
Generic checks only, by the public option kinds: no library identifier, rule
number or wording appears in this repository.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from app.evaluation.evaluator import EvaluationRequest, evaluate_conversation
from app.evaluation.model import TrustedFactState
from app.evaluation.profile import load_execution_profile
from app.evaluation.snapshot import ExecutionSnapshot, build_snapshot, coverage_matrix
from app.knowledge.bundle import load_knowledge_bundle
from app.workflows.definition import WORKFLOWS

KNOWLEDGE = os.environ.get("KNOWLEDGE_BUNDLE")
PROFILE = os.environ.get("EXECUTION_PROFILE")

pytestmark = pytest.mark.skipif(
    not (KNOWLEDGE and PROFILE), reason="the private artifacts are only on the content server"
)


@pytest.fixture(scope="module")
def snapshot() -> ExecutionSnapshot:
    assert KNOWLEDGE and PROFILE
    knowledge_path, profile_path = Path(KNOWLEDGE), Path(PROFILE)
    knowledge = load_knowledge_bundle(
        knowledge_path, hashlib.sha256(knowledge_path.read_bytes()).hexdigest(), production=False
    )
    profile = load_execution_profile(
        profile_path, hashlib.sha256(profile_path.read_bytes()).hexdigest(), production=False
    )
    return build_snapshot(knowledge, profile, {}, WORKFLOWS)


def option(snapshot: ExecutionSnapshot, kind: str) -> str:
    execution = snapshot.workflows["disciplinary"]
    return next(o.id for o in execution.options.values() if o.kind == kind)


def disposition(snapshot: ExecutionSnapshot, kind: str, jurisdiction: str) -> str:
    action = option(snapshot, kind)
    evaluation = evaluate_conversation(
        snapshot,
        EvaluationRequest(
            matter="supported",
            workflow="disciplinary",
            company_jurisdiction=jurisdiction,
            facts=TrustedFactState(),
            requested=(action,),
        ),
    )
    return evaluation.actions[0].disposition


def test_the_real_pairing_is_compatible(snapshot: ExecutionSnapshot) -> None:
    assert snapshot.availability("disciplinary") == "ready", dict(snapshot.unavailable)


def test_every_condition_has_one_category_and_nothing_disabled_runs(
    snapshot: ExecutionSnapshot,
) -> None:
    execution = snapshot.workflows["disciplinary"]
    rows = coverage_matrix(execution)
    assert len(rows) == len(execution.conditions)
    for row in rows:
        if row["enforcement_status"] != "active":
            assert row["category"] == "not_enforced" and row["executor"] is None
        if row["category"] == "executable":
            assert row["enforcement_status"] == "active"


@pytest.mark.parametrize("jurisdiction", ["uae_federal", "difc"])
def test_review_boundaries_hold_whatever_the_facts(
    snapshot: ExecutionSnapshot, jurisdiction: str
) -> None:
    assert disposition(snapshot, "dismissal_without_notice", jurisdiction) == "escalate"
    assert disposition(snapshot, "salary_deduction", jurisdiction) == "escalate"


def test_difc_unpaid_disciplinary_suspension_needs_review(snapshot: ExecutionSnapshot) -> None:
    assert disposition(snapshot, "disciplinary_suspension_unpaid", "difc") == "escalate"
    assert option(snapshot, "disciplinary_suspension_unpaid") != option(
        snapshot, "investigative_suspension"
    )


def test_a_supported_step_is_never_clear_without_executable_coverage(
    snapshot: ExecutionSnapshot,
) -> None:
    execution = snapshot.workflows["disciplinary"]
    for found in execution.options.values():
        if found.jurisdictions["uae_federal"].availability != "supported":
            continue
        result = disposition(snapshot, found.kind, "uae_federal")
        assert result != "allow" or found.id in execution.covered, found.kind


def test_the_difc_investigation_is_guidance(snapshot: ExecutionSnapshot) -> None:
    execution = snapshot.workflows["disciplinary"]
    topics = tuple(
        t.key
        for t in execution.knowledge.topics
        if t.workflow == "disciplinary" and "serious" in t.pathways and not t.options
    )
    evaluation = evaluate_conversation(
        snapshot,
        EvaluationRequest(
            matter="supported",
            workflow="disciplinary",
            company_jurisdiction="difc",
            topics=topics,
        ),
    )
    assert evaluation.presentation == "guidance" and evaluation.reviews == ()


def test_sensitive_inputs_are_a_privacy_gap_never_a_finding(snapshot: ExecutionSnapshot) -> None:
    execution = snapshot.workflows["disciplinary"]
    for condition_id, reason in execution.incapable.items():
        assert reason in ("privacy_capability_unavailable", "input_not_collectable")
        assert execution.categories[condition_id] == "executable"


def test_deterministic(snapshot: ExecutionSnapshot) -> None:
    request = EvaluationRequest(
        matter="supported",
        workflow="disciplinary",
        company_jurisdiction="uae_federal",
        requested=(
            option(snapshot, "written_warning"),
            option(snapshot, "dismissal_without_notice"),
        ),
    )
    first = json.dumps(evaluate_conversation(snapshot, request).record(), sort_keys=True)
    assert all(
        json.dumps(evaluate_conversation(snapshot, request).record(), sort_keys=True) == first
        for _ in range(5)
    )
