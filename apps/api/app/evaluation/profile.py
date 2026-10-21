"""Execution profiles: which content and execution artifacts are approved to operate together.

An execution profile (``heroos.execution-profile/1``) is **not another rules
source**. It holds compatibility and binding metadata only:

- per workflow, the exact knowledge runtime (M2-NEW-04 ``runtime_bundle_digest``),
  workflow definition version and rule bundle (id, version and content digest,
  or none) it was approved with;
- the executors that may run (``intake``: the public intake rule set, pinned
  by its version and digest; ``rule_bundle``: the conversation rules of that
  rule bundle);
- the **explicit bindings** from a knowledge Condition to a rule of one of
  those executors. Nothing is ever bound by name similarity, and no Condition
  is executed from its text;
- the employer decisions whose deterministic coverage is complete, and which
  rule establishes each mandatory prerequisite the approved content requires
  (the employee's response, a completed investigation);
- who owns the workflow's pathway (``pathway_ownership``).

It has no field for wording, thresholds, guidance, Condition text or a rule
predicate, and none can be added: the schema is exact. The real profile binds
private Condition ids and stays private like the bundles it pairs; a fictional
one tests the mechanism.

Loading contract (``load_execution_profile``), fail-closed like every bundle:
read once at startup, SHA-256 pin, strict schema, no duplicate keys; a
synthetic or development profile is refused in production. Whether the
installed artifacts actually match is checked when the execution snapshot is
built (``app.evaluation.snapshot``): a mismatch makes deterministic evaluation
unavailable, never silently stale.
"""

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from app.evaluation.model import PathwayOwnership

SCHEMA: Final = "heroos.execution-profile/1"
MAX_PROFILE_BYTES: Final = 256 * 1024
MAX_WORKFLOWS: Final = 8
MAX_BINDINGS: Final = 300
MAX_ACTIONS: Final = 60

PROFILE_ID: Final = re.compile(r"^[a-z][a-z0-9-]{0,49}$")
VERSION: Final = re.compile(r"^[a-z0-9][a-z0-9.-]{0,49}$")
WORKFLOW_KEY: Final = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
ITEM_ID: Final = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,79}$")
RULE_KEY: Final = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
EXECUTOR: Final = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
SHA256_HEX: Final = re.compile(r"^[0-9a-f]{64}$")
OWNERSHIP: Final[tuple[PathwayOwnership, ...]] = (
    "ai_candidate_only", "employer_confirmation_required", "deterministic", "none",
)  # fmt: skip
# The mandatory prerequisites the approved content flags on an employer decision.
PREREQUISITES: Final = ("employee_response", "completed_investigation")

Provenance = Literal["synthetic", "private"]
Approval = Literal["development", "approved"]


class ExecutionProfileError(ValueError):
    """The profile is refused. ``code`` is fixed; ``location`` is structural only."""

    def __init__(self, code: str, location: str = "") -> None:
        self.code = code
        self.location = location
        suffix = f" at {location}" if location else ""
        super().__init__(f"execution profile refused: {code}{suffix}")


@dataclass(frozen=True, slots=True)
class RuleBundleRef:
    bundle: str
    version: str
    digest: str


@dataclass(frozen=True, slots=True)
class ExecutorRef:
    # "intake", "rule_bundle", or a name this code doesn't know (unsupported at runtime).
    executor: str
    version: str | None
    digest: str | None


@dataclass(frozen=True, slots=True)
class Binding:
    condition: str
    executor: str
    rule: str


@dataclass(frozen=True, slots=True)
class CoveredAction:
    action: str
    # Prerequisite (employee_response, completed_investigation) -> the action rule establishing it.
    prerequisites: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class WorkflowProfile:
    workflow: str
    knowledge_runtime_digest: str
    definition_version: int
    rule_bundle: RuleBundleRef | None
    executors: tuple[ExecutorRef, ...]
    pathway_ownership: PathwayOwnership
    bindings: tuple[Binding, ...]
    covered_actions: tuple[CoveredAction, ...]

    def executor(self, name: str) -> ExecutorRef | None:
        return next((e for e in self.executors if e.executor == name), None)

    def covered(self, action: str) -> CoveredAction | None:
        return next((a for a in self.covered_actions if a.action == action), None)


@dataclass(frozen=True, slots=True)
class ExecutionProfile:
    profile: str
    version: str
    provenance: Provenance
    approval: Approval
    workflows: tuple[WorkflowProfile, ...]
    # SHA-256 of the canonical content.
    digest: str
    # SHA-256 of the file as deployed (the configured pin).
    file_sha256: str

    def workflow(self, key: str) -> WorkflowProfile | None:
        return next((w for w in self.workflows if w.workflow == key), None)


# --- parsing -------------------------------------------------------------------------------


def _object(
    raw: object, where: str, required: set[str], optional: frozenset[str] = frozenset()
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ExecutionProfileError("expected_object", where)
    keys = set(raw)
    if not required <= keys:
        raise ExecutionProfileError("missing_field", where)
    if not keys <= required | optional:
        raise ExecutionProfileError("unknown_field", where)
    return raw


def _match(raw: object, pattern: re.Pattern[str], where: str) -> str:
    if not isinstance(raw, str) or not pattern.fullmatch(raw):
        raise ExecutionProfileError("invalid_value", where)
    return raw


def _optional(raw: object, pattern: re.Pattern[str], where: str) -> str | None:
    return None if raw is None else _match(raw, pattern, where)


def _list(raw: object, where: str, limit: int) -> list[object]:
    if not isinstance(raw, list) or len(raw) > limit:
        raise ExecutionProfileError("invalid_list", where)
    return raw


def _code[T: str](raw: object, allowed: tuple[T, ...], where: str) -> T:
    if not isinstance(raw, str) or raw not in allowed:
        raise ExecutionProfileError("invalid_code", where)
    return raw


def _workflow(raw: object, where: str) -> WorkflowProfile:
    data = _object(
        raw,
        where,
        {
            "workflow", "knowledge_runtime_digest", "definition_version", "rule_bundle",
            "executors", "pathway_ownership", "bindings", "covered_actions",
        },
    )  # fmt: skip
    version = data["definition_version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ExecutionProfileError("invalid_value", f"{where}.definition_version")
    bundle_ref = None
    if data["rule_bundle"] is not None:
        ref = _object(data["rule_bundle"], f"{where}.rule_bundle", {"bundle", "version", "digest"})
        bundle_ref = RuleBundleRef(
            _match(ref["bundle"], PROFILE_ID, f"{where}.rule_bundle.bundle"),
            _match(ref["version"], VERSION, f"{where}.rule_bundle.version"),
            _match(ref["digest"], SHA256_HEX, f"{where}.rule_bundle.digest"),
        )
    executors = []
    for i, item in enumerate(_list(data["executors"], f"{where}.executors", 8)):
        at = f"{where}.executors[{i}]"
        entry = _object(item, at, {"executor"}, frozenset({"version", "digest"}))
        executors.append(
            ExecutorRef(
                _match(entry["executor"], EXECUTOR, f"{at}.executor"),
                _optional(entry.get("version"), VERSION, f"{at}.version"),
                _optional(entry.get("digest"), SHA256_HEX, f"{at}.digest"),
            )
        )
    if len({e.executor for e in executors}) != len(executors):
        raise ExecutionProfileError("duplicate_executor", f"{where}.executors")
    bindings = []
    for i, item in enumerate(_list(data["bindings"], f"{where}.bindings", MAX_BINDINGS)):
        at = f"{where}.bindings[{i}]"
        entry = _object(item, at, {"condition", "executor", "rule"})
        bindings.append(
            Binding(
                _match(entry["condition"], ITEM_ID, f"{at}.condition"),
                _match(entry["executor"], EXECUTOR, f"{at}.executor"),
                _match(entry["rule"], RULE_KEY, f"{at}.rule"),
            )
        )
    if len({b.condition for b in bindings}) != len(bindings):
        # One Condition, one binding: never two rules deciding the same Condition.
        raise ExecutionProfileError("duplicate_binding", f"{where}.bindings")
    covered = []
    for i, item in enumerate(
        _list(data["covered_actions"], f"{where}.covered_actions", MAX_ACTIONS)
    ):
        at = f"{where}.covered_actions[{i}]"
        entry = _object(item, at, {"action", "prerequisites"})
        raw_prerequisites = entry["prerequisites"]
        if not isinstance(raw_prerequisites, dict):
            raise ExecutionProfileError("expected_object", f"{at}.prerequisites")
        prerequisites = {
            _code(name, PREREQUISITES, f"{at}.prerequisites"): _match(
                rule, RULE_KEY, f"{at}.prerequisites.{name}"
            )
            for name, rule in raw_prerequisites.items()
        }
        covered.append(
            CoveredAction(_match(entry["action"], ITEM_ID, f"{at}.action"), prerequisites)
        )
    if len({a.action for a in covered}) != len(covered):
        raise ExecutionProfileError("duplicate_action", f"{where}.covered_actions")
    return WorkflowProfile(
        workflow=_match(data["workflow"], WORKFLOW_KEY, f"{where}.workflow"),
        knowledge_runtime_digest=_match(
            data["knowledge_runtime_digest"], SHA256_HEX, f"{where}.knowledge_runtime_digest"
        ),
        definition_version=version,
        rule_bundle=bundle_ref,
        executors=tuple(executors),
        pathway_ownership=_code(data["pathway_ownership"], OWNERSHIP, f"{where}.pathway_ownership"),
        bindings=tuple(bindings),
        covered_actions=tuple(covered),
    )


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise ExecutionProfileError("duplicate_json_key")
        data[key] = value
    return data


def _no_constants(_: str) -> object:
    raise ExecutionProfileError("invalid_json_number")


def parse_execution_profile(content: bytes, *, file_sha256: str) -> ExecutionProfile:
    """Validate a profile's bytes against the schema (structure only; compatibility is separate)."""
    if len(content) > MAX_PROFILE_BYTES:
        raise ExecutionProfileError("too_large")
    try:
        raw = json.loads(
            content.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constants
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExecutionProfileError("invalid_json") from error
    data = _object(
        raw, "$", {"schema", "profile", "version", "provenance", "approval", "workflows"}
    )
    if data["schema"] != SCHEMA:
        raise ExecutionProfileError("unsupported_schema", "$.schema")
    workflows = tuple(
        _workflow(item, f"$.workflows[{i}]")
        for i, item in enumerate(_list(data["workflows"], "$.workflows", MAX_WORKFLOWS))
    )
    if not workflows or len({w.workflow for w in workflows}) != len(workflows):
        raise ExecutionProfileError("invalid_workflows", "$.workflows")
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return ExecutionProfile(
        profile=_match(data["profile"], PROFILE_ID, "$.profile"),
        version=_match(data["version"], VERSION, "$.version"),
        provenance=_code(data["provenance"], ("synthetic", "private"), "$.provenance"),
        approval=_code(data["approval"], ("development", "approved"), "$.approval"),
        workflows=workflows,
        digest=hashlib.sha256(canonical.encode()).hexdigest(),
        file_sha256=file_sha256,
    )


def load_execution_profile(
    path: Path, expected_sha256: str, *, production: bool
) -> ExecutionProfile:
    """Read, verify against the pin, validate; never falls back (``ExecutionProfileError``)."""
    if not SHA256_HEX.fullmatch(expected_sha256):
        raise ExecutionProfileError("invalid_pin")
    try:
        with path.open("rb") as handle:
            content = handle.read(MAX_PROFILE_BYTES + 1)
    except OSError as error:
        raise ExecutionProfileError("unreadable") from error
    if len(content) > MAX_PROFILE_BYTES:
        raise ExecutionProfileError("too_large")
    actual = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(actual, expected_sha256):
        raise ExecutionProfileError("checksum_mismatch")
    profile = parse_execution_profile(content, file_sha256=actual)
    if production and profile.provenance == "synthetic":
        raise ExecutionProfileError("synthetic_in_production")
    if production and profile.approval != "approved":
        raise ExecutionProfileError("unapproved_in_production")
    return profile
