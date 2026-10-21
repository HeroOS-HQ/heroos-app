"""The gateway on the real knowledge bundle (local only; skipped in CI).

The compiled bundle is private and never in this public repository, so this
runs only where it is, with a scripted provider (nothing is sent anywhere):

    KNOWLEDGE_BUNDLE=/path/to/bundle.json uv run pytest tests/assistant/test_real_bundle.py

It names no library content: everything is checked generically on whatever
the bundle holds (its own ids, topics, options and texts).
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from app.assistant.gateway.catalog import routing_catalog
from app.assistant.gateway.planning import plan_turn
from app.assistant.gateway.projection import KNOWLEDGE_BUDGET_CHARS, knowledge_view
from app.assistant.gateway.proposals import UnderstandingProposal
from app.assistant.gateway.service import FounderTurn
from app.knowledge.bundle import KnowledgeBundle, jurisdiction_leaks, load_knowledge_bundle
from app.knowledge.context import KnowledgeStatus
from tests.fixtures.gateway import (
    DIFC,
    FED,
    ScriptedProvider,
    company,
    gateway,
    response,
    understanding,
)

BUNDLE = os.environ.get("KNOWLEDGE_BUNDLE")
pytestmark = pytest.mark.skipif(
    not BUNDLE, reason="private bundle not configured (local check only)"
)


@pytest.fixture(scope="module")
def real() -> KnowledgeBundle:
    assert BUNDLE
    path = Path(BUNDLE)
    return load_knowledge_bundle(
        path, hashlib.sha256(path.read_bytes()).hexdigest(), production=False
    )


def proposal(topics: tuple[str, ...] = (), pathway: str | None = None) -> UnderstandingProposal:
    return UnderstandingProposal("supported_hr", "disciplinary", pathway, topics, (), (), None)


def every_plan(bundle: KnowledgeBundle, jurisdiction: str | None):  # type: ignore[no-untyped-def]
    for topics in [(), *[(t.key,) for t in bundle.topics]]:
        for pathway in (None, "less_serious", "serious"):
            yield plan_turn(
                bundle,
                proposal(topics, pathway),
                company(jurisdiction, confirmed=bool(jurisdiction)),
            )


def test_the_catalog_is_small_and_names_only_published_workflows(real: KnowledgeBundle) -> None:
    catalog = routing_catalog(real)
    assert [w.key for w in catalog.workflows] == [w.key for w in real.workflows]
    assert len(json.dumps(catalog.model_view())) < 12_000
    sensitive = {f.key for f in real.facts if f.sensitive}
    assert not sensitive & set(catalog.facts)


@pytest.mark.parametrize("jurisdiction", [FED, DIFC, None])
def test_every_view_is_bounded_and_carries_no_internal_identifier(
    real: KnowledgeBundle, jurisdiction: str | None
) -> None:
    private = [d.id for d in real.documents] + [c.id for c in real.conditions]
    private += [g.id for g in real.guards] + [o.id for o in real.options]
    private += [m.filename for m in real.manifest]
    private += [real.runtime_digest, real.source_package_digest]
    for plan in every_plan(real, jurisdiction):
        view = knowledge_view(real, plan)
        flat = json.dumps(view.data, ensure_ascii=False)
        texts = sum(len(t) for t in view.texts)
        assert texts <= KNOWLEDGE_BUDGET_CHARS + 6000, plan.query
        for item in private:
            assert item not in flat, (item, plan.query)
        # What a DIFC or unresolved company is shown never states another regime's authority.
        if jurisdiction != FED:
            scope = jurisdiction or "shared"
            guidance = [t for g in view.data["approved_guidance"] for t in g["text"]]  # type: ignore[attr-defined]
            assert not any(jurisdiction_leaks(scope, t) for t in guidance), plan.query


@pytest.mark.parametrize("jurisdiction", [FED, DIFC])
def test_requested_actions_keep_the_runtimes_review_routing(
    real: KnowledgeBundle, jurisdiction: str
) -> None:
    for option in real.options:
        topics = tuple(t.key for t in real.topics if option.id in t.options)
        if not topics:
            continue
        plan = plan_turn(real, proposal(topics[:1]), company(jurisdiction))
        expected = option.jurisdictions[jurisdiction].availability
        found = [a for a in plan.requested_actions if a.title == option.title]
        if plan.context.status is not KnowledgeStatus.SOURCE_CONFLICT and found:
            assert found[0].availability in (expected, "review_required"), option.id
        if option.kind in ("dismissal_without_notice", "salary_deduction") and found:
            assert found[0].availability != "supported"


def test_a_full_turn_runs_on_the_real_bundle_with_a_scripted_model(real: KnowledgeBundle) -> None:
    topics = [t.key for t in real.topics if t.options][:1]
    provider = ScriptedProvider(
        understanding(topics=topics), response("You can dismiss him today.")
    )
    result = gateway(real, provider).respond(company(FED), FounderTurn("[SYNTHETIC] test"))
    assert "dismiss him today" not in result.reply
    assert result.handoff.runtime_bundle_digest == real.runtime_digest
