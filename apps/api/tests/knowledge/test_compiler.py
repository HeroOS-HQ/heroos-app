"""The offline knowledge compiler, on the fictional package (M2-NEW-04).

Covers the source manifest and checksums, the two digests (deterministic,
and which changes move which), Conditions counts and action normalization,
document identity and the owner-approved normalization, broken mappings,
stale metadata, explicit supersession, jurisdiction scoping, coverage and the
compiler's refusals. Nothing here uses HeroOS content.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.knowledge.bundle import source_package_digest
from scripts.knowledge.__main__ import main
from scripts.knowledge.compiler import CompileResult, MappingError, compile_package
from scripts.knowledge.sources import inventory
from tests.fixtures.knowledge import synthetic


def _compile(tmp_path: Path, mapping: dict[str, Any] | None = None, **source: Any) -> CompileResult:
    sources = synthetic.write_sources(tmp_path / "package", **source)
    data = mapping if mapping is not None else synthetic.mapping(sources)
    return compile_package(sources, synthetic.write_mapping(tmp_path / "mapping.json", data))


def _codes(result: CompileResult, severity: str | None = None) -> set[tuple[str, str]]:
    return {
        (f.code, f.subject_id)
        for f in result.findings.items
        if severity is None or f.severity == severity
    }


def _runtime(result: CompileResult) -> dict[str, Any]:
    assert result.bundle is not None
    runtime: dict[str, Any] = result.bundle["runtime"]
    return runtime


def _item(result: CompileResult, collection: str, item_id: str) -> dict[str, Any]:
    return next(i for i in _runtime(result)[collection] if i["id"] == item_id)


# --- sources, manifest and digests ---------------------------------------------------------


def test_the_manifest_lists_every_source_with_its_exact_bytes(
    compiled: CompileResult, synthetic_sources: Path
) -> None:
    assert compiled.bundle is not None
    manifest = {m["source_id"]: m for m in compiled.bundle["manifest"]}
    assert set(manifest) == {"guide", "rules", "conditions", *synthetic.TEMPLATES}
    for entry in manifest.values():
        data = (synthetic_sources / entry["filename"]).read_bytes()
        assert entry["sha256"] == hashlib.sha256(data).hexdigest()
        assert entry["size"] == len(data)
        assert entry["runtime_role"] == "operational"
    assert compiled.bundle["source_package_digest"] == source_package_digest(
        compiled.bundle["manifest"]
    )
    assert compiled.report["source_package"]["files_missing"] == []


def test_inventory_is_sorted_and_never_follows_links(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "a.txt").write_text("a")
    assert [f.relative for f in inventory(tmp_path)] == ["a.txt", "b.txt"]
    (tmp_path / "link").symlink_to(tmp_path / "a.txt")
    with pytest.raises(ValueError, match="symbolic link"):
        inventory(tmp_path)


def test_two_runs_over_unchanged_sources_are_byte_identical(tmp_path: Path) -> None:
    first = _compile(tmp_path / "one")
    second = _compile(tmp_path / "two")
    assert first.bundle_bytes == second.bundle_bytes
    assert first.report == second.report


def test_compiling_never_changes_a_source_file(tmp_path: Path) -> None:
    sources = synthetic.write_sources(tmp_path / "package")
    before = {f.relative: f.sha256 for f in inventory(sources)}
    compile_package(
        sources, synthetic.write_mapping(tmp_path / "m.json", synthetic.mapping(sources))
    )
    assert {f.relative: f.sha256 for f in inventory(sources)} == before


def test_changed_operational_content_changes_both_digests(tmp_path: Path) -> None:
    base = _compile(tmp_path / "base")
    changed = [list(row) for row in synthetic.CONDITIONS]
    changed[1][5] = "Check the expected standard was explained, in writing."
    other = _compile(tmp_path / "changed", conditions=changed)
    assert base.bundle is not None and other.bundle is not None
    assert other.bundle["source_package_digest"] != base.bundle["source_package_digest"]
    assert other.bundle["runtime_bundle_digest"] != base.bundle["runtime_bundle_digest"]


def test_an_audit_only_change_changes_the_source_digest_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _compile(tmp_path / "base")
    original = synthetic.workbook_sheets

    def with_new_finding(conditions: Any = None) -> dict[str, list[list[str]]]:
        sheets = original(conditions)
        sheets["Structural Findings"] = [
            *sheets["Structural Findings"],
            ["2026-11", "Another one."],
        ]
        return sheets

    monkeypatch.setattr(synthetic, "workbook_sheets", with_new_finding)
    other = _compile(tmp_path / "audit")
    assert base.bundle is not None and other.bundle is not None
    assert other.bundle["source_package_digest"] != base.bundle["source_package_digest"]
    assert other.bundle["runtime_bundle_digest"] == base.bundle["runtime_bundle_digest"]


def test_a_missing_source_is_fatal_and_nothing_is_reconstructed(tmp_path: Path) -> None:
    sources = synthetic.write_sources(tmp_path / "package")
    data = synthetic.mapping(sources)
    (sources / synthetic.TEMPLATES["EX04"][0]).unlink()
    result = compile_package(sources, synthetic.write_mapping(tmp_path / "m.json", data))
    assert result.bundle is None
    assert ("MISSING_SOURCE", "EX04") in _codes(result, "FATAL")
    assert result.report["source_package"]["files_missing"] == [synthetic.TEMPLATES["EX04"][0]]


def test_a_source_changed_since_review_is_fatal(tmp_path: Path) -> None:
    sources = synthetic.write_sources(tmp_path / "package")
    data = synthetic.mapping(sources)
    synthetic.write_docx(
        sources / synthetic.TEMPLATES["EX01"][0], [synthetic._paragraph("Example Reminder")]
    )
    result = compile_package(sources, synthetic.write_mapping(tmp_path / "m.json", data))
    assert result.bundle is None
    assert ("SOURCE_CHANGED", "EX01") in _codes(result, "FATAL")


def test_an_unexpected_file_is_reported_and_not_used(tmp_path: Path) -> None:
    sources = synthetic.write_sources(tmp_path / "package")
    (sources / "notes.txt").write_text("x")
    result = compile_package(
        sources, synthetic.write_mapping(tmp_path / "m.json", synthetic.mapping(sources))
    )
    assert ("UNEXPECTED_SOURCE", "notes.txt") in _codes(result, "WARNING")
    assert result.bundle is not None


# --- Conditions ------------------------------------------------------------------------


def test_condition_counts_come_from_the_workbook(compiled: CompileResult) -> None:
    every = compiled.report["conditions"]["all"]
    assert every["total"] == 11
    assert every["by_workflow"] == {"disciplinary": 9, "global": 1, "probation": 1}
    assert every["by_jurisdiction"] == {"difc": 2, "global": 1, "shared": 1, "uae_federal": 7}
    assert every["by_enforcement_status"] == {"active": 10, "not_enforced": 1}
    assert every["by_citation_status"] == {"confirmed": 6, "needs_legal_review": 5}
    assert (every["active_confirmed"], every["active_needs_legal_review"]) == (5, 5)
    assert (every["not_enforced_confirmed"], every["not_enforced_needs_legal_review"]) == (1, 0)
    assert compiled.report["conditions"]["runtime_slice"]["total"] == 10
    assert compiled.report["conditions"]["outside_runtime_slice"] == ["EX-PROB-ONLY (probation)"]


def test_actions_are_normalized_into_a_policy_and_raw_values_kept(compiled: CompileResult) -> None:
    routing = _item(compiled, "conditions", "EX-ROUTING-1")
    assert routing["action_policy"] == {"initial": "block", "follow_up": None}
    assert routing["raw"]["action"] == "blocking"
    cap = _item(compiled, "conditions", "EX-FED-CAP")["action_policy"]
    assert (cap["initial"], cap["follow_up"]["action"], cap["follow_up"]["when"]) == (
        "warn",
        "block",
        "employer_insists",
    )
    timing = _item(compiled, "conditions", "EX-DIFC-DEADLINE")["action_policy"]
    assert (timing["follow_up"]["action"], timing["follow_up"]["when"]) == (
        "escalate",
        "condition_specific",
    )
    assert ("MALFORMED_ACTION", "EX-ROUTING-1") in _codes(compiled, "WARNING")


def test_needs_legal_review_keeps_its_action_and_is_reported(compiled: CompileResult) -> None:
    escalate = _item(compiled, "conditions", "EX-FED-ESCALATE")
    assert (escalate["citation_status"], escalate["enforcement_status"]) == (
        "needs_legal_review",
        "active",
    )
    assert escalate["action_policy"]["initial"] == "escalate"
    assert ("REVIEW_REQUIRED", "EX-FED-ESCALATE") in _codes(compiled, "REVIEW_REQUIRED")


def test_not_enforced_rows_stay_in_the_bundle_for_traceability(compiled: CompileResult) -> None:
    old = _item(compiled, "conditions", "EX-FED-OLD-DEDUCTION")
    assert old["enforcement_status"] == "not_enforced"
    assert ("STALE_METADATA", "EX-FED-OLD-DEDUCTION") in _codes(compiled, "WARNING")


@pytest.mark.parametrize(
    ("row", "column", "value", "code"),
    [
        (1, 6, "warn then maybe block", "MALFORMED_ACTION"),
        (1, 1, "ADGM", "INVALID_ROW"),
        (1, 10, "sometimes", "INVALID_ROW"),
        (4, 11, "", "INVALID_ROW"),  # not_enforced needs its note
    ],
)
def test_invalid_condition_rows_are_fatal(
    tmp_path: Path, row: int, column: int, value: str, code: str
) -> None:
    changed = [list(r) for r in synthetic.CONDITIONS]
    changed[row][column] = value
    result = _compile(tmp_path, conditions=changed)
    assert result.bundle is None
    assert code in {f.code for f in result.findings.fatal()}


def test_a_duplicate_condition_id_is_fatal(tmp_path: Path) -> None:
    result = _compile(tmp_path, conditions=[*synthetic.CONDITIONS, list(synthetic.CONDITIONS[1])])
    assert result.bundle is None
    assert ("DUPLICATE_ID", "EX-FED-POLICY") in _codes(result, "FATAL")


# --- document identity and mappings ----------------------------------------------------


def test_document_identity_comes_from_the_actual_files(compiled: CompileResult) -> None:
    assert _item(compiled, "documents", "EX02")["title"] == "Example Warning"
    assert _item(compiled, "documents", "EX03")["title"] == "Example Meeting"
    assert ("OWNER_DECISION", "EX02") in _codes(compiled, "INFO")
    assert ("SOURCE_MISMATCH", "EX02") in _codes(compiled, "WARNING")


def test_reversed_references_are_normalized_and_kept_for_traceability(
    compiled: CompileResult,
) -> None:
    warning = " ".join(s["text"] for s in _item(compiled, "units", "stage-warning")["segments"])
    assert "Doc EX03 – Example Meeting" in warning and "Doc EX02 – Example Warning" in warning
    assert "as per Doc EX03, then use Doc EX02 to issue the warning" in warning
    label = _item(compiled, "conditions", "EX-FED-WARNING-LABEL")
    assert "Use EX02 again" in label["segments"][0]["text"]
    assert label["raw"]["guidance"].startswith("Use EX03 again")
    references = _item(compiled, "documents", "EX02")["references"]
    assert {r["resolution"] for r in references} == {"source_mismatch_resolved"}
    assert {r["cited_id"] for r in references} >= {"EX03", "03"}


def test_an_owner_decision_the_files_contradict_is_fatal(tmp_path: Path) -> None:
    sources = synthetic.write_sources(tmp_path / "package")
    data = synthetic.mapping(sources)
    data["owner_decisions"][0]["expected_identity"] = {"EX02": "Example Meeting"}
    result = compile_package(sources, synthetic.write_mapping(tmp_path / "m.json", data))
    assert result.bundle is None
    assert ("OWNER_DECISION", "EX02") in _codes(result, "FATAL")


def test_a_copied_condition_mapping_is_broken_and_its_route_quarantined(
    compiled: CompileResult,
) -> None:
    delay = _item(compiled, "documents", "EX05")
    assert delay["related_conditions"] == [] and delay["status"] == "quarantined"
    assert _item(compiled, "documents", "EX04")["related_conditions"] == [
        "EX-FED-CAP",
        "EX-DIFC-SUSPENSION",
    ]
    assert ("BROKEN_MAPPING", "EX05") in _codes(compiled, "QUARANTINED")
    assert {k: v for k, v in _runtime(compiled)["quarantine"][0].items() if k != "finding"} == {
        "kind": "document",
        "id": "EX05",
        "reason": "broken_mapping:related_conditions",
    }


def test_stale_workbook_notes_are_verified_against_the_file(compiled: CompileResult) -> None:
    assert ("STALE_METADATA", "EX06") in _codes(compiled, "WARNING")
    assert ("COVERAGE", "EX99-OLD") in _codes(compiled, "INFO")


# --- explicit supersession, conflicts and scoping ------------------------------------------


def test_explicit_supersession_withholds_text_and_is_recorded(compiled: CompileResult) -> None:
    assert _item(compiled, "guards", "rule-2")["status"] == "superseded"
    assert {"kind": "guard", "id": "rule-2"} in _item(compiled, "guards", "rule-3")["supersedes"]
    warning = " ".join(s["text"] for s in _item(compiled, "units", "stage-warning")["segments"])
    assert "salary deduction" not in warning
    caution = _item(compiled, "conditions", "EX-FED-PAY-CAUTION")
    assert caution["guidance_status"] == "withheld"
    assert caution["raw"]["guidance"]  # kept for audit


def test_withholding_under_a_rule_that_doesnt_say_so_is_refused(tmp_path: Path) -> None:
    sources = synthetic.write_sources(tmp_path / "package")
    data = synthetic.mapping(sources)
    data["conditions"]["EX-FED-PAY-CAUTION"]["guidance_withheld"]["guard"] = "rule-5"
    result = compile_package(sources, synthetic.write_mapping(tmp_path / "m.json", data))
    assert result.bundle is None
    assert ("SOURCE_CONFLICT", "rule-5") in _codes(result, "FATAL")


def test_a_stated_supersession_the_mapping_ignores_is_fatal(tmp_path: Path) -> None:
    sources = synthetic.write_sources(tmp_path / "package")
    data = synthetic.mapping(sources)
    next(g for g in data["guards"] if g["id"] == "rule-2")["status"] = "operational"
    result = compile_package(sources, synthetic.write_mapping(tmp_path / "m.json", data))
    assert result.bundle is None
    assert ("SOURCE_CONFLICT", "2") in _codes(result, "FATAL")


def test_an_unresolved_conflict_is_withheld_and_reported(compiled: CompileResult) -> None:
    outcome = " ".join(s["text"] for s in _item(compiled, "units", "stage-outcome")["segments"])
    assert "must sign" not in outcome
    assert ("SOURCE_CONFLICT", "stage-outcome") in _codes(compiled, "REVIEW_REQUIRED")


def test_text_is_split_by_jurisdiction_without_rewording(compiled: CompileResult) -> None:
    shared = _item(compiled, "conditions", "EX-SHARED-DEDUCTION")["segments"]
    assert [s["scope"] for s in shared] == ["shared", "uae_federal", "difc"]
    assert (
        " ".join(s["text"] for s in shared)
        == _item(compiled, "conditions", "EX-SHARED-DEDUCTION")["raw"]["guidance"]
    )
    notice = _item(compiled, "documents", "EX04")["segments"]
    assert [s["scope"] for s in notice] == ["uae_federal", "difc"]


def test_a_mapping_that_leaks_federal_law_into_shared_text_is_refused(tmp_path: Path) -> None:
    sources = synthetic.write_sources(tmp_path / "package")
    data = synthetic.mapping(sources)
    next(u for u in data["units"] if u["id"] == "fed-suspension")["scope"] = "shared"
    result = compile_package(sources, synthetic.write_mapping(tmp_path / "m.json", data))
    assert result.bundle is None
    assert any("jurisdiction_leakage" in f.detail for f in result.findings.fatal())


def test_every_paragraph_and_rule_must_be_accounted_for(tmp_path: Path) -> None:
    sources = synthetic.write_sources(tmp_path / "package")
    data = synthetic.mapping(sources)
    data["playbook_excluded"] = []
    data["guards"] = [g for g in data["guards"] if g["id"] != "rule-11"]
    result = compile_package(sources, synthetic.write_mapping(tmp_path / "m.json", data))
    assert ("COVERAGE", "paragraph-0") in _codes(result, "WARNING")
    assert ("COVERAGE", "11") in _codes(result, "FATAL")


def test_a_stale_anchor_is_fatal(tmp_path: Path) -> None:
    sources = synthetic.write_sources(tmp_path / "package")
    data = synthetic.mapping(sources)
    data["units"][0]["from"] = "Step 9: Nowhere"
    result = compile_package(sources, synthetic.write_mapping(tmp_path / "m.json", data))
    assert ("COVERAGE", "orientation") in _codes(result, "FATAL")


def test_a_malformed_mapping_is_refused(tmp_path: Path) -> None:
    sources = synthetic.write_sources(tmp_path / "package")
    data = synthetic.mapping(sources)
    data["surprise"] = 1
    with pytest.raises(MappingError):
        compile_package(sources, synthetic.write_mapping(tmp_path / "m.json", data))


def test_reference_data_is_published_only_when_an_active_condition_needs_it(
    compiled: CompileResult,
) -> None:
    datasets = _runtime(compiled)["reference_data"]
    assert [d["id"] for d in datasets] == ["EX-FED-LIST"]
    assert datasets[0]["items"] == ["1. First example ground.", "2. Second example ground."]
    assert ("SUPERSEDED", "EX-OLD-LIMITS") in _codes(compiled, "INFO")


def test_option_source_refs_come_from_what_the_option_rests_on(compiled: CompileResult) -> None:
    dismissal = _item(compiled, "options", "opt-dismissal")
    sources = {r["source_id"] for r in dismissal["source_refs"]}
    assert sources == {"guide", "rules", "conditions"}
    assert dismissal["decided_by"] == "employer"


# --- the command line -------------------------------------------------------------------


def test_the_cli_writes_owner_only_outputs_and_prints_no_content(
    synthetic_sources: Path,
    synthetic_mapping_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "out"
    assert (
        main(["compile", str(synthetic_sources), str(synthetic_mapping_path), "--out", str(out)])
        == 0
    )
    printed = capsys.readouterr().out
    bundle = out / "example-knowledge.private-knowledge.json"
    for path in (bundle, out / "validation-report.json", out / "validation-report.md"):
        assert path.stat().st_mode & 0o777 == 0o600
    assert (
        f"HEROOS_KNOWLEDGE_BUNDLE_SHA256={hashlib.sha256(bundle.read_bytes()).hexdigest()}"
        in printed
    )
    assert "Example Reminder" not in printed and "fictional" not in printed
    assert main(["validate", str(bundle)]) == 0
    assert main(["validate", str(bundle), "--production"]) == 1
    assert "synthetic_in_production" in capsys.readouterr().err


@pytest.mark.parametrize("inside", ["repository", "sources"])
def test_the_cli_never_writes_into_the_repository_or_the_sources(
    synthetic_sources: Path, synthetic_mapping_path: Path, inside: str
) -> None:
    target = (
        Path(__file__).resolve().parent / "out"
        if inside == "repository"
        else synthetic_sources / "out"
    )
    assert (
        main(["compile", str(synthetic_sources), str(synthetic_mapping_path), "--out", str(target)])
        == 2
    )
    assert not target.exists()


def test_the_report_holds_every_section(compiled: CompileResult) -> None:
    report = compiled.report
    for key in (
        "source_package",
        "conditions",
        "documents",
        "playbook",
        "implementation_rules",
        "jurisdiction",
        "reference_data",
        "blueprint_dependencies",
        "workbook_sheets",
        "quarantine",
        "findings",
        "source_package_digest",
        "runtime_bundle_digest",
        "publishable",
    ):
        assert key in report, key
    assert report["publishable"] is True
    assert json.loads(json.dumps(report)) == report
    assert report["implementation_rules"]["deferred_capabilities"] == ["rule-10"]
