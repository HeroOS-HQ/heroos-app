"""Golden safety tests for the knowledge query service (M2-NEW-04), on the fictional bundle.

A  serious misconduct is investigation-first and never authorizes dismissal;
B  completing every stage still doesn't make dismissal supported;
C  UAE Federal and DIFC content never leak into each other;
D  an unknown, unsupported or conflicting jurisdiction never falls back;
E  DIFC dismissal without notice needs expert clearance, no document before it;
F  investigative suspension is distinct from disciplinary suspension;
G  DIFC unpaid disciplinary suspension needs expert review;
H  a deduction is an expert referral, never calculated;
I  the employer decides: nothing selects a sanction;
J  a not-enforced Condition never takes part;
K  an active needs_legal_review Condition keeps its action, not its authority;
L/M the reversed document codes resolve to the actual files;
N  a broken document mapping is quarantined;
O  an unsupported workflow or topic returns nothing invented;
P  same bundle and query, same result (digests in tests/knowledge/test_compiler.py);
Q  nothing is exposed (tests/knowledge/test_configuration.py).
"""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.companies.blueprint import CompanyBlueprintContext, CompanyPerson, JurisdictionContext
from app.knowledge.bundle import KnowledgeBundle
from app.knowledge.context import (
    ALWAYS_PROHIBITED,
    KnowledgeContext,
    KnowledgeQuery,
    KnowledgeStatus,
    get_knowledge_context,
)

FED, DIFC = "uae_federal", "difc"


def ask(
    bundle: KnowledgeBundle | None, jurisdiction: str | None = FED, **query: object
) -> KnowledgeContext:
    return get_knowledge_context(bundle, KnowledgeQuery("disciplinary", jurisdiction, **query))  # type: ignore[arg-type]


def steps(context: KnowledgeContext) -> dict[str, str]:
    return {s.kind: s.availability for s in context.supported_next_steps}


def company(
    jurisdiction: str | None, *, confirmed: bool = True, employees: int | None = 12
) -> CompanyBlueprintContext:
    person = CompanyPerson(
        uuid4(), uuid4(), "company_admin", datetime(2026, 10, 1, tzinfo=UTC), True, True
    )
    return CompanyBlueprintContext(
        company_id=uuid4(),
        company_display_name="Example Co",
        legal_name=None,
        industry=None,
        employee_count=employees,
        website_url=None,
        company_summary=None,
        jurisdiction=JurisdictionContext(
            readiness="supported_confirmed" if confirmed else "unconfirmed",
            reason="confirmed" if confirmed else "awaiting_confirmation",
            employment_jurisdiction=jurisdiction if confirmed else None,
            confirmed_at=None,
            guidance_allowed=confirmed,
            licensing_location=None,
            licensing_authority=None,
        ),
        policies_exist=None,
        policy_context=None,
        hr_support=None,
        hr_support_notes=None,
        primary_contact=person,
        current_user=person,
        updated_at=None,
        missing=(),
    )


# --- A, B: serious misconduct -------------------------------------------------------------


@pytest.mark.parametrize("jurisdiction", [FED, DIFC])
def test_a_serious_misconduct_is_investigation_first_never_dismissal(
    bundle: KnowledgeBundle, jurisdiction: str
) -> None:
    context = ask(bundle, jurisdiction, pathway="serious")
    assert steps(context)["dismissal_without_notice"] == "review_required"
    assert "dismiss_on_classification" in context.prohibited_behaviors
    assert "guide_investigation_first" in context.required_behaviors
    investigation_first = [
        g for g in context.implementation_guards if g.kind == "investigation_first"
    ]
    assert investigation_first
    dismissal = next(
        s for s in context.supported_next_steps if s.kind == "dismissal_without_notice"
    )
    assert dismissal.requires_completed_investigation and dismissal.requires_employee_response


def test_b_completing_every_stage_does_not_make_dismissal_supported(
    bundle: KnowledgeBundle,
) -> None:
    everything = frozenset(f.key for f in bundle.facts)
    context = ask(bundle, FED, pathway="serious", stage="penalty_notice", known_facts=everything)
    assert context.missing_facts == ()
    assert steps(context)["dismissal_without_notice"] == "review_required"
    assert "treat_stage_completion_as_lawful_dismissal" in context.prohibited_behaviors
    assert not any(
        d.status == "eligible_with_gates" and "dismissal" in d.id for d in context.document_metadata
    )


# --- C, D: jurisdiction isolation and no fallback --------------------------------------------


def _every_query(bundle: KnowledgeBundle, jurisdiction: str) -> list[KnowledgeContext]:
    queries = [ask(bundle, jurisdiction)]
    queries += [ask(bundle, jurisdiction, topics=(t.key,)) for t in bundle.topics]
    workflow = bundle.workflow("disciplinary")
    assert workflow is not None
    for pathway in workflow.pathways:
        queries.append(ask(bundle, jurisdiction, pathway=pathway.key))
        queries += [
            ask(bundle, jurisdiction, pathway=pathway.key, stage=s.key) for s in pathway.stages
        ]
    queries += [ask(bundle, jurisdiction, document_ids=(d.id,)) for d in bundle.documents]
    return queries


def test_c_federal_content_never_reaches_a_difc_case(bundle: KnowledgeBundle) -> None:
    federal_text = {s.text for u in bundle.units for s in u.segments if s.scope == FED}
    federal_text |= {s.text for c in bundle.conditions for s in c.segments if s.scope == FED}
    federal_text |= {s.text for d in bundle.documents for s in d.segments if s.scope == FED}
    assert federal_text
    for context in _every_query(bundle, DIFC):
        assert all(u.scope != FED for u in context.playbook_units)
        assert all(c.scope != FED for c in context.condition_metadata)
        assert all(r.id != "EX-FED-LIST" for r in context.reference_data)
        shown = {t for u in context.playbook_units for t in u.text}
        shown |= {t for c in context.condition_metadata for t in c.guidance}
        shown |= {t for d in context.document_metadata for t in d.purpose}
        assert not shown & federal_text


def test_c_difc_content_never_reaches_a_federal_case(bundle: KnowledgeBundle) -> None:
    difc_text = {s.text for c in bundle.conditions for s in c.segments if s.scope == DIFC}
    difc_text |= {s.text for d in bundle.documents for s in d.segments if s.scope == DIFC}
    assert difc_text
    for context in _every_query(bundle, FED):
        assert all(u.scope != DIFC for u in context.playbook_units)
        assert all(c.scope != DIFC for c in context.condition_metadata)
        shown = {t for c in context.condition_metadata for t in c.guidance}
        shown |= {t for d in context.document_metadata for t in d.purpose}
        assert not shown & difc_text


def test_c_shared_guidance_shows_each_jurisdiction_only_its_own_passage(
    bundle: KnowledgeBundle,
) -> None:
    def guidance(jurisdiction: str) -> tuple[str, ...]:
        context = ask(bundle, jurisdiction, condition_ids=("EX-SHARED-DEDUCTION",))
        return next(c.guidance for c in context.condition_metadata if c.id == "EX-SHARED-DEDUCTION")

    federal, difc = guidance(FED), guidance(DIFC)
    assert any("UAE Federal:" in t for t in federal) and not any(
        t.startswith("DIFC:") for t in federal
    )
    assert any(t.startswith("DIFC:") for t in difc) and not any("UAE Federal:" in t for t in difc)


@pytest.mark.parametrize("jurisdiction", [None, "adgm", "other"])
def test_d_no_or_unsupported_jurisdiction_never_falls_back(
    bundle: KnowledgeBundle, jurisdiction: str | None
) -> None:
    context = ask(bundle, jurisdiction, topics=("disciplinary_suspension",))
    assert context.status is KnowledgeStatus.JURISDICTION_UNRESOLVED
    assert context.jurisdiction is None
    assert context.supported_next_steps == () and context.document_metadata == ()
    assert all(u.without_jurisdiction is not False for u in [bundle.units[0]])
    assert {u.scope for u in context.playbook_units} <= {"shared", "global"}
    assert {c.scope for c in context.condition_metadata} == {"global"}
    assert "confirm_jurisdiction_first" in context.required_behaviors


def test_d_a_jurisdiction_conflicting_with_the_blueprint_is_unresolved(
    bundle: KnowledgeBundle,
) -> None:
    context = ask(bundle, DIFC, company=company(FED))
    assert context.status is KnowledgeStatus.JURISDICTION_UNRESOLVED
    assert ("jurisdiction_unresolved", "jurisdiction_conflict") in {
        (lim.code, lim.subject) for lim in context.limitations
    }
    unconfirmed = ask(bundle, FED, company=company(FED, confirmed=False))
    assert unconfirmed.status is KnowledgeStatus.JURISDICTION_UNRESOLVED


def test_d_orientation_safe_without_a_jurisdiction_is_returned(bundle: KnowledgeBundle) -> None:
    context = ask(bundle, None)
    assert {u.id for u in context.playbook_units} == {
        u.id for u in bundle.units if u.without_jurisdiction
    }
    assert all(u.kind != "legal_reference" for u in context.playbook_units)


# --- E, G, H: expert review ---------------------------------------------------------------


def test_e_difc_dismissal_without_notice_needs_expert_clearance(bundle: KnowledgeBundle) -> None:
    context = ask(bundle, DIFC, topics=("dismissal_without_notice",))
    assert context.status is KnowledgeStatus.REVIEW_REQUIRED
    dismissal = next(
        s for s in context.supported_next_steps if s.kind == "dismissal_without_notice"
    )
    assert dismissal.availability == "review_required" and dismissal.documents == ()
    assert "expert_clearance_documented" in dismissal.required_facts
    assert (
        "generate_dismissal_without_notice_letter_before_clearance" in context.prohibited_behaviors
    )
    assert any(
        g.kind == "expert_review_mandatory" and g.escalation == "human_expert_review"
        for g in context.implementation_guards
    )
    outcome = ask(bundle, DIFC, document_ids=("EX07",)).document_metadata[0]
    assert outcome.status != "eligible_with_gates"
    assert "outcome:dismissal_without_notice_before_expert_clearance" in outcome.prohibited_when
    assert ("expert_review_not_operational", "disciplinary") in {
        (lim.code, lim.subject) for lim in context.limitations
    }
    assert "promise_expert_response" in context.prohibited_behaviors


def test_g_difc_unpaid_disciplinary_suspension_needs_expert_review(bundle: KnowledgeBundle) -> None:
    context = ask(bundle, DIFC, topics=("disciplinary_suspension",))
    assert context.status is KnowledgeStatus.REVIEW_REQUIRED
    assert steps(context)["disciplinary_suspension_unpaid"] == "review_required"
    assert {d.id: d.status for d in context.document_metadata}["EX04"] == "expert_review_required"
    assert "generate_unpaid_suspension_notice" in context.prohibited_behaviors
    federal = ask(bundle, FED, topics=("disciplinary_suspension",))
    assert steps(federal)["disciplinary_suspension_unpaid"] == "supported"
    assert {d.id: d.status for d in federal.document_metadata}["EX04"] == "eligible_with_gates"


@pytest.mark.parametrize("jurisdiction", [FED, DIFC])
def test_h_a_deduction_is_an_expert_referral_never_calculated(
    bundle: KnowledgeBundle, jurisdiction: str
) -> None:
    context = ask(bundle, jurisdiction, topics=("salary_deduction",))
    assert context.status is KnowledgeStatus.REVIEW_REQUIRED
    deduction = next(s for s in context.supported_next_steps if s.kind == "salary_deduction")
    assert deduction.availability == "review_required" and deduction.documents == ()
    assert {"calculate_deduction", "recommend_deduction_amount", "instruct_payroll"} <= set(
        context.prohibited_behaviors
    )


# --- F: the two suspensions ------------------------------------------------------------


def test_f_investigative_suspension_is_not_disciplinary_suspension(bundle: KnowledgeBundle) -> None:
    investigative = ask(bundle, FED, topics=("investigative_suspension",))
    disciplinary = ask(bundle, FED, topics=("disciplinary_suspension",))
    i = next(s for s in investigative.supported_next_steps if s.kind == "investigative_suspension")
    d = next(
        s for s in disciplinary.supported_next_steps if s.kind == "disciplinary_suspension_unpaid"
    )
    assert (i.is_penalty, d.is_penalty) == (False, True)
    assert not set(i.documents) & set(d.documents)
    assert "conflate_suspension_types" in investigative.prohibited_behaviors
    assert d.requires_completed_investigation and not i.requires_completed_investigation


# --- I, J, K: the employer, not-enforced and review status -------------------------------


def test_i_nothing_selects_a_sanction(bundle: KnowledgeBundle) -> None:
    for context in _every_query(bundle, FED) + _every_query(bundle, DIFC):
        assert context.decided_by == "employer"
        assert all(s.decided_by == "employer" for s in context.supported_next_steps)
        assert set(ALWAYS_PROHIBITED) <= set(context.prohibited_behaviors)
        assert "choose_sanction" in context.prohibited_behaviors
    assert not hasattr(KnowledgeContext, "selected_option")


def test_j_a_not_enforced_condition_never_takes_part(bundle: KnowledgeBundle) -> None:
    old = bundle.condition("EX-FED-OLD-DEDUCTION")
    assert old is not None and not old.participates_in_execution
    assert old not in bundle.executable_conditions()
    assert old.id not in {link.condition for link in bundle.engine_links}
    for context in _every_query(bundle, FED):
        assert old.id not in {c.id for c in context.condition_metadata}
        assert old.id not in {s.id for s in context.safeguards}
    asked = ask(bundle, FED, condition_ids=(old.id,))
    assert ("condition_not_enforced", old.id) in {
        (lim.code, lim.subject) for lim in asked.limitations
    }


def test_k_needs_legal_review_keeps_its_action_but_not_its_authority(
    bundle: KnowledgeBundle,
) -> None:
    context = ask(bundle, FED, pathway="serious", stage="penalty_notice")
    escalate = next(c for c in context.condition_metadata if c.id == "EX-FED-ESCALATE")
    assert (escalate.action, escalate.enforcement_status) == ("escalate", "active")
    assert escalate.citation_status == "needs_legal_review"
    assert not escalate.legal_basis_confirmed
    assert escalate.presentation == "provisional_not_legal_advice"
    assert "legal_basis_not_confirmed" in escalate.limitations
    confirmed = next(
        c
        for c in ask(bundle, FED, topics=("disciplinary_suspension",)).condition_metadata
        if c.id == "EX-FED-CAP"
    )
    assert confirmed.presentation == "confirmed_legal_basis"


def test_k_superseded_guidance_is_withheld_but_the_action_stays(bundle: KnowledgeBundle) -> None:
    context = ask(bundle, FED, topics=("investigative_suspension",))
    caution = next(c for c in context.condition_metadata if c.id == "EX-FED-PAY-CAUTION")
    assert caution.guidance == () and caution.action == "warn"
    assert "guidance_withheld" in caution.limitations


# --- L, M, N: document identity and quarantine --------------------------------------------


def test_l_m_reversed_codes_resolve_to_the_actual_files(bundle: KnowledgeBundle) -> None:
    warning, meeting = bundle.document("EX02"), bundle.document("EX03")
    assert warning is not None and warning.title == "Example Warning"
    assert meeting is not None and meeting.title == "Example Meeting"
    stage = ask(bundle, FED, pathway="less_serious", stage="formal_warning")
    text = " ".join(t for u in stage.playbook_units for t in u.text)
    assert "Doc EX03 – Example Meeting" in text and "Doc EX02 – Example Warning" in text
    assert {d.id for d in stage.document_metadata} >= {"EX02", "EX03"}
    assert {r.cited_id for r in warning.references} >= {"EX03"}


def test_n_a_broken_mapping_never_makes_a_document_eligible(bundle: KnowledgeBundle) -> None:
    delay = bundle.document("EX05")
    assert delay is not None and delay.related_conditions == ()
    context = ask(bundle, FED, document_ids=("EX05",))
    assert context.status is KnowledgeStatus.SOURCE_CONFLICT
    assert context.document_metadata[0].status == "quarantined"
    topic = ask(bundle, FED, topics=("delay_increase_or_promotion",))
    assert {d.id: d.status for d in topic.document_metadata}["EX05"] == "quarantined"


# --- O: unsupported --------------------------------------------------------------------


def test_o_an_unsupported_workflow_returns_nothing(bundle: KnowledgeBundle) -> None:
    context = get_knowledge_context(bundle, KnowledgeQuery("workforce_strategy", FED))
    assert context.status is KnowledgeStatus.UNSUPPORTED
    assert (context.playbook_units, context.condition_metadata, context.supported_next_steps) == (
        (),
        (),
        (),
    )
    assert ("workflow_not_in_approved_sources", "workforce_strategy") in {
        (lim.code, lim.subject) for lim in context.limitations
    }


@pytest.mark.parametrize(
    "selectors",
    [
        {"topics": ("staffing_plan_2027",)},
        {"pathway": "probation"},
        {"stage": "nowhere"},
        {"condition_ids": ("EX-PROB-ONLY",)},
        {"document_ids": ("EX99",)},
    ],
)
def test_o_an_unsupported_selector_returns_nothing(
    bundle: KnowledgeBundle, selectors: dict[str, object]
) -> None:
    context = ask(bundle, FED, **selectors)
    assert context.status is KnowledgeStatus.UNSUPPORTED
    assert context.playbook_units == () and context.supported_next_steps == ()


def test_no_bundle_means_unavailable_never_invented() -> None:
    context = ask(None, FED, topics=("salary_deduction",))
    assert context.status is KnowledgeStatus.BUNDLE_UNAVAILABLE
    assert context.playbook_units == () and context.runtime_bundle_digest is None
    assert set(ALWAYS_PROHIBITED) <= set(context.prohibited_behaviors)


# --- P: determinism, narrowness, facts ------------------------------------------------------


def test_p_the_same_query_gives_the_same_result(bundle: KnowledgeBundle) -> None:
    first = ask(bundle, FED, pathway="less_serious", stage="formal_warning")
    assert first == ask(bundle, FED, pathway="less_serious", stage="formal_warning")
    assert first.runtime_bundle_digest == bundle.runtime_digest
    assert first.source_package_digest == bundle.source_package_digest


def test_retrieval_is_narrow_never_the_whole_library(bundle: KnowledgeBundle) -> None:
    general = ask(bundle, FED)
    assert {u.id for u in general.playbook_units} < {u.id for u in bundle.units}
    stage = ask(bundle, FED, pathway="less_serious", stage="reminder")
    assert {u.id for u in stage.playbook_units} == {"stage-reminder"}


def test_facts_report_what_the_blueprint_or_the_case_already_holds(bundle: KnowledgeBundle) -> None:
    context = ask(bundle, FED, pathway="less_serious", stage="formal_warning")
    assert "given_opportunity_to_explain" in context.missing_facts
    known = ask(
        bundle,
        FED,
        pathway="less_serious",
        stage="formal_warning",
        known_facts=frozenset({"given_opportunity_to_explain"}),
    )
    assert "given_opportunity_to_explain" not in known.missing_facts
    routing = ask(bundle, FED, condition_ids=("EX-ROUTING-1",), company=company(FED))
    jurisdiction = next(f for f in routing.required_facts if f.key == "employment_jurisdiction")
    assert (jurisdiction.availability, jurisdiction.source) == ("from_case", "routing:jurisdiction")


def test_a_blueprint_value_is_used_without_creating_a_new_company_model(
    bundle: KnowledgeBundle,
) -> None:
    fact = bundle.fact("headcount")
    assert fact is not None and fact.blueprint == "employee_count"
    patched = replace(
        bundle, units=(replace(bundle.units[0], required_facts=("headcount",)),) + bundle.units[1:]
    )
    known = ask(patched, FED, topics=("misconduct_level",), company=company(FED, employees=60))
    assert (
        next(f for f in known.required_facts if f.key == "headcount").availability
        == "from_blueprint"
    )
    unknown = ask(patched, FED, topics=("misconduct_level",), company=company(FED, employees=None))
    assert next(f for f in unknown.required_facts if f.key == "headcount").availability == "missing"


def test_needs_more_context_names_the_missing_facts_not_questions(bundle: KnowledgeBundle) -> None:
    context = ask(bundle, FED, topics=("misconduct_level",))
    assert context.status is KnowledgeStatus.NEEDS_MORE_CONTEXT
    assert "misconduct_level" in context.missing_facts
    assert all(not hasattr(f, "question") for f in context.required_facts)
    supported = ask(
        bundle, FED, topics=("misconduct_level",), known_facts=frozenset({"misconduct_level"})
    )
    assert supported.status is KnowledgeStatus.SUPPORTED
