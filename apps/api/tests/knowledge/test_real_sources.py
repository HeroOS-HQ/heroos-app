"""The real source package, compiled and checked (local only; skipped in CI).

The authoritative sources and the compile mapping are private and never in
this public repository, so this test runs only where they are:

    KNOWLEDGE_SOURCE_DIR=/path/to/sources KNOWLEDGE_MAPPING=/path/to/mapping.json \\
        uv run pytest tests/knowledge/test_real_sources.py

It names no library content: what must hold (the owner's document-identity
decisions, the safety invariants, jurisdiction isolation) is read from the
mapping and the compiled bundle, and checked generically.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from app.knowledge.bundle import KnowledgeBundle, parse_knowledge_bundle
from app.knowledge.context import KnowledgeQuery, KnowledgeStatus, get_knowledge_context
from scripts.knowledge.compiler import CompileResult, compile_package
from scripts.knowledge.sources import inventory
from scripts.knowledge.templates import same_document

SOURCES = os.environ.get("KNOWLEDGE_SOURCE_DIR")
MAPPING = os.environ.get("KNOWLEDGE_MAPPING")
pytestmark = pytest.mark.skipif(
    not (SOURCES and MAPPING), reason="private sources not configured (local check only)"
)


@pytest.fixture(scope="module")
def real() -> tuple[CompileResult, KnowledgeBundle, dict[str, str]]:
    assert SOURCES and MAPPING
    before = {f.relative: f.sha256 for f in inventory(Path(SOURCES))}
    result = compile_package(Path(SOURCES), Path(MAPPING))
    assert result.bundle_bytes is not None, [f.data() for f in result.findings.fatal()]
    bundle = parse_knowledge_bundle(result.bundle_bytes, file_sha256="0" * 64)
    return result, bundle, before


def test_the_real_package_compiles_with_no_fatal_finding(
    real: tuple[CompileResult, KnowledgeBundle, dict[str, str]],
) -> None:
    result, _, _ = real
    assert result.report["publishable"] is True
    assert result.findings.fatal() == []
    assert result.report["source_package"]["files_missing"] == []


def test_compiling_leaves_every_source_byte_identical(
    real: tuple[CompileResult, KnowledgeBundle, dict[str, str]],
) -> None:
    _, _, before = real
    assert SOURCES
    assert {f.relative: f.sha256 for f in inventory(Path(SOURCES))} == before


def test_two_compiles_are_identical() -> None:
    assert SOURCES and MAPPING
    first = compile_package(Path(SOURCES), Path(MAPPING))
    second = compile_package(Path(SOURCES), Path(MAPPING))
    assert first.bundle_bytes == second.bundle_bytes
    assert first.bundle_bytes is not None
    assert (
        hashlib.sha256(first.bundle_bytes).hexdigest()
        == hashlib.sha256(second.bundle_bytes).hexdigest()
    )


def test_every_owner_identity_decision_holds_for_the_actual_files(
    real: tuple[CompileResult, KnowledgeBundle, dict[str, str]],
) -> None:
    _, bundle, _ = real
    assert MAPPING
    decisions = json.loads(Path(MAPPING).read_text())["owner_decisions"]
    expected = {
        code: title for d in decisions for code, title in d.get("expected_identity", {}).items()
    }
    assert expected
    for code, title in expected.items():
        document = bundle.document(code)
        assert document is not None and same_document(title, document.title), code


def test_jurisdictions_never_leak_in_any_query(
    real: tuple[CompileResult, KnowledgeBundle, dict[str, str]],
) -> None:
    _, bundle, _ = real
    workflow = bundle.workflow("disciplinary")
    assert workflow is not None
    for jurisdiction, other in (("uae_federal", "difc"), ("difc", "uae_federal")):
        queries = [KnowledgeQuery("disciplinary", jurisdiction)]
        queries += [
            KnowledgeQuery("disciplinary", jurisdiction, topics=(t.key,)) for t in bundle.topics
        ]
        for pathway in workflow.pathways:
            queries.append(KnowledgeQuery("disciplinary", jurisdiction, pathway=pathway.key))
            queries += [
                KnowledgeQuery("disciplinary", jurisdiction, pathway=pathway.key, stage=s.key)
                for s in pathway.stages
            ]
        for query in queries:
            context = get_knowledge_context(bundle, query)
            assert all(u.scope != other for u in context.playbook_units)
            assert all(c.scope != other for c in context.condition_metadata)
            assert all(c.enforcement_status == "active" for c in context.condition_metadata)
            assert all(s.decided_by == "employer" for s in context.supported_next_steps)


def test_the_hard_safety_outcomes_hold_on_the_real_bundle(
    real: tuple[CompileResult, KnowledgeBundle, dict[str, str]],
) -> None:
    _, bundle, _ = real
    for option in bundle.options:
        if option.kind in ("dismissal_without_notice", "salary_deduction"):
            assert all(e.availability != "supported" for e in option.jurisdictions.values())
        if option.kind == "disciplinary_suspension_unpaid":
            assert option.jurisdictions["difc"].availability == "review_required"
    everything = frozenset(f.key for f in bundle.facts)
    for jurisdiction in ("uae_federal", "difc"):
        context = get_knowledge_context(
            bundle,
            KnowledgeQuery("disciplinary", jurisdiction, pathway="serious", known_facts=everything),
        )
        dismissal = [
            s for s in context.supported_next_steps if s.kind == "dismissal_without_notice"
        ]
        assert dismissal and dismissal[0].availability == "review_required"
    unresolved = get_knowledge_context(bundle, KnowledgeQuery("disciplinary", None))
    assert unresolved.status is KnowledgeStatus.JURISDICTION_UNRESOLVED
    assert unresolved.supported_next_steps == ()
    unsupported = get_knowledge_context(bundle, KnowledgeQuery("workforce_planning", "uae_federal"))
    assert unsupported.status is KnowledgeStatus.UNSUPPORTED
