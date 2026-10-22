"""The conversation checkpoint: bounded codes, never trusted blindly, rebuilt from the records."""

from dataclasses import replace
from typing import Any

import pytest

from app.assistant.gateway.service import snapshot_versions
from app.conversations.checkpoint import (
    SCHEMA,
    CaseView,
    Checkpoint,
    Resumed,
    Reviews,
    case_backed,
    decode,
    encode,
    next_checkpoint,
    resume,
)
from app.evaluation.continuation import ContinuationState, ReadResult
from app.evaluation.facts import Asked
from app.evaluation.model import TwoState
from app.evaluation.snapshot import ExecutionSnapshot
from app.workflows.conditions import Tri
from tests.fixtures.evaluation import PROBATION, Artifacts

POLICY = "employee_aware_of_relevant_policy"
QUESTION = "context.policy_awareness"
CAP = "fictional_cap"


@pytest.fixture
def snapshot(artifacts: Artifacts) -> ExecutionSnapshot:
    return artifacts.snapshot()


def trusted_state(**overrides: Any) -> ContinuationState:
    return replace(
        ContinuationState(
            workflow="disciplinary",
            asked=(Asked("confirm", "proposed_suspension_days", 20),),
            engine={"given_opportunity_to_explain": "yes", "proposed_suspension_days": 20},
            jurisdiction="confirmed",
            two_state={CAP: TwoState(CAP, True, True, Tri.UNKNOWN)},
            reconfirm=False,
            actions=("opt-suspension",),
        ),
        **overrides,
    )


def stored(snapshot: ExecutionSnapshot, **overrides: Any) -> dict[str, object]:
    return encode(Checkpoint(snapshot_versions(snapshot), trusted_state(**overrides)))


def test_a_checkpoint_round_trips_as_plain_bounded_codes(snapshot: ExecutionSnapshot) -> None:
    checkpoint = Checkpoint(
        snapshot_versions(snapshot), trusted_state(), voided=(POLICY,), case_revision=3
    )
    data = encode(checkpoint)
    assert data["schema"] == SCHEMA
    assert decode(data) == checkpoint
    assert decode(encode(Checkpoint(""))) == Checkpoint("")


@pytest.mark.parametrize(
    "change",
    [
        {"schema": "heroos.assistant-checkpoint/0"},
        {"versions": None},
        {"engine": {"given_opportunity_to_explain": True}},
        {"engine": {"given_opportunity_to_explain": 1.5}},
        {"engine": {"x": "a value with spaces"}},
        {"asked": [["guess", "x"]]},
        {"asked": [["fact", "a"], ["fact", "b"], ["fact", "c"]]},
        {"two_state": {CAP: [True, True]}},
        {"two_state": {CAP: [True, True, "maybe"]}},
        {"jurisdiction": "somewhere"},
        {"reconfirm": "no"},
        {"actions": ["a", "b", "c", "d"]},
        {"voided": [f"k{i}" for i in range(30)]},
        {"case_revision": "1"},
        {"case_revision": True},
    ],
)
def test_anything_it_cant_vouch_for_is_rejected(
    snapshot: ExecutionSnapshot, change: dict[str, object]
) -> None:
    assert decode({**stored(snapshot), **change}) is None


@pytest.mark.parametrize("data", [None, [], "x", {"schema": SCHEMA}])
def test_a_malformed_document_is_rejected(data: object) -> None:
    assert decode(data) is None


def test_only_collectable_case_questions_back_facts(snapshot: ExecutionSnapshot) -> None:
    execution = snapshot.execution("disciplinary")
    assert execution is not None
    # Never the jurisdiction (the gate owns it), a sensitive question or a Blueprint value.
    assert case_backed(execution) == {POLICY: QUESTION}


def test_a_new_conversation_starts_with_nothing(snapshot: ExecutionSnapshot) -> None:
    resumed = resume(snapshot, stored=None, workflow=None, case=None, company_jurisdiction=None)
    assert resumed == Resumed(ReadResult(None, "missing", True))


def test_a_trusted_checkpoint_is_the_next_turns_start(snapshot: ExecutionSnapshot) -> None:
    resumed = resume(
        snapshot,
        stored=stored(snapshot),
        workflow="disciplinary",
        case=None,
        company_jurisdiction=None,
    )
    assert resumed.read == ReadResult(trusted_state(), None, True)
    assert not resumed.rebuilt and resumed.from_case == frozenset()


def test_the_cases_facts_are_authoritative(snapshot: ExecutionSnapshot) -> None:
    resumed = resume(
        snapshot,
        stored=stored(snapshot, engine={POLICY: "yes", "proposed_suspension_days": 20}),
        workflow="disciplinary",
        case=CaseView({QUESTION: "no", "incident.narrative": "[SYNTHETIC] text"}, {QUESTION: 2}),
        company_jurisdiction=None,
    )
    assert resumed.read.state is not None
    assert resumed.read.state.engine == {POLICY: "no", "proposed_suspension_days": 20}
    assert resumed.from_case == {POLICY}


def test_a_case_value_outside_the_schema_is_never_trusted(snapshot: ExecutionSnapshot) -> None:
    resumed = resume(
        snapshot,
        stored=stored(snapshot, engine={}),
        workflow="disciplinary",
        case=CaseView({QUESTION: "maybe"}, {QUESTION: 1}),
        company_jurisdiction=None,
    )
    assert resumed.read.state is not None and resumed.read.state.engine == {}


@pytest.mark.parametrize(
    "untrusted",
    [
        {"versions": "other-knowledge|other-profile"},
        {"schema": "tampered"},
        {"workflow": PROBATION},
    ],
    ids=["other_versions", "unknown_schema", "other_workflow"],
)
def test_an_untrusted_checkpoint_is_rebuilt_and_the_rest_reconfirmed(
    snapshot: ExecutionSnapshot, untrusted: dict[str, object]
) -> None:
    resumed = resume(
        snapshot,
        stored={**stored(snapshot), **untrusted},
        workflow="disciplinary",
        case=CaseView({QUESTION: "yes"}, {QUESTION: 1}),
        company_jurisdiction=None,
    )
    assert resumed.rebuilt
    # The workflow and the Case's facts are rebuilt; what HeroOS asked, cautions and
    # conversation-only facts are confirmed again.
    assert resumed.read == ReadResult(
        ContinuationState(workflow="disciplinary", engine={POLICY: "yes"}, reconfirm=True),
        None,
        True,
    )


def test_a_voided_case_fact_stays_out_until_the_case_holds_a_newer_one(
    snapshot: ExecutionSnapshot,
) -> None:
    voided = encode(
        Checkpoint(snapshot_versions(snapshot), trusted_state(), voided=(POLICY,), case_revision=2)
    )

    def resumed(revision: int, data: dict[str, object] = voided) -> Resumed:
        return resume(
            snapshot,
            stored=data,
            workflow="disciplinary",
            case=CaseView({QUESTION: "no"}, {QUESTION: revision}),
            company_jurisdiction=None,
        )

    still = resumed(2)
    assert still.read.state is not None and POLICY not in still.read.state.engine
    assert still.voided == {POLICY} and still.from_case == frozenset()
    # Even from a checkpoint that is otherwise rebuilt (stricter only).
    rebuilt = resumed(2, {**voided, "versions": "other"})
    assert rebuilt.rebuilt and rebuilt.read.state is not None
    assert POLICY not in rebuilt.read.state.engine
    # The form saved a newer answer since: trusted again.
    newer = resumed(3)
    assert newer.read.state is not None and newer.read.state.engine[POLICY] == "no"


def test_the_next_checkpoint_keeps_no_copy_of_what_the_case_holds(
    snapshot: ExecutionSnapshot,
) -> None:
    after = trusted_state(engine={POLICY: "yes", "proposed_suspension_days": 20})
    resumed = Resumed(ReadResult(after, None, True), from_case=frozenset({POLICY}))
    checkpoint = next_checkpoint(
        snapshot,
        after,
        resumed=resumed,
        workflow="disciplinary",
        case_answers={QUESTION: "yes"},
        case_revision=4,
        company_jurisdiction=None,
        reviews=Reviews(),
    )
    assert checkpoint.state.engine == {"proposed_suspension_days": 20}
    assert (checkpoint.voided, checkpoint.case_revision) == ((), 4)
    assert checkpoint.versions == snapshot_versions(snapshot)
    # Before a Case exists the checkpoint keeps every trusted fact.
    before = next_checkpoint(
        snapshot,
        after,
        resumed=resumed,
        workflow=None,
        case_answers=None,
        case_revision=None,
        company_jurisdiction=None,
        reviews=Reviews(),
    )
    assert before.state.engine == after.engine


def test_a_case_fact_the_founder_contradicted_is_voided(snapshot: ExecutionSnapshot) -> None:
    after = trusted_state(engine={"proposed_suspension_days": 20})
    resumed = Resumed(ReadResult(after, None, True), from_case=frozenset({POLICY}))
    checkpoint = next_checkpoint(
        snapshot,
        after,
        resumed=resumed,
        workflow="disciplinary",
        case_answers={QUESTION: "no"},
        case_revision=2,
        company_jurisdiction=None,
        reviews=Reviews(),
    )
    assert checkpoint.voided == (POLICY,)
