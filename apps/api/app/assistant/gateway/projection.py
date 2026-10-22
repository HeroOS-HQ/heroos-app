"""The minimized views a model may see: the company and the approved knowledge for this turn.

**Company view** (``company_view``): a whitelisted projection of the
canonical ``CompanyBlueprintContext``: industry, size, summary, whether the
employment jurisdiction is confirmed (and which), HR policies and HR support.
No id, person, role, date, website, licensing answer or audit field.

**Knowledge view** (``knowledge_view``): what the approved runtime returned for
this turn, reduced to what the reply needs: approved guidance and cautions
(texts and titles only), how each may be presented (a Condition whose legal
basis isn't confirmed is a practical caution, never law), the decisions the
founder asked about with their availability, the behaviors HeroOS must keep
and must never adopt (in words), the limitations, and the server's question
targets. Never: source references, file names, hashes, digests, item ids,
raw Condition rows, triggers, validation findings or document templates.
Document codes inside approved text are replaced with the documents' titles
(internal labels are never shown to a founder).

A character budget keeps the view small: items are included whole, in the
runtime's order (methodology, then safeguards, then cautions, then
reference data), and the view says when more approved material exists than
it shows, so the model never fills a gap itself.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from app.assistant.gateway.planning import TurnPlan
from app.companies.blueprint import CompanyBlueprintContext
from app.knowledge.bundle import KnowledgeBundle
from app.knowledge.context import KnowledgeStatus

KNOWLEDGE_BUDGET_CHARS: Final = 9000

JURISDICTION_NAMES: Final = {"uae_federal": "UAE Federal", "difc": "DIFC"}

# What each closed-vocabulary behavior means, for the model (app.knowledge.bundle).
REQUIRED: Final[Mapping[str, str]] = {
    "confirm_jurisdiction_first": (
        "Confirm the applicable employment jurisdiction before any jurisdiction-specific guidance."
    ),
    "suppress_other_jurisdiction_law": "Never mention another jurisdiction's law as applying here.",
    "use_shared_practice_when_same": "Use shared practical methodology where it applies equally.",
    "guide_investigation_first": (
        "For serious allegations, guide a fair investigation before any outcome is considered."
    ),
    "establish_required_facts": (
        "Establish the facts the approved methodology needs before going further."
    ),
    "reuse_known_information": (
        "Reuse what the founder and the company context already say; never ask again."
    ),
    "ask_only_material_questions": "Ask only what matters now, naturally, never as a checklist.",
    "explain_supported_options": (
        "You may explain the approved options as possibilities the employer decides on."
    ),
    "explain_risks": "Explain the risks the approved guidance describes.",
    "explain_limitation": "Say plainly when approved guidance doesn't cover something.",
    "refer_to_specialist_review": "Say when specialist review is needed before an action.",
    "gather_facts_for_review": "Gathering context useful for a specialist is fine.",
    "employer_makes_final_decision": "The employer makes every employment decision.",
    "record_employer_decision": "The employer's decision is theirs to record.",
    "distinguish_suspension_types": (
        "Keep suspension during an investigation distinct from suspension as a penalty."
    ),
    "require_expert_clearance": "Some actions need specialist clearance first.",
    "use_traceable_delivery": "Notices should be delivered in a traceable way.",
    "record_signature_refusal": (
        "A refusal to sign can be recorded; it is about receipt, not agreement."
    ),
    "keep_records_confidential": "Disciplinary records are confidential.",
    "distinguish_discretionary_from_contractual": (
        "Keep discretionary benefits distinct from contractual entitlements."
    ),
    "use_approved_sources_only": "Use only the approved guidance given here.",
    "explain_deadlines_employer_tracks": (
        "Explain approved timing; the employer tracks their own deadlines."
    ),
    "hold_unsupported_for_review": (
        "Hold actions the approved guidance doesn't support for specialist review."
    ),
}
PROHIBITED: Final[Mapping[str, str]] = {
    "apply_other_jurisdiction_law": "applying another jurisdiction's law",
    "cite_federal_law_for_difc": "citing UAE Federal law for a DIFC employer",
    "blend_jurisdictions": "blending jurisdictions",
    "dismiss_on_classification": (
        "treating a misconduct category as grounds for dismissal by itself"
    ),
    "treat_stage_completion_as_lawful_dismissal": (
        "treating completed process steps as making a dismissal lawful"
    ),
    "present_dismissal_without_notice_automatically": (
        "presenting dismissal without notice as automatic"
    ),
    "select_or_approve_employment_decision": "selecting or approving any employment decision",
    "decide_misconduct_proven": "deciding that misconduct is proven",
    "choose_sanction": "choosing or recommending a sanction",
    "determine_deduction_legality": "deciding whether a salary deduction is lawful",
    "recommend_deduction_amount": "recommending a deduction amount",
    "calculate_deduction": "calculating a deduction",
    "generate_deduction_notice": "preparing a deduction notice",
    "instruct_payroll": "instructing payroll",
    "recommend_dismissal_without_notice": "recommending dismissal without notice",
    "generate_dismissal_without_notice_letter_before_clearance": "preparing a dismissal letter",
    "recommend_unpaid_suspension": "recommending unpaid suspension",
    "generate_unpaid_suspension_notice": "preparing a suspension notice",
    "apply_federal_suspension_limits_to_difc": (
        "applying UAE Federal suspension limits to a DIFC employer"
    ),
    "treat_suspension_as_finding": "treating a suspension as a finding of misconduct",
    "conflate_suspension_types": (
        "confusing suspension during an investigation with suspension as a penalty"
    ),
    "use_open_web_or_general_model_knowledge": "using general knowledge or the internet",
    "invent_legal_requirement": "inventing a legal requirement, deadline, number or threshold",
    "rigid_questionnaire": "asking a checklist of questions",
    "repeat_answered_questions": "asking again for something already answered",
    "promise_deadline_monitoring": "promising to monitor deadlines or send reminders",
    "promise_document_deletion": "promising to delete documents or data",
    "offer_document_upload": "offering document upload",
    "promise_expert_response": (
        "promising that an expert will respond or that a review was requested"
    ),
    "invent_universal_deadline": "stating a universal deadline",
    "assert_universal_consent_rule": "stating a universal consent rule",
    "assume_signature_makes_deduction_lawful": "treating a signature as making a deduction lawful",
    "present_benefit_decision_as_statutory_penalty": (
        "presenting a benefit decision as a statutory penalty"
    ),
    "withhold_contractual_entitlement": "suggesting withholding a contractual entitlement",
    "show_internal_labels": "showing internal codes, ids or labels",
}
LIMITATIONS: Final[Mapping[str, str]] = {
    "synthetic_content": "This approved content is fictional test material.",
    "development_content_not_production_approved": (
        "This guidance is development content, not yet approved for production use."
    ),
    "difc_coverage_partial": "Approved DIFC coverage is partial: say so where it matters.",
    "expert_review_not_operational": (
        "HeroOS has no specialist review service yet: advise specialist review, never promise, "
        "request or arrange one."
    ),
    "deferred_capability": "Some related capabilities are not available in HeroOS yet.",
    "unit_quarantined": (
        "Part of the approved material for this area is under review and not shown."
    ),
    "condition_quarantined": (
        "Part of the approved material for this area is under review and not shown."
    ),
    "no_approved_content": "Approved guidance does not cover this request.",
}
GENERIC_LIMITATION: Final = "A coverage limitation applies to this area of approved guidance."
AVAILABILITY: Final[Mapping[str, str]] = {
    "supported": (
        "covered by approved guidance as a possible employer decision, only after every required "
        "step"
    ),
    "review_required": "requires specialist review before it is taken",
    "not_available": "not available for this employer under approved guidance",
}
STATUS: Final[Mapping[KnowledgeStatus, str]] = {
    KnowledgeStatus.SUPPORTED: "covered",
    KnowledgeStatus.NEEDS_MORE_CONTEXT: "covered, but more facts are needed",
    KnowledgeStatus.REVIEW_REQUIRED: (
        "covered for methodology; the actions marked below need specialist review"
    ),
    KnowledgeStatus.JURISDICTION_UNRESOLVED: (
        "jurisdiction not confirmed: only shared orientation is available"
    ),
    KnowledgeStatus.SOURCE_CONFLICT: "not safely covered",
    KnowledgeStatus.UNSUPPORTED: "not covered",
    KnowledgeStatus.BUNDLE_UNAVAILABLE: "unavailable",
}


@dataclass(frozen=True, slots=True)
class KnowledgeView:
    data: dict[str, object]
    # Every text the model was shown (the grounding check's allowed sources).
    texts: tuple[str, ...]


def company_view(company: CompanyBlueprintContext) -> dict[str, object]:
    jurisdiction = company.jurisdiction
    confirmed = jurisdiction.employment_jurisdiction if jurisdiction.guidance_allowed else None
    return {
        "industry": company.industry,
        "number_of_employees": company.employee_count,
        "company_summary": company.company_summary,
        "employment_jurisdiction": (
            f"{JURISDICTION_NAMES.get(confirmed, confirmed)} (confirmed)"
            if confirmed is not None
            else "not confirmed yet"
        ),
        "hr_policies_exist": company.policies_exist,
        "hr_policy_notes": company.policy_context,
        "hr_support": company.hr_support,
        "hr_support_notes": company.hr_support_notes,
    }


def company_text(company: CompanyBlueprintContext) -> str:
    """The company view's values, for checking a Blueprint-sourced excerpt."""
    return "\n".join(str(v) for v in company_view(company).values() if v is not None)


def _redactor(bundle: KnowledgeBundle) -> list[tuple[re.Pattern[str], str]]:
    """Document codes become the documents' titles; Condition ids disappear."""
    pairs = [(re.compile(rf"\b{re.escape(d.id)}\b"), d.title) for d in bundle.documents]
    pairs += [(re.compile(rf"\s*\(?\b{re.escape(c.id)}\b\)?"), "") for c in bundle.conditions]
    return pairs


def _redact(texts: Iterable[str], redactor: list[tuple[re.Pattern[str], str]]) -> list[str]:
    out = []
    for text in texts:
        for pattern, replacement in redactor:
            text = pattern.sub(replacement, text)
        out.append(text)
    return out


def knowledge_view(bundle: KnowledgeBundle, plan: TurnPlan) -> KnowledgeView:
    context = plan.context
    redactor = _redactor(bundle)
    budget = KNOWLEDGE_BUDGET_CHARS
    shown: list[str] = []
    omitted = False

    def fits(texts: list[str]) -> bool:
        nonlocal budget, omitted
        size = sum(len(t) for t in texts)
        if size > budget:
            omitted = True
            return False
        budget -= size
        shown.extend(texts)
        return True

    guidance: list[dict[str, object]] = []
    for unit in context.playbook_units:
        title, *texts = _redact([unit.title, *unit.text], redactor)
        if texts and fits([title, *texts]):
            item: dict[str, object] = {"title": title, "text": texts}
            if unit.legal_status == "playbook_statement":
                item["presentation"] = (
                    "approved HeroOS statement about the law, not confirmed legal advice: "
                    "present it with that qualification"
                )
            guidance.append(item)

    cautions: list[dict[str, object]] = []
    active = [c for c in context.condition_metadata if c.enforcement_status == "active"]
    ordered = [c for c in active if c.action in ("block", "escalate")] + [
        c for c in active if c.action not in ("block", "escalate")
    ]
    for condition in ordered:
        title, *texts = _redact([condition.title, *condition.guidance], redactor)
        if not texts or not fits([title, *texts]):
            continue
        cautions.append(
            {
                "title": title,
                "text": texts,
                "safeguard": condition.action in ("block", "escalate"),
                "legal_basis": (
                    "confirmed"
                    if condition.legal_basis_confirmed
                    else "not confirmed: present only as a practical caution, never as the law"
                ),
            }
        )

    reference: list[dict[str, object]] = []
    for dataset in context.reference_data:
        title, *items = _redact([dataset.title, *dataset.items], redactor)
        if items and fits([title, *items]):
            reference.append(
                {
                    "title": title,
                    "items": items,
                    "legal_basis": (
                        "confirmed" if dataset.legal_basis_confirmed else "not confirmed"
                    ),
                }
            )

    requested = {a.title for a in plan.requested_actions}
    options = [
        {
            "title": _redact([step.title], redactor)[0],
            "availability": AVAILABILITY.get(step.availability, AVAILABILITY["not_available"]),
            "asked_about": step.title in requested,
            "needs_completed_investigation": step.requires_completed_investigation,
            "needs_employee_response": step.requires_employee_response,
        }
        for step in context.supported_next_steps
    ]
    shown += _redact([step.title for step in context.supported_next_steps], redactor)

    limitations = _limitations(context.limitations, plan)
    must = [REQUIRED[b] for b in context.required_behaviors if b in REQUIRED]
    must_not = [PROHIBITED[b] for b in context.prohibited_behaviors if b in PROHIBITED]
    targets = [
        {
            "id": t.id,
            "about": t.label,
            "mode": t.mode,
            # A deterministic check's question: HeroOS asks it itself, in these words.
            **({"heroos_asks_after_your_reply": t.question} if t.question else {}),
        }
        for t in plan.targets
    ]
    shown += [t.label for t in plan.targets] + [t.question for t in plan.targets if t.question]
    shown += limitations
    data: dict[str, object] = {
        "knowledge_status": STATUS[context.status],
        "jurisdiction": (
            JURISDICTION_NAMES.get(context.jurisdiction, context.jurisdiction)
            if context.jurisdiction is not None
            else None
        ),
        "approved_guidance": guidance,
        "cautions": cautions,
        "reference": reference,
        "decisions": options,
        "must": must,
        "must_never": must_not,
        "limitations": limitations,
        "question_targets": targets,
    }
    if omitted:
        data["more_material_not_shown"] = (
            "More approved material exists than is shown here: don't fill the gap; say what "
            "you can and ask."
        )
    return KnowledgeView(data=data, texts=tuple(shown))


def _limitations(codes: Iterable[object], plan: TurnPlan) -> list[str]:
    found: list[str] = []
    for limitation in codes:
        code = getattr(limitation, "code", "")
        if code in ("legal_basis_not_confirmed", "guidance_withheld", "condition_not_enforced"):
            continue  # presented per item, or never shown
        if code == "jurisdiction_unresolved":
            continue  # the jurisdiction note says it
        text = LIMITATIONS.get(code, GENERIC_LIMITATION)
        if text not in found:
            found.append(text)
    if plan.conflicted_topics:
        found.append(
            "Part of what the founder asked about can't be safely covered: the approved "
            "material for it is in conflict and under review. Say so and suggest specialist review."
        )
    return found
