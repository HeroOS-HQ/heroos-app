"""The knowledge bundle loader: pin, schema, digests and the safety invariants (M2-NEW-04).

Every invariant is tested by tampering with a valid (fictional) bundle and
re-sealing it, so the refusal comes from the invariant, not from a digest.
"""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.knowledge.bundle import (
    KnowledgeBundle,
    KnowledgeBundleError,
    jurisdiction_leaks,
    load_knowledge_bundle,
    parse_knowledge_bundle,
    runtime_bundle_digest,
    source_package_digest,
)


def _seal(data: dict[str, Any]) -> bytes:
    data["runtime_bundle_digest"] = runtime_bundle_digest(data["runtime"])
    data["source_package_digest"] = source_package_digest(data["manifest"])
    return json.dumps(data).encode()


def _refused(data: dict[str, Any]) -> str:
    with pytest.raises(KnowledgeBundleError) as refused:
        parse_knowledge_bundle(_seal(data), file_sha256="0" * 64)
    return refused.value.code


def _find(data: dict[str, Any], collection: str, item_id: str) -> dict[str, Any]:
    item: dict[str, Any] = next(i for i in data["runtime"][collection] if i["id"] == item_id)
    return item


def _write(tmp_path: Path, content: bytes) -> tuple[Path, str]:
    path = tmp_path / "bundle.json"
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


# --- loading -----------------------------------------------------------------------------


def test_a_valid_bundle_loads_with_both_digests(bundle: KnowledgeBundle) -> None:
    assert bundle.provenance == "synthetic" and bundle.approval == "development"
    assert len(bundle.source_package_digest) == len(bundle.runtime_digest) == 64
    assert {c.id for c in bundle.executable_conditions()} <= {c.id for c in bundle.conditions}


def test_the_pin_must_match_the_file(bundle_file: Path) -> None:
    with pytest.raises(KnowledgeBundleError) as refused:
        load_knowledge_bundle(bundle_file, "0" * 64, production=False)
    assert refused.value.code == "checksum_mismatch"
    with pytest.raises(KnowledgeBundleError) as invalid:
        load_knowledge_bundle(bundle_file, "not-a-pin", production=False)
    assert invalid.value.code == "invalid_pin"


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(KnowledgeBundleError) as refused:
        load_knowledge_bundle(tmp_path / "none.json", "0" * 64, production=False)
    assert refused.value.code == "unreadable"


def test_production_refuses_synthetic_and_development_content(
    tmp_path: Path, bundle_data: dict[str, Any]
) -> None:
    path, pin = _write(tmp_path, _seal(bundle_data))
    with pytest.raises(KnowledgeBundleError) as synthetic:
        load_knowledge_bundle(path, pin, production=True)
    assert synthetic.value.code == "synthetic_in_production"
    bundle_data["provenance"] = "private"
    bundle_data["notice"] = None
    path, pin = _write(tmp_path, _seal(bundle_data))
    with pytest.raises(KnowledgeBundleError) as development:
        load_knowledge_bundle(path, pin, production=True)
    assert development.value.code == "unapproved_in_production"


def test_a_tampered_runtime_section_fails_its_digest(bundle_data: dict[str, Any]) -> None:
    bundle_data["runtime"]["units"][0]["title"] = "Changed"
    with pytest.raises(KnowledgeBundleError) as refused:
        parse_knowledge_bundle(json.dumps(bundle_data).encode(), file_sha256="0" * 64)
    assert refused.value.code == "runtime_bundle_digest_mismatch"


def test_a_tampered_manifest_fails_the_source_digest(bundle_data: dict[str, Any]) -> None:
    bundle_data["manifest"][0]["sha256"] = "f" * 64
    with pytest.raises(KnowledgeBundleError) as refused:
        parse_knowledge_bundle(json.dumps(bundle_data).encode(), file_sha256="0" * 64)
    assert refused.value.code == "source_package_digest_mismatch"


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda d: d.update(schema="heroos.knowledge-bundle/2"), "unsupported_schema"),
        (lambda d: d.update(extra=1), "unknown_field"),
        (lambda d: d.update(notice=None), "synthetic_without_notice"),
        (lambda d: d["runtime"]["units"].append(dict(d["runtime"]["units"][0])), "duplicate_id"),
        (lambda d: d["runtime"]["units"][0]["guards"].append("nowhere"), "unknown_reference"),
        (lambda d: d["runtime"]["jurisdictions"].pop(), "jurisdictions_incomplete"),
        (
            lambda d: d["runtime"]["documents"][0]["jurisdictions"].pop("difc"),
            "jurisdictions_incomplete",
        ),
        (lambda d: d["runtime"]["options"][0].update(decided_by="heroos"), "decision_not_employer"),
        (
            lambda d: d["runtime"]["guards"][0]["required"].append("invent_a_behavior"),
            "invalid_code",
        ),
        (
            lambda d: d["runtime"]["units"][0].update(segments=[{"scope": "shared", "text": "a​b"}]),
            "invalid_text",
        ),
    ],
)
def test_malformed_bundles_are_refused(
    bundle_data: dict[str, Any], mutate: Callable[[dict[str, Any]], Any], code: str
) -> None:
    mutate(bundle_data)
    assert _refused(bundle_data) == code


def test_duplicate_json_keys_are_refused() -> None:
    with pytest.raises(KnowledgeBundleError) as refused:
        parse_knowledge_bundle(b'{"schema": 1, "schema": 2}', file_sha256="0" * 64)
    assert refused.value.code == "duplicate_json_key"


def test_operational_knowledge_comes_from_operational_sources_only(
    bundle_data: dict[str, Any],
) -> None:
    next(m for m in bundle_data["manifest"] if m["source_id"] == "guide")["runtime_role"] = (
        "audit_only"
    )
    assert _refused(bundle_data) == "source_not_operational"


# --- safety invariants ---------------------------------------------------------------------


def test_dismissal_without_notice_can_never_be_supported(bundle_data: dict[str, Any]) -> None:
    _find(bundle_data, "options", "opt-dismissal")["jurisdictions"]["uae_federal"][
        "availability"
    ] = "supported"
    assert _refused(bundle_data) == "option_must_not_be_supported"


def test_dismissal_without_notice_needs_an_investigation_first(bundle_data: dict[str, Any]) -> None:
    _find(bundle_data, "options", "opt-dismissal")["requires_completed_investigation"] = False
    assert _refused(bundle_data) == "outcome_without_investigation"


def test_dismissal_without_notice_needs_an_investigation_first_guard(
    bundle_data: dict[str, Any],
) -> None:
    _find(bundle_data, "guards", "rule-4")["options"] = []
    assert _refused(bundle_data) == "dismissal_without_investigation_guard"


def test_difc_dismissal_without_notice_needs_expert_review(bundle_data: dict[str, Any]) -> None:
    _find(bundle_data, "options", "opt-dismissal")["jurisdictions"]["difc"]["guards"] = ["rule-4"]
    assert _refused(bundle_data) == "difc_expert_review_missing"


def test_a_deduction_always_goes_to_expert_review_with_no_document(
    bundle_data: dict[str, Any],
) -> None:
    deduction = _find(bundle_data, "options", "opt-deduction")
    deduction["jurisdictions"]["uae_federal"]["documents"] = ["EX07"]
    assert _refused(bundle_data) == "deduction_with_document"
    deduction["jurisdictions"]["uae_federal"]["documents"] = []
    deduction["jurisdictions"]["difc"]["guards"] = []
    assert _refused(bundle_data) == "deduction_without_expert_review"


def test_difc_unpaid_suspension_needs_expert_review(bundle_data: dict[str, Any]) -> None:
    _find(bundle_data, "options", "opt-suspension")["jurisdictions"]["difc"]["availability"] = (
        "supported"
    )
    assert _refused(bundle_data) == "difc_expert_review_missing"


def test_investigative_suspension_is_never_a_penalty(bundle_data: dict[str, Any]) -> None:
    _find(bundle_data, "options", "opt-investigative")["is_penalty"] = True
    assert _refused(bundle_data) == "investigative_suspension_is_not_a_penalty"


def test_the_two_suspensions_never_share_a_document(bundle_data: dict[str, Any]) -> None:
    investigative = _find(bundle_data, "options", "opt-investigative")["jurisdictions"][
        "uae_federal"
    ]
    investigative["documents"] = ["EX06", "EX04"]
    _find(bundle_data, "documents", "EX04")["options"].append("opt-investigative")
    assert _refused(bundle_data) == "suspension_documents_shared"


def test_every_penalty_needs_the_employees_response(bundle_data: dict[str, Any]) -> None:
    _find(bundle_data, "options", "opt-warning")["requires_employee_response"] = False
    assert _refused(bundle_data) == "penalty_without_employee_response"


def test_a_document_is_never_more_available_than_its_option(bundle_data: dict[str, Any]) -> None:
    _find(bundle_data, "documents", "EX04")["jurisdictions"]["difc"]["status"] = (
        "eligible_with_gates"
    )
    assert _refused(bundle_data) == "document_more_available_than_option"


def test_a_template_written_for_another_regime_is_never_offered(
    bundle_data: dict[str, Any],
) -> None:
    document = _find(bundle_data, "documents", "EX04")
    document["options"] = []
    document["jurisdictions"]["difc"]["status"] = "eligible_with_gates"
    _find(bundle_data, "options", "opt-suspension")["jurisdictions"]["uae_federal"][
        "documents"
    ] = []
    assert _refused(bundle_data) == "document_body_other_jurisdiction"


def test_the_required_guards_must_be_operational(bundle_data: dict[str, Any]) -> None:
    _find(bundle_data, "guards", "rule-1")["status"] = "audit_only"
    assert _refused(bundle_data) == "required_guard_missing"


def test_federal_authority_in_shared_or_difc_text_is_refused(bundle_data: dict[str, Any]) -> None:
    unit = _find(bundle_data, "units", "difc-deadline")
    unit["segments"] = [
        {"scope": "difc", "text": "Under the UAE Federal Labour Law, notify in 30 days."}
    ]
    assert _refused(bundle_data) == "jurisdiction_leakage"


def test_difc_authority_in_federal_text_is_refused(bundle_data: dict[str, Any]) -> None:
    unit = _find(bundle_data, "units", "fed-deadline")
    unit["segments"] = [{"scope": "uae_federal", "text": "DIFC Employment Law sets the rule here."}]
    assert _refused(bundle_data) == "jurisdiction_leakage"


def test_a_jurisdiction_unit_carries_no_other_jurisdictions_text(
    bundle_data: dict[str, Any],
) -> None:
    _find(bundle_data, "units", "fed-deadline")["segments"].append(
        {"scope": "difc", "text": "Plain."}
    )
    assert _refused(bundle_data) == "segment_outside_scope"


def test_only_orientation_may_be_returned_without_a_jurisdiction(
    bundle_data: dict[str, Any],
) -> None:
    _find(bundle_data, "units", "fed-deadline")["without_jurisdiction"] = True
    assert _refused(bundle_data) == "unsafe_without_jurisdiction"


@pytest.mark.parametrize(
    ("scope", "text", "leaks"),
    [
        ("shared", "Under Article 900, suspension is capped.", True),
        ("shared", "Do not cite Article 900 for this.", True),  # a bare article: always scoped
        ("difc", "Do not apply UAE Federal Labour Law here.", False),
        ("difc", "Unlike UAE Federal Labour Law, DIFC has no cap.", False),
        ("difc", "Articles 901 and 902 protect remuneration.", False),
        ("difc", "The MOHRE deadline applies.", True),
        ("uae_federal", "Under DIFC Employment Law the rule is different.", True),
        ("uae_federal", "This does not apply to DIFC cases.", False),
    ],
)
def test_the_leakage_check(scope: str, text: str, leaks: bool) -> None:
    assert bool(jurisdiction_leaks(scope, text)) is leaks


def test_system_rules_may_compare_regimes(bundle_data: dict[str, Any]) -> None:
    text = "Use Article 900 for UAE Federal cases, or Article 901 for DIFC cases."
    assert jurisdiction_leaks("shared", text)
    assert not jurisdiction_leaks("shared", text, comparative_allowed=True)


# --- the deterministic engine and the facts --------------------------------------------------


def test_engine_links_must_agree_with_the_intake_rules(bundle_data: dict[str, Any]) -> None:
    _find(bundle_data, "conditions", "EX-FED-POLICY")["action_policy"]["initial"] = "block"
    assert _refused(bundle_data) == "engine_action_mismatch"


def test_engine_links_must_agree_on_review_status(bundle_data: dict[str, Any]) -> None:
    _find(bundle_data, "conditions", "EX-FED-POLICY")["citation_status"] = "confirmed"
    assert _refused(bundle_data) == "engine_review_status_mismatch"


def test_a_not_enforced_condition_can_never_be_linked_to_the_engine(
    bundle_data: dict[str, Any],
) -> None:
    bundle_data["runtime"]["engine_links"][1]["condition"] = "EX-FED-OLD-DEDUCTION"
    assert _refused(bundle_data) == "not_enforced_condition_linked"


def test_engine_links_name_real_intake_rules(bundle_data: dict[str, Any]) -> None:
    bundle_data["runtime"]["engine_links"][1]["rule"] = "no_such_rule"
    assert _refused(bundle_data) == "unknown_engine_rule"


def test_facts_name_real_case_questions_with_their_sensitivity(bundle_data: dict[str, Any]) -> None:
    fact = next(
        f
        for f in bundle_data["runtime"]["facts"]
        if f["key"] == "dismissal_without_notice_considered"
    )
    fact["sensitive"] = False
    assert _refused(bundle_data) == "sensitivity_mismatch"
    fact["sensitive"] = True
    fact["case_fact"] = "screening.no_such_question"
    assert _refused(bundle_data) == "unknown_case_fact"


def test_facts_name_real_company_blueprint_fields(bundle_data: dict[str, Any]) -> None:
    next(f for f in bundle_data["runtime"]["facts"] if f["key"] == "headcount")["blueprint"] = (
        "headcount"
    )
    assert _refused(bundle_data) == "unknown_blueprint_field"
