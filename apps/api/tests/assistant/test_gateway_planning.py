"""Retrieval, question targets and the minimized knowledge view (M2-NEW-05), fictional bundle.

Covers: the jurisdiction comes from the Blueprint only; known facts are the
founder's explicit statements; the server picks what to ask, safety first,
one target by default and a second only from the same approved item; nothing
sensitive, Blueprint-held or answered is asked; the view carries no ids,
sources or digests; a not-enforced Condition never appears; a Condition
whose legal basis isn't confirmed is never presented as law; a source
conflict narrows to the topics it concerns.
"""

import json
from dataclasses import replace

import pytest

from app.assistant.gateway import planning
from app.assistant.gateway.planning import (
    jurisdiction_input,
    plan_turn,
    question_targets,
)
from app.assistant.gateway.projection import company_view, knowledge_view
from app.assistant.gateway.proposals import FactProposal, UnderstandingProposal
from app.knowledge.bundle import KnowledgeBundle
from app.knowledge.context import KnowledgeQuery, KnowledgeStatus, get_knowledge_context
from tests.fixtures.gateway import DIFC, FED, company


def proposal(
    *,
    pathway: str | None = None,
    topics: tuple[str, ...] = (),
    facts: tuple[FactProposal, ...] = (),
    uncertainties: tuple[str, ...] = (),
) -> UnderstandingProposal:
    return UnderstandingProposal(
        intent="supported_hr",
        workflow="disciplinary",
        pathway=pathway,
        topics=topics,
        facts=facts,
        uncertainties=uncertainties,  # type: ignore[arg-type]
        summary=None,
    )


def stated(key: str, value: str = "yes", turn: int = 0, basis: str = "explicit") -> FactProposal:
    return FactProposal(key, value, "high", "current_user_message", turn, value, basis)  # type: ignore[arg-type]


# --- jurisdiction ---------------------------------------------------------------------


def test_the_jurisdiction_is_the_blueprints_confirmation_only() -> None:
    assert jurisdiction_input(company(FED), proposal()) == (FED, "confirmed")
    assert jurisdiction_input(company(DIFC), proposal()) == (DIFC, "confirmed")
    assert jurisdiction_input(company(FED, confirmed=False), proposal()) == (
        None, "company_unconfirmed",
    )  # fmt: skip
    # The model can only make it less certain.
    conflict = proposal(uncertainties=("jurisdiction_conflict",))
    assert jurisdiction_input(company(FED), conflict) == (None, "conversation_conflict")
    assert jurisdiction_input(company(None, confirmed=False), conflict)[0] is None


# --- known facts ----------------------------------------------------------------------


def test_the_newest_explicit_statement_wins_and_inferences_never_count() -> None:
    facts = (
        stated("misconduct_level", "serious", turn=0),
        stated("misconduct_level", "minor", turn=2),
        stated("investigation_completed", "probably", turn=2, basis="inferred"),
    )
    established = planning.established_facts(proposal(facts=facts))
    assert [(f.fact_key, f.value) for f in established] == [("misconduct_level", "minor")]


def test_an_inferred_correction_withdraws_the_earlier_explicit_value() -> None:
    facts = (
        stated("misconduct_level", "serious", 0),
        stated("misconduct_level", "?", 1, "inferred"),
    )
    assert planning.established_facts(proposal(facts=facts)) == ()


# --- question targets -----------------------------------------------------------------


def _targets(
    bundle: KnowledgeBundle, understanding: UnderstandingProposal, j: str = FED
) -> list[str]:
    plan = plan_turn(bundle, understanding, company(j))
    return [t.fact_key for t in plan.targets]


def test_a_safeguard_conditions_facts_come_before_methodology(bundle: KnowledgeBundle) -> None:
    # The deduction safeguard (escalate) needs whether a deduction is requested.
    assert _targets(bundle, proposal(topics=("salary_deduction",))) == ["deduction_requested"]


def test_one_target_by_default_and_a_second_only_from_the_same_item(
    bundle: KnowledgeBundle,
) -> None:
    # The DIFC suspension safeguard needs two facts; the jurisdiction is known.
    targets = _targets(bundle, proposal(topics=("disciplinary_suspension",)), DIFC)
    assert targets == ["proposed_penalty"]
    plan = plan_turn(bundle, proposal(pathway="serious", topics=("penalty_notice",)), company(FED))
    assert [t.fact_key for t in plan.targets] == ["investigation_completed", "employer_decision"]
    assert [t.id for t in plan.targets] == ["q1", "q2"]


def test_answered_sensitive_and_blueprint_facts_are_never_asked(bundle: KnowledgeBundle) -> None:
    answered = proposal(
        pathway="serious", topics=("penalty_notice",), facts=(stated("investigation_completed"),)
    )
    assert "investigation_completed" not in _targets(bundle, answered)
    everything = {
        t
        for topics in [(t.key,) for t in bundle.topics]
        for j in (FED, DIFC)
        for t in _targets(bundle, proposal(topics=topics), j)
    }
    for never in ("dismissal_without_notice_considered", "headcount", "employment_jurisdiction"):
        assert never not in everything


def test_a_hinted_fact_is_confirmed_not_asked_from_scratch(bundle: KnowledgeBundle) -> None:
    hinted = proposal(
        topics=("salary_deduction",), facts=(stated("deduction_requested", basis="inferred"),)
    )
    plan = plan_turn(bundle, hinted, company(FED))
    assert [(t.fact_key, t.mode) for t in plan.targets] == [("deduction_requested", "confirm")]


def test_no_targets_while_the_jurisdiction_is_unresolved(bundle: KnowledgeBundle) -> None:
    plan = plan_turn(bundle, proposal(topics=("salary_deduction",)), company(None, confirmed=False))
    assert plan.context.status is KnowledgeStatus.JURISDICTION_UNRESOLVED
    assert plan.targets == () and plan.requested_actions == ()


def test_targets_never_come_from_document_gates(bundle: KnowledgeBundle) -> None:
    context = get_knowledge_context(
        bundle, KnowledgeQuery("disciplinary", FED, topics=("formal_warning",))
    )
    gates = {g for d in context.document_metadata for g in d.gates}
    targets = question_targets(bundle, context, proposal(topics=("formal_warning",)), ())
    units = {u.id: u for u in bundle.units}
    others = {k for c in context.condition_metadata for k in c.required_facts}
    others |= {k for s in context.supported_next_steps for k in s.required_facts}
    others |= {k for u in context.playbook_units for k in units[u.id].required_facts}
    assert not ({t.fact_key for t in targets} & (gates - others))


# --- action-scoped review ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("jurisdiction", "topic", "kind", "availability"),
    [
        (FED, "salary_deduction", "salary_deduction", "review_required"),
        (DIFC, "salary_deduction", "salary_deduction", "review_required"),
        (FED, "dismissal_without_notice", "dismissal_without_notice", "review_required"),
        (DIFC, "disciplinary_suspension", "disciplinary_suspension_unpaid", "review_required"),
        (FED, "disciplinary_suspension", "disciplinary_suspension_unpaid", "supported"),
        (FED, "investigative_suspension", "investigative_suspension", "supported"),
        (DIFC, "investigative_suspension", "investigative_suspension", "review_required"),
    ],
)
def test_the_decisions_asked_about_keep_the_runtimes_availability(
    bundle: KnowledgeBundle, jurisdiction: str, topic: str, kind: str, availability: str
) -> None:
    plan = plan_turn(bundle, proposal(topics=(topic,)), company(jurisdiction))
    assert [(a.title, a.availability) for a in plan.requested_actions] == [
        (f"Example {kind}", availability)
    ]


def test_investigative_and_disciplinary_suspension_stay_distinct(bundle: KnowledgeBundle) -> None:
    for topic in ("investigative_suspension", "disciplinary_suspension"):
        plan = plan_turn(bundle, proposal(topics=(topic,)), company(FED))
        assert (
            "Keep suspension during an investigation distinct from suspension as a penalty."
            in (
                knowledge_view(bundle, plan).data["must"]  # type: ignore[operator]
            )
        )
        assert len(plan.requested_actions) == 1


# --- the minimized view -----------------------------------------------------------------


def _all_views(bundle: KnowledgeBundle) -> list[str]:
    views = []
    for j in (FED, DIFC, None):
        for topics in [(), *[(t.key,) for t in bundle.topics]]:
            for pathway in (None, "less_serious", "serious"):
                plan = plan_turn(
                    bundle, proposal(pathway=pathway, topics=topics),
                    company(j, confirmed=j is not None),
                )  # fmt: skip
                views.append(json.dumps(knowledge_view(bundle, plan).data, ensure_ascii=False))
    return views


def test_the_view_never_carries_ids_sources_digests_or_raw_rows(bundle: KnowledgeBundle) -> None:
    private = [bundle.runtime_digest, bundle.source_package_digest, bundle.file_sha256]
    private += [d.id for d in bundle.documents] + [c.id for c in bundle.conditions]
    private += [g.id for g in bundle.guards] + [o.id for o in bundle.options]
    # Source files and their ids (the fictional package names some with plain words).
    private += [m.filename for m in bundle.manifest]
    private += [m.source_id for m in bundle.manifest if m.source_id.upper() == m.source_id]
    # Trigger descriptions (the fictional ones that are longer than a common word).
    private += [c.trigger for c in bundle.conditions if len(c.trigger) > 20]
    for view in _all_views(bundle):
        for item in private:
            assert item not in view, item
        for word in ("source_ref", "sha256", "location", "eligible_with_gates", "trigger"):
            assert word not in view


def test_document_codes_inside_approved_text_become_titles(bundle: KnowledgeBundle) -> None:
    plan = plan_turn(bundle, proposal(topics=("formal_warning",)), company(FED))
    view = json.dumps(knowledge_view(bundle, plan).data)
    assert "Example Meeting" in view and "EX03" not in view


def test_a_not_enforced_condition_never_appears(bundle: KnowledgeBundle) -> None:
    retired = next(c for c in bundle.conditions if c.enforcement_status == "not_enforced")
    texts = [s.text for s in retired.segments]
    for view in _all_views(bundle):
        assert not any(t in view for t in texts)


def test_withheld_guidance_never_appears(bundle: KnowledgeBundle) -> None:
    withheld = next(c for c in bundle.conditions if c.guidance_status == "withheld")
    for view in _all_views(bundle):
        assert not any(s.text in view for s in withheld.segments)


def test_an_unconfirmed_legal_basis_is_a_practical_caution_never_law(
    bundle: KnowledgeBundle,
) -> None:
    plan = plan_turn(bundle, proposal(topics=("salary_deduction",)), company(FED))
    cautions = knowledge_view(bundle, plan).data["cautions"]
    deduction = next(
        c
        for c in cautions
        if any("deduction" in t for t in c["text"])  # type: ignore[attr-defined]
    )
    assert deduction["safeguard"] is True
    assert deduction["legal_basis"].startswith("not confirmed: present only as a practical")
    confirmed = plan_turn(bundle, proposal(), company(FED))
    routing = knowledge_view(bundle, confirmed).data["cautions"]
    assert any(c["legal_basis"] == "confirmed" for c in routing)  # type: ignore[attr-defined]


def test_the_view_is_bounded_and_says_when_material_is_left_out(
    bundle: KnowledgeBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.assistant.gateway import projection

    plan = plan_turn(bundle, proposal(pathway="serious", topics=("penalty_notice",)), company(FED))
    full = knowledge_view(bundle, plan).data
    assert "more_material_not_shown" not in full
    monkeypatch.setattr(projection, "KNOWLEDGE_BUDGET_CHARS", 120)
    small = knowledge_view(bundle, plan)
    assert "more_material_not_shown" in small.data
    assert len(small.data["approved_guidance"]) < len(full["approved_guidance"])  # type: ignore[arg-type]


def test_the_company_view_is_a_whitelist() -> None:
    view = company_view(company(FED, policy_context="[SYNTHETIC] Handbook v2"))
    assert set(view) == {
        "industry", "number_of_employees", "company_summary", "employment_jurisdiction",
        "hr_policies_exist", "hr_policy_notes", "hr_support", "hr_support_notes",
    }  # fmt: skip
    assert view["employment_jurisdiction"] == "UAE Federal (confirmed)"
    flat = json.dumps(view)
    for private in (
        "example.com",
        "Example Trading",
        "company_admin",
        "licensing",
        "[SYNTHETIC] L",
    ):
        assert private not in flat
    assert company_view(company(DIFC, confirmed=False))["employment_jurisdiction"] == (
        "not confirmed yet"
    )


# --- a source conflict is about its route only ---------------------------------------------


def test_a_conflict_on_one_topic_leaves_the_others(
    bundle: KnowledgeBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = planning.get_knowledge_context

    def conflicted(b: KnowledgeBundle | None, query: KnowledgeQuery):  # type: ignore[no-untyped-def]
        context = real(b, query)
        if "delay_increase_or_promotion" in query.topics:
            return replace(context, status=KnowledgeStatus.SOURCE_CONFLICT)
        return context

    monkeypatch.setattr(planning, "get_knowledge_context", conflicted)
    plan = plan_turn(
        bundle, proposal(topics=("delay_increase_or_promotion", "formal_warning")), company(FED)
    )
    assert plan.conflicted_topics == ("delay_increase_or_promotion",)
    assert plan.query.topics == ("formal_warning",)
    assert plan.context.status is not KnowledgeStatus.SOURCE_CONFLICT
    view = knowledge_view(bundle, plan).data
    assert any("in conflict" in limitation for limitation in view["limitations"])  # type: ignore[union-attr]
    alone = plan_turn(bundle, proposal(topics=("delay_increase_or_promotion",)), company(FED))
    assert alone.context.status is KnowledgeStatus.SOURCE_CONFLICT
