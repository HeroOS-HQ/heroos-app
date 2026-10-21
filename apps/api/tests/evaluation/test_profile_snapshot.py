"""Execution profiles, version compatibility, explicit bindings, coverage and snapshots (M2-NEW-06).

The profile is compatibility and binding metadata only, pinned like every
bundle. A snapshot is built only from artifacts the profile approves together;
anything else makes that workflow's evaluation unavailable, never stale. A
Condition is executable only through an explicit, verified binding.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.evaluation.profile import (
    ExecutionProfileError,
    load_execution_profile,
    parse_execution_profile,
)
from app.evaluation.snapshot import (
    ExecutionRuntime,
    build_snapshot,
    coverage_matrix,
    knowledge_only_runtime,
)
from tests.fixtures.evaluation import (
    DEFINITIONS,
    PROBATION,
    Artifacts,
    knowledge,
    profile,
    rule_bundle,
    to_bytes,
)


def _pinned(tmp_path: Path, data: dict[str, Any]) -> tuple[Path, str]:
    path = tmp_path / "profile.json"
    path.write_bytes(to_bytes(data))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _workflow(artifacts: Artifacts, key: str = "disciplinary") -> dict[str, Any]:
    entry: dict[str, Any] = next(w for w in artifacts.profile["workflows"] if w["workflow"] == key)
    return entry


# --- the profile: metadata only, strict, pinned -------------------------------------------------


def test_a_profile_holds_only_identities_and_bindings(artifacts: Artifacts) -> None:
    loaded = profile(artifacts.profile)
    assert loaded.provenance == "synthetic" and len(loaded.digest) == 64
    # There is nowhere to put wording, a threshold, guidance or a predicate.
    for field in (
        "message",
        "text",
        "guidance",
        "trigger",
        "when",
        "require",
        "threshold",
        "title",
    ):
        data = json.loads(json.dumps(artifacts.profile))
        data["workflows"][0][field] = "anything"
        with pytest.raises(ExecutionProfileError) as refused:
            profile(data)
        assert refused.value.code == "unknown_field"
    binding = json.loads(json.dumps(artifacts.profile))
    binding["workflows"][0]["bindings"][0]["when"] = {"answer": "x", "in": ["yes"]}
    with pytest.raises(ExecutionProfileError, match="unknown_field"):
        profile(binding)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda d: d.update(schema="heroos.execution-profile/2"), "unsupported_schema"),
        (lambda d: d["workflows"].append(d["workflows"][0]), "invalid_workflows"),
        (lambda d: d.update(workflows=[]), "invalid_workflows"),
        (
            lambda d: d["workflows"][0]["bindings"].append(d["workflows"][0]["bindings"][0]),
            "duplicate_binding",
        ),
        (lambda d: d["workflows"][0].update(pathway_ownership="model"), "invalid_code"),
        (lambda d: d["workflows"][0].update(knowledge_runtime_digest="abc"), "invalid_value"),
        (
            lambda d: d["workflows"][0]["covered_actions"][0]["prerequisites"].update(x="y"),
            "invalid_code",
        ),
    ],
)
def test_a_malformed_profile_is_refused(artifacts: Artifacts, change: Any, code: str) -> None:
    data = json.loads(json.dumps(artifacts.profile))
    change(data)
    with pytest.raises(ExecutionProfileError) as refused:
        profile(data)
    assert refused.value.code == code


def test_duplicate_json_keys_and_constants_are_refused() -> None:
    for content in (b'{"schema": 1, "schema": 2}', b'{"schema": NaN}'):
        with pytest.raises(ExecutionProfileError):
            parse_execution_profile(content, file_sha256="0" * 64)


def test_the_pin_and_production_rules(tmp_path: Path, artifacts: Artifacts) -> None:
    path, pin = _pinned(tmp_path, artifacts.profile)
    assert load_execution_profile(path, pin, production=False).profile == "synthetic-execution"
    with pytest.raises(ExecutionProfileError, match="checksum_mismatch"):
        load_execution_profile(path, "0" * 64, production=False)
    with pytest.raises(ExecutionProfileError, match="invalid_pin"):
        load_execution_profile(path, "x", production=False)
    with pytest.raises(ExecutionProfileError, match="synthetic_in_production"):
        load_execution_profile(path, pin, production=True)
    private = dict(artifacts.profile, provenance="private")
    path, pin = _pinned(tmp_path, private)
    with pytest.raises(ExecutionProfileError, match="unapproved_in_production"):
        load_execution_profile(path, pin, production=True)


# --- compatibility: fail closed, never stale -------------------------------------------------


def test_compatible_artifacts_build_a_ready_snapshot(artifacts: Artifacts) -> None:
    snapshot = artifacts.snapshot()
    assert set(snapshot.workflows) == {"disciplinary", PROBATION}
    assert snapshot.availability("disciplinary") == "ready"
    assert len(snapshot.id) == 16


@pytest.mark.parametrize(
    ("change", "availability", "code"),
    [
        (
            lambda a: _workflow(a).update(knowledge_runtime_digest="f" * 64),
            "incompatible_versions",
            "knowledge_digest_mismatch",
        ),
        (
            lambda a: _workflow(a).update(definition_version=1),
            "incompatible_versions",
            "definition_version_mismatch",
        ),
        (
            lambda a: _workflow(a)["rule_bundle"].update(digest="e" * 64),
            "incompatible_versions",
            "rule_bundle_mismatch",
        ),
        (
            lambda a: _workflow(a)["rule_bundle"].update(version="synthetic.2"),
            "incompatible_versions",
            "rule_bundle_mismatch",
        ),
        (
            lambda a: _workflow(a)["executors"][0].update(digest="d" * 64),
            "incompatible_versions",
            "executor_version_mismatch",
        ),
        (
            lambda a: _workflow(a)["executors"].append({"executor": "lisp_engine"}),
            "unsupported_executor",
            "unsupported_executor",
        ),
        (
            lambda a: _workflow(a)["bindings"].append(
                {
                    "condition": "EX-FED-OLD-DEDUCTION",
                    "executor": "rule_bundle",
                    "rule": "fictional_cap",
                }
            ),
            "incompatible_versions",
            "not_enforced_condition_bound",
        ),
        (
            lambda a: _workflow(a)["bindings"].append(
                {"condition": "EX-NOPE", "executor": "rule_bundle", "rule": "fictional_cap"}
            ),
            "incompatible_versions",
            "unknown_condition",
        ),
        (
            lambda a: _workflow(a)["bindings"].append(
                {
                    "condition": "EX-FED-PAY-CAUTION",
                    "executor": "rule_bundle",
                    "rule": "no_such_rule",
                }
            ),
            "incompatible_versions",
            "unknown_rule",
        ),
        # An intake rule runs only where the approved knowledge links it to that Condition.
        (
            lambda a: _workflow(a)["bindings"].append(
                {
                    "condition": "EX-FED-PAY-CAUTION",
                    "executor": "intake",
                    "rule": "policy_awareness",
                }
            ),
            "incompatible_versions",
            "not_an_engine_link",
        ),
        # A covered decision with a safeguard nothing can execute: refused.
        (
            lambda a: _workflow(a)["covered_actions"].append(
                {"action": "opt-reminder", "prerequisites": {}}
            ),
            "incompatible_versions",
            "prerequisite_not_bound",
        ),
        (
            lambda a: _workflow(a)["covered_actions"].append(
                {"action": "opt-nope", "prerequisites": {}}
            ),
            "incompatible_versions",
            "unknown_action",
        ),
    ],
)
def test_any_mismatch_makes_that_workflow_unavailable(
    artifacts: Artifacts, change: Any, availability: str, code: str
) -> None:
    change(artifacts)
    snapshot = artifacts.snapshot()
    assert snapshot.execution("disciplinary") is None
    assert snapshot.unavailable["disciplinary"] == (availability, (code,))
    assert snapshot.availability("disciplinary") == availability
    # The other workflow's compatibility is its own.
    assert snapshot.availability(PROBATION) == "ready"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (
            lambda rule: rule.update(
                action="block", follow_up={"action": "escalate", "when": "employer_insists"}
            ),
            "action_mismatch",
        ),
        (lambda rule: rule.pop("follow_up"), "follow_up_mismatch"),
        (lambda rule: rule.update(provisional=True), "review_status_mismatch"),
    ],
)
def test_a_bound_rule_must_agree_with_its_condition(
    artifacts: Artifacts, change: Any, code: str
) -> None:
    """Same action, follow-up and review status as the approved Condition, or nothing runs."""
    change(artifacts.disciplinary["conversation"]["jurisdictions"]["uae_federal"]["rules"][0])
    artifacts.repin()
    assert artifacts.snapshot().unavailable["disciplinary"] == ("incompatible_versions", (code,))


def test_missing_artifacts_are_technical_states(artifacts: Artifacts) -> None:
    rules = {
        "disciplinary": rule_bundle(artifacts.disciplinary),
        PROBATION: rule_bundle(artifacts.probation),
    }
    snapshot = build_snapshot(None, profile(artifacts.profile), rules, DEFINITIONS)
    assert snapshot.availability("disciplinary") == "knowledge_bundle_missing"
    snapshot = build_snapshot(knowledge(artifacts.knowledge), None, rules, DEFINITIONS)
    assert snapshot.availability("disciplinary") == "execution_profile_missing"
    snapshot = build_snapshot(
        knowledge(artifacts.knowledge),
        profile(artifacts.profile),
        {PROBATION: rules[PROBATION]},
        DEFINITIONS,
    )
    assert snapshot.availability("disciplinary") == "rule_bundle_missing"
    assert knowledge_only_runtime(None).current().availability("disciplinary") == (
        "knowledge_bundle_missing"
    )


# --- coverage: one category per Condition, nothing guessed -----------------------------------


def test_every_condition_has_exactly_one_execution_category(artifacts: Artifacts) -> None:
    snapshot = artifacts.snapshot()
    disciplinary = {
        r["condition"]: r["category"] for r in coverage_matrix(snapshot.workflows["disciplinary"])
    }
    assert disciplinary == {
        # The global routing precondition: the jurisdiction gate.
        "EX-ROUTING-1": "guard_only",
        # Explicit bindings, one to the public intake rule its engine link names.
        "EX-FED-POLICY": "executable",
        "EX-FED-CAP": "executable",
        "EX-FED-WARNING-LABEL": "executable",
        # Every decision they guard is already held for review by the approved availability.
        "EX-FED-ESCALATE": "guard_only",
        "EX-DIFC-SUSPENSION": "guard_only",
        "EX-SHARED-DEDUCTION": "guard_only",
        # Nothing executable can say they fired.
        "EX-FED-PAY-CAUTION": "question_only",
        "EX-DIFC-DEADLINE": "question_only",
        "EX-FED-OLD-DEDUCTION": "not_enforced",
    }
    probation = {
        r["condition"]: r["category"] for r in coverage_matrix(snapshot.workflows[PROBATION])
    }
    assert probation["SP-OLD"] == "not_enforced"
    assert {
        probation[c] for c in ("SP-EXTENSION-CAP", "SP-TRIAL-OVERRUN", "SP-CONCERNS", "SP-MEETING")
    } == {"executable"}


def test_a_quarantined_condition_never_executes(artifacts: Artifacts) -> None:
    artifacts.knowledge["runtime"]["quarantine"].append(
        {
            "kind": "condition",
            "id": "EX-FED-PAY-CAUTION",
            "reason": "source_conflict:test",
            "finding": artifacts.knowledge["runtime"]["quarantine"][0]["finding"],
        }
    )
    artifacts.repin()
    snapshot = artifacts.snapshot()
    rows = {r["condition"]: r for r in coverage_matrix(snapshot.workflows["disciplinary"])}
    assert rows["EX-FED-PAY-CAUTION"]["category"] == "quarantined"
    # Binding it is refused.
    _workflow(artifacts)["bindings"].append(
        {"condition": "EX-FED-PAY-CAUTION", "executor": "rule_bundle", "rule": "fictional_cap"}
    )
    assert artifacts.snapshot().unavailable["disciplinary"][1] == ("quarantined_condition_bound",)


def test_coverage_rows_carry_no_text(artifacts: Artifacts) -> None:
    rows = coverage_matrix(artifacts.snapshot().workflows["disciplinary"])
    assert set(rows[0]) == {
        "condition",
        "workflow",
        "jurisdiction",
        "enforcement_status",
        "citation_status",
        "action_policy",
        "category",
        "executor",
        "rule",
        "compatibility",
        "capability",
        "linked_actions",
    }
    assert "fictional trigger" not in json.dumps(rows)


# --- one immutable snapshot per turn ------------------------------------------------------------


def test_the_snapshot_is_immutable_and_indexed_once(artifacts: Artifacts) -> None:
    snapshot = artifacts.snapshot()
    execution = snapshot.workflows["disciplinary"]
    with pytest.raises(TypeError):
        execution.conditions["X"] = execution.conditions["EX-FED-CAP"]  # type: ignore[index]
    with pytest.raises(AttributeError):
        snapshot.id = "other"  # type: ignore[misc]
    assert ("opt-suspension", "uae_federal") in execution.option_conditions
    assert execution.schemas["proposed_suspension_days"].kind == "count"
    # The definition owns its options: a definition-backed fact keeps them.
    schema = execution.schemas["employee_aware_of_relevant_policy"]
    assert schema.kind == "yes_no" and schema.question == "context.policy_awareness"


def test_installing_a_new_snapshot_never_changes_the_one_a_turn_holds(artifacts: Artifacts) -> None:
    runtime = ExecutionRuntime(artifacts.snapshot())
    held = runtime.current()
    _workflow(artifacts)["knowledge_runtime_digest"] = "f" * 64
    runtime.install(artifacts.snapshot())
    assert held.execution("disciplinary") is not None
    assert runtime.current().execution("disciplinary") is None
    assert held.id != runtime.current().id


def test_a_prerequisite_rule_has_no_follow_up(artifacts: Artifacts) -> None:
    """Two-state cautions come from approved Conditions; a prerequisite is a plain rule."""
    from app.workflows.progression.bundle import RuleBundleError

    actions = artifacts.disciplinary["conversation"]["jurisdictions"]["uae_federal"]["actions"]
    actions[0]["rules"][0]["follow_up"] = {"action": "escalate", "when": "employer_insists"}
    with pytest.raises(RuleBundleError, match="follow_up_on_prerequisite"):
        rule_bundle(artifacts.disciplinary)
