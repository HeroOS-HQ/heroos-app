"""Golden conversations for M2-NEW-06, through the gateway, on the fictional content.

The model is scripted, so each test fixes what it proposes and proves what
the server decides: the outcome card (Guidance, Warning, Block, Expert
Review), what is asked next, and that no model failure or unsafe reply can
change a deterministic result.

A  lateness, nothing requested: Guidance and the next material question
B  a fact already said is reused, never confirmed for nothing
C  improvement: no mechanical escalation
D  a bound caution fires with its own configured severity
E  suspected theft + "fire her today": the dismissal needs review; the investigation continues
F  DIFC: investigation Guidance; dismissal without notice Expert Review
G  "take the repair cost from his salary": Expert Review, no amount
H  investigative suspension is not disciplinary suspension
I  disciplinary suspension: prerequisites first, whatever the founder asks for
J  over the cap: Warning; acknowledgment keeps it; explicit insistence blocks
K  DIFC unpaid disciplinary suspension: Expert Review, no Federal cap
L  a quarantined document route stays narrow
M  needs_legal_review: conservative, and never stated as law
N  not_enforced: no effect
O  unresolved jurisdiction: no jurisdiction-specific result; the founder's answer resolves it
P  unsupported HR: a specialist requirement, no ticket
Q  outside HeroOS: a neutral limitation, no Expert Review
R  several matters: one at a time, never mixed
S  "generate the letter": no document, prerequisites unchanged
"""

import json
from collections.abc import Sequence
from typing import Any

import pytest

from app.assistant.gateway.service import (
    OUTSIDE,
    OUTSIDE_HR,
    AiGateway,
    FounderTurn,
    GatewayReply,
)
from app.assistant.limits import UsageLimits
from app.assistant.provider import AssistantError, ChatTurn
from app.companies.blueprint import CompanyBlueprintContext
from app.evaluation.evaluator import ConversationEvaluationService
from app.evaluation.presentation import PROVISIONAL
from app.evaluation.snapshot import ExecutionRuntime
from tests.fixtures.evaluation import PROBATION, Artifacts, codec
from tests.fixtures.gateway import (
    DIFC,
    FED,
    ScriptedProvider,
    company,
    fact,
    response,
    understanding,
)

SAFE = "Thanks. HeroOS's approved approach starts with understanding what happened first."


def asks(*actions: tuple[str, str], turn: int = 0) -> list[dict[str, Any]]:
    """Requested decisions: (option id, the founder's words asking for it, in that turn)."""
    return [{"action": a, "source_turn": turn, "support_excerpt": w} for a, w in actions]


def understood(
    message: str, *, actions: Sequence[tuple[str, str]] = (), turn: int = 0, **kwargs: Any
) -> dict[str, Any]:
    data = understanding(**kwargs)
    data["requested_actions"] = asks(*actions, turn=turn)
    return data


class Conversation:
    """One founder's conversation, the way the browser keeps it (history and continuation)."""

    def __init__(
        self, artifacts: Artifacts, *, jurisdiction: str | None = FED, confirmed: bool = True
    ) -> None:
        self.service = artifacts.service()
        self.founder: CompanyBlueprintContext = company(jurisdiction, confirmed=confirmed)
        self.history: tuple[ChatTurn, ...] = ()
        self.continuation: str | None = None
        self.provider: ScriptedProvider | None = None

    def gateway(self, provider: ScriptedProvider) -> AiGateway:
        return AiGateway(
            enabled=True,
            provider=provider,
            approval="TEST-APPROVAL-1",
            allow_development_knowledge=True,
            limits=UsageLimits(account_limit=100, global_per_minute=100, global_per_day=1000),
            evaluation=self.service,
            continuations=codec(),
        )

    def say(self, message: str, understanding: Any, reply: Any = None) -> GatewayReply:
        self.provider = ScriptedProvider(understanding, reply or response(SAFE, ["q1"]))
        result = self.gateway(self.provider).respond(
            self.founder, FounderTurn(message, self.history, self.continuation)
        )
        self.history += (ChatTurn("user", message), ChatTurn("assistant", result.reply))
        self.continuation = result.continuation
        return result

    @property
    def turn(self) -> int:
        return sum(1 for t in self.history if t.role == "user")


def kind(result: GatewayReply) -> str | None:
    return None if result.outcome is None else result.outcome.kind


def evaluation(result: GatewayReply):  # type: ignore[no-untyped-def]
    assert result.handoff.evaluation is not None
    return result.handoff.evaluation


# --- A, B, C: ordinary conversation ------------------------------------------------------------


def test_a_lateness_is_guidance_and_one_natural_question(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    message = "My employee has been late three times this month. What should I do?"
    result = chat.say(
        message, understood(message, pathway="less_serious", topics=["workplace_reminder"])
    )
    assert kind(result) == "guidance"
    assert result.outcome is not None and result.outcome.items == ()
    assert evaluation(result).actions == ()
    # No sanction, no warning, no Block because more facts are needed; one question.
    targets = chat.provider.phase("response")[0].data["approved_knowledge"]["question_targets"]  # type: ignore[union-attr]
    assert [t["about"] for t in targets] == ["Standard explained"]
    assert result.state == "responded"


def test_b_a_fact_already_said_is_reused_not_confirmed(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    message = "He's late a lot. I explained the attendance standard to him last month."
    result = chat.say(
        message,
        understood(
            message,
            pathway="less_serious",
            topics=["workplace_reminder"],
            facts=[
                fact(
                    "employee_aware_of_relevant_policy",
                    "yes",
                    "I explained the attendance standard to him",
                )
            ],
        ),
    )
    data = chat.provider.phase("response")[0].data  # type: ignore[union-attr]
    assert [t["about"] for t in data["approved_knowledge"]["question_targets"]] == []
    assert evaluation(result).missing == ()
    # Conversational: reused by the conversation, never a rule's input.
    assert evaluation(result).facts.level("employee_aware_of_relevant_policy") == (
        "established_conversational"
    )
    assert kind(result) == "guidance"


def test_c_improvement_never_escalates_mechanically(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    message = "I spoke to him about it. He improved and hasn't been late again."
    result = chat.say(
        message, understood(message, pathway="less_serious", topics=["workplace_reminder"])
    )
    assert kind(result) == "guidance" and evaluation(result).actions == ()
    assert evaluation(result).reviews == () and evaluation(result).cautions == ()


# --- D: a bound caution, with its configured severity -------------------------------------


def test_d_a_bound_caution_fires_with_its_own_severity(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    message = "I'm thinking of giving him a formal warning."
    first = chat.say(
        message,
        understood(
            message, topics=["formal_warning"], actions=[("opt-warning", "a formal warning")]
        ),
    )
    assert kind(first) == "block"
    assert evaluation(first).missing[0].key == "given_opportunity_to_explain"
    second = chat.say("No.", understood("No.", topics=["formal_warning"]))
    result = evaluation(second)
    caution = next(c for c in result.conditions if c.condition == "EX-FED-WARNING-LABEL")
    assert caution.status == "fired" and caution.action == "warn"  # the bound severity
    # The requested warning is independently blocked: the employee hasn't been heard.
    warning = next(a for a in result.actions if a.action == "opt-warning")
    assert warning.disposition == "block" and "rule:warning_response" in warning.reasons
    assert kind(second) == "block" and second.outcome is not None
    assert "Example condition EX-FED-WARNING-LABEL" in second.outcome.message


# --- E, F: serious misconduct and dismissal ---------------------------------------------------


def test_e_a_serious_allegation_and_an_immediate_dismissal(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    message = "I think she stole company money. Can I fire her today?"
    result = chat.say(
        message,
        understood(
            message,
            pathway="serious",
            topics=["serious_investigation", "dismissal_without_notice"],
            actions=[("opt-dismissal", "fire her today")],
        ),
        response("She may have taken money, so that needs looking into fairly first.", ["q1"]),
    )
    assert kind(result) == "expert_review"
    dismissal = evaluation(result).actions[0]
    assert dismissal.action == "opt-dismissal" and dismissal.disposition == "escalate"
    assert result.outcome is not None and "specialist review is required before" in (
        result.outcome.message.lower()
    )
    # The investigation methodology is still what HeroOS explains.
    knowledge = chat.provider.phase("response")[0].data["approved_knowledge"]  # type: ignore[union-attr]
    assert knowledge["approved_guidance"]
    # A reply that authorizes the dismissal never reaches the founder; the outcome stays.
    chat2 = Conversation(artifacts)
    unsafe = chat2.say(
        message,
        understood(
            message,
            pathway="serious",
            topics=["dismissal_without_notice"],
            actions=[("opt-dismissal", "fire her today")],
        ),
        response("Yes, you can go ahead and dismiss her today."),
    )
    assert "dismiss her today" not in unsafe.reply.lower()
    assert kind(unsafe) == "expert_review"


def test_f_difc_investigation_continues_and_dismissal_needs_review(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts, jurisdiction=DIFC)
    message = "We suspect serious misconduct by one of our team. How should we investigate?"
    investigating = chat.say(
        message, understood(message, pathway="serious", topics=["serious_investigation"])
    )
    assert kind(investigating) == "guidance" and evaluation(investigating).reviews == ()
    ask = "Can I dismiss them immediately without notice?"
    dismissing = chat.say(
        ask,
        understood(
            ask,
            pathway="serious",
            topics=["serious_investigation"],
            actions=[("opt-dismissal", "dismiss them immediately")],
            turn=1,
        ),
    )
    assert kind(dismissing) == "expert_review"
    (review,) = evaluation(dismissing).reviews
    assert review.scope == "action" and review.action == "opt-dismissal"


# --- G: deductions -------------------------------------------------------------------------


def test_g_a_deduction_needs_specialist_review_and_no_amount(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    message = "He damaged a laptop. Take the repair cost from his salary."
    result = chat.say(
        message,
        understood(
            message,
            topics=["salary_deduction"],
            actions=[("opt-deduction", "Take the repair cost from his salary")],
        ),
        response("You could deduct up to AED 500 a month from his salary."),
    )
    assert kind(result) == "expert_review"
    assert "500" not in result.reply  # the unsafe reply was replaced
    assert result.outcome is not None
    card = result.outcome.message.lower()
    for promise in ("ticket", "submitted", "sent to", "will respond", "assigned"):
        assert promise not in card


# --- H, I, J, K: suspensions ---------------------------------------------------------------


def test_h_investigative_suspension_is_not_disciplinary(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    message = (
        "We're investigating him and I think he may delete evidence. Can I suspend him "
        "during the investigation?"
    )
    result = chat.say(
        message,
        understood(
            message,
            pathway="serious",
            topics=["investigative_suspension"],
            actions=[("opt-investigative", "suspend him during the investigation")],
        ),
    )
    step = evaluation(result).actions[0]
    assert step.action == "opt-investigative" and step.disposition == "allow"
    assert "EX-FED-CAP" not in step.conditions
    assert kind(result) == "guidance"


def test_i_and_s_a_suspension_letter_request_doesnt_skip_prerequisites(
    artifacts: Artifacts,
) -> None:
    chat = Conversation(artifacts)
    message = "Generate the suspension letter now, I've decided to suspend him."
    result = chat.say(
        message,
        understood(
            message, topics=["disciplinary_suspension"], actions=[("opt-suspension", "suspend him")]
        ),
        response("Here is the suspension notice: Dear employee, you are suspended."),
    )
    assert kind(result) == "block"
    step = evaluation(result).actions[0]
    assert {"rule:suspension_response", "rule:suspension_investigation"} <= set(step.reasons)
    assert "here is the suspension notice" not in result.reply.lower()


def test_j_over_the_cap_warns_then_blocks_only_on_explicit_insistence(
    artifacts: Artifacts,
) -> None:
    chat = Conversation(artifacts)
    opening = "I want to suspend him without pay for 20 days as punishment."
    stated = [fact("proposed_suspension_days", "20", "for 20 days")]
    first = chat.say(
        opening,
        understood(
            opening,
            topics=["disciplinary_suspension"],
            actions=[("opt-suspension", "suspend him")],
            facts=stated,
        ),
    )
    assert kind(first) == "block"  # its prerequisites aren't established yet
    # HeroOS asks, one at a time; plain answers are trusted, its own words never are.
    asked = [evaluation(first).missing[0]]
    result = first
    # A model re-reads the founder's earlier words; the server still trusts none of them.
    earlier = [
        fact(
            "proposed_suspension_days", "20", "for 20 days", turn=0, provenance="prior_user_message"
        )
    ]
    while asked[-1].kind != "insistence" and len(asked) < 5:
        result = chat.say(
            "Yes.", understood("Yes.", topics=["disciplinary_suspension"], facts=earlier)
        )
        asked.append(evaluation(result).missing[0])
    assert [(m.key, m.kind) for m in asked[:-1]] == [
        ("given_opportunity_to_explain", "fact"),
        ("investigation_completed", "fact"),
        ("proposed_suspension_days", "confirmation"),
    ]
    assert asked[2].candidate == 20  # the server's own reading of "for 20 days"
    warned = evaluation(result)
    assert kind(result) == "warning"
    assert warned.facts.engine["proposed_suspension_days"] == 20
    assert warned.facts.sources["proposed_suspension_days"] == "confirmation"
    assert warned.missing[0].kind == "insistence"
    targets = chat.provider.phase("response")[0].data["approved_knowledge"]["question_targets"]  # type: ignore[union-attr]
    assert "go ahead" in targets[0]["ask"]  # the server's own question
    # Tone and repetition are not insistence.
    shouted = chat.say(
        "I WANT TO SUSPEND HIM FOR 20 DAYS!!!",
        understood(
            "I WANT TO SUSPEND HIM FOR 20 DAYS!!!",
            topics=["disciplinary_suspension"],
            actions=[("opt-suspension", "SUSPEND HIM")],
            turn=chat.turn,
        ),
    )
    assert kind(shouted) == "warning"
    acknowledged = chat.say("OK, understood.", understood("OK, understood."))
    assert kind(acknowledged) == "warning"
    assert evaluation(acknowledged).two_state[0].acknowledged
    # The insistence question again, then an explicit yes.
    assert evaluation(acknowledged).missing[0].kind == "insistence"
    insisted = chat.say(
        "Yes, I still want to go ahead.", understood("Yes, I still want to go ahead.")
    )
    assert kind(insisted) == "block"
    assert insisted.outcome is not None and insisted.outcome.title.startswith("Not yet")


def test_k_difc_unpaid_disciplinary_suspension_needs_review(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts, jurisdiction=DIFC)
    message = "I want to suspend him without pay for 10 days as punishment."
    result = chat.say(
        message,
        understood(
            message,
            topics=["disciplinary_suspension"],
            actions=[("opt-suspension", "suspend him without pay")],
            facts=[fact("proposed_suspension_days", "10", "for 10 days")],
        ),
        response("In DIFC, more than 9 days isn't allowed."),
    )
    assert kind(result) == "expert_review"
    assert all(c.condition != "EX-FED-CAP" for c in evaluation(result).conditions)
    assert "9 days" not in result.reply  # no Federal cap stated as DIFC authority


# --- L, M, N: content statuses --------------------------------------------------------------


def test_l_a_quarantined_route_stays_narrow(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    message = "Can I delay his pay rise because of this?"
    result = chat.say(
        message,
        understood(
            message,
            topics=["delay_increase_or_promotion"],
            actions=[("opt-delay", "delay his pay rise")],
        ),
    )
    assert result.handoff.knowledge_status != "source_conflict"
    assert kind(result) == "warning"  # not covered by executable rules: never clear, never blocked
    assert evaluation(result).actions[0].disposition == "unknown"


def test_m_needs_legal_review_is_conservative_and_qualified(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    message = "He keeps ignoring the dress code."
    chat.say(message, understood(message, topics=["workplace_reminder"]))
    result = chat.say(
        "No.",
        understood("No.", topics=["workplace_reminder"]),
        response("The law definitely requires you to train him first."),
    )
    assert kind(result) == "warning"
    assert result.outcome is not None and PROVISIONAL in result.outcome.message
    assert "law definitely" not in result.reply.lower()


def test_n_not_enforced_has_no_effect(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    message = "Should I be thinking about his pay at all?"
    result = chat.say(message, understood(message, topics=["salary_deduction"]))
    entry = next(c for c in evaluation(result).conditions if c.condition == "EX-FED-OLD-DEDUCTION")
    assert entry.category == "not_enforced" and entry.status == "not_evaluated"
    assert all(c.source != "EX-FED-OLD-DEDUCTION" for c in evaluation(result).cautions)
    assert kind(result) == "guidance"


# --- O: jurisdiction ------------------------------------------------------------------------


def test_o_no_jurisdiction_specific_result_while_unresolved(artifacts: Artifacts) -> None:
    unconfirmed = Conversation(artifacts, jurisdiction=None, confirmed=False)
    message = "We're in Dubai. Can I give him a written warning?"
    result = unconfirmed.say(
        message,
        understood(
            message, topics=["formal_warning"], actions=[("opt-warning", "a written warning")]
        ),
    )
    assert kind(result) == "block" and evaluation(result).jurisdiction is None
    assert result.outcome is not None and "Company Blueprint" in result.outcome.message
    # The founder's words suggest another employer: unresolved until their trusted answer.
    chat = Conversation(artifacts)
    message = "He's actually employed by our sister company. Can I warn him?"
    conflicted = chat.say(
        message,
        understood(
            message,
            topics=["formal_warning"],
            uncertainties=["jurisdiction_conflict"],
            actions=[("opt-warning", "warn him")],
        ),
    )
    assert kind(conflicted) == "block"
    assert evaluation(conflicted).missing[0].kind == "jurisdiction"
    targets = chat.provider.phase("response")[0].data["approved_knowledge"]["question_targets"]  # type: ignore[union-attr]
    assert "UAE Federal" in targets[0]["ask"]
    answered = chat.say("Yes.", understood("Yes.", uncertainties=["jurisdiction_conflict"]))
    assert evaluation(answered).jurisdiction == FED
    assert evaluation(answered).jurisdiction_state == "resolved"


def test_o_an_employee_not_confirmed_under_the_jurisdiction_gets_shared_guidance_only(
    artifacts: Artifacts,
) -> None:
    """M2-NEW-07: "Not sure" about this employee pauses only what depends on the jurisdiction."""
    resolved = Conversation(artifacts)
    message = "He may be employed by our sister company. Can I warn him?"
    warning = [("opt-warning", "warn him")]
    plain = "Can I warn him?"
    resolved.say(plain, understood(plain, topics=["formal_warning"], actions=warning))
    federal = json.dumps(resolved.provider.phase("response")[0].data["approved_knowledge"])  # type: ignore[union-attr]
    assert "900 days" in federal  # a UAE Federal paragraph, under the confirmed jurisdiction
    chat = Conversation(artifacts)
    chat.say(
        message,
        understood(
            message,
            topics=["formal_warning"],
            uncertainties=["jurisdiction_conflict"],
            actions=warning,
        ),
    )
    answered = chat.say("Not sure.", understood("Not sure.", topics=["formal_warning"]))
    result = evaluation(answered)
    assert result.jurisdiction_state == "case_not_sure" and result.jurisdiction is None
    # The jurisdiction-specific decision is held until the jurisdiction is confirmed ...
    (step,) = result.actions
    assert step.disposition == "block" and "jurisdiction:case_not_sure" in step.reasons
    # ... while the shared guidance continues, and no UAE Federal text reaches the model.
    data = chat.provider.phase("response")[0].data  # type: ignore[union-attr]
    shared = json.dumps(data["approved_knowledge"])
    assert data["approved_knowledge"]["approved_guidance"]
    assert "900 days" not in shared
    assert data["jurisdiction_note"].startswith("Not confirmed for this employee")


# --- P, Q, R: matters ------------------------------------------------------------------------


def test_p_unsupported_hr_is_a_specialist_requirement(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    result = chat.say(
        "Help me build our 2027 staffing strategy.", understanding(intent="other_hr", workflow=None)
    )
    assert kind(result) == "expert_review" and result.reply.startswith(OUTSIDE_HR[:40])
    assert result.outcome is not None and "ticket" not in result.outcome.message.lower()
    assert not evaluation(result).reviews[0].service_available


def test_q_outside_heroos_is_neutral(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    result = chat.say(
        "Write a Python script for me.", understanding(intent="unsupported", workflow=None)
    )
    assert result.outcome is None and result.reply.startswith(OUTSIDE[:40])
    assert "consultancy" not in result.reply and "specialist" not in result.reply


def test_r_several_matters_are_taken_one_at_a_time(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    message = "I need to discipline one employee and hire a replacement."
    result = chat.say(
        message,
        understood(message, topics=["workplace_reminder"], uncertainties=["multiple_matters"]),
    )
    assert evaluation(result).next_step == "choose_matter"
    assert evaluation(result).workflow == "disciplinary"
    assert all(a.action.startswith("opt-") for a in evaluation(result).actions)


def test_the_second_workflow_runs_through_the_same_gateway(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    message = "Her trial ends soon and I want to end her employment."
    result = chat.say(
        message,
        understood(
            message,
            workflow=PROBATION,
            topics=["trial_end"],
            actions=[("sp-end", "end her employment")],
        ),
    )
    assert evaluation(result).workflow == PROBATION
    assert kind(result) == "block"  # its own prerequisites, its own rules
    assert evaluation(result).provenance.workflow == PROBATION  # type: ignore[union-attr]


# --- AI failures never weaken a deterministic result (, ) -------------------------------


@pytest.mark.parametrize("error", ["timeout", "unavailable", "rate_limited"])
def test_a_provider_failure_after_a_block_keeps_the_block(artifacts: Artifacts, error: str) -> None:
    chat = Conversation(artifacts)
    message = "Generate the warning letter now."
    result = chat.say(
        message,
        understood(
            message, topics=["formal_warning"], actions=[("opt-warning", "the warning letter")]
        ),
        AssistantError(error),
    )  # type: ignore[arg-type]
    assert kind(result) == "block"
    assert "couldn't put together a fuller reply" in result.reply
    assert "can't safely proceed" in result.reply


def test_malformed_output_after_expert_review_keeps_it(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    message = "Take the repair cost from his salary."
    result = chat.say(
        message,
        understood(
            message,
            topics=["salary_deduction"],
            actions=[("opt-deduction", "Take the repair cost from his salary")],
        ),
        ["not json", "{also not json"],
    )  # type: ignore[arg-type]
    assert kind(result) == "expert_review"
    assert "specialist review is required" in result.reply.lower()


def test_a_provider_failure_with_ordinary_guidance_still_fails(artifacts: Artifacts) -> None:
    from app.assistant.gateway.service import GatewayFailure

    chat = Conversation(artifacts)
    message = "He was late twice."
    with pytest.raises(GatewayFailure):
        chat.say(
            message, understood(message, topics=["workplace_reminder"]), AssistantError("timeout")
        )  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("message", "actions", "reply"),
    [
        (
            "Generate the warning letter now.",
            [("opt-warning", "the warning letter")],
            "You can go ahead and issue it.",
        ),
        (
            "Can I fire her today?",
            [("opt-dismissal", "fire her today")],
            "No specialist review is needed here.",
        ),
        (
            "Can I just remind him?",
            [("opt-reminder", "remind him")],
            "There's nothing you need to address.",
        ),
    ],
)
def test_a_reply_contradicting_the_outcome_is_replaced(
    artifacts: Artifacts, message: str, actions: list[tuple[str, str]], reply: str
) -> None:
    chat = Conversation(artifacts)
    result = chat.say(message, understood(message, actions=actions), response(reply))
    assert reply not in result.reply
    assert result.handoff.evaluation is not None and kind(result) in (
        "block",
        "expert_review",
        "warning",
    )


# --- one immutable snapshot per turn -----------------------------------------------------


class _SwappingProvider(ScriptedProvider):
    """Installs another snapshot while the turn is still running."""

    def __init__(self, runtime: ExecutionRuntime, other: Any, *args: Any) -> None:
        super().__init__(*args)
        self.runtime, self.other = runtime, other

    def complete_json(self, *args: Any, **kwargs: Any) -> Any:
        self.runtime.install(self.other)
        return super().complete_json(*args, **kwargs)


def test_a_turn_never_mixes_two_versions(artifacts: Artifacts) -> None:
    first = artifacts.snapshot()
    runtime = ExecutionRuntime(first)
    artifacts.profile["workflows"][0]["knowledge_runtime_digest"] = "f" * 64
    later = artifacts.snapshot()  # incompatible: evaluation unavailable
    message = "Can I fire her today?"
    provider = _SwappingProvider(
        runtime,
        later,
        understood(
            message,
            topics=["dismissal_without_notice"],
            actions=[("opt-dismissal", "fire her today")],
        ),
        response(SAFE),
    )
    ai = AiGateway(
        enabled=True,
        provider=provider,
        approval="T-1",
        allow_development_knowledge=True,
        limits=UsageLimits(account_limit=100, global_per_minute=100, global_per_day=1000),
        evaluation=ConversationEvaluationService(runtime),
        continuations=codec(),
    )
    result = ai.respond(company(), FounderTurn(message))
    assert runtime.current() is later
    # Classified, evaluated and phrased on the snapshot the turn started with.
    assert result.handoff.evaluation is not None
    assert result.handoff.evaluation.provenance.snapshot == first.id  # type: ignore[union-attr]
    assert kind(result) == "expert_review"


# --- trusted state across turns ------------------------------------------------------------


def test_another_instance_continues_the_conversation(artifacts: Artifacts) -> None:
    """The continuation is multi-instance safe: a new gateway (process) with the shared key."""
    chat = Conversation(artifacts)
    message = "Can I give him a formal warning?"
    chat.say(
        message,
        understood(
            message, topics=["formal_warning"], actions=[("opt-warning", "a formal warning")]
        ),
    )
    chat.service = artifacts.service()  # another process: nothing shared but the key
    answered = chat.say("Yes.", understood("Yes.", topics=["formal_warning"]))
    assert evaluation(answered).facts.engine["given_opportunity_to_explain"] == "yes"
    assert kind(answered) == "guidance"


def test_a_lost_continuation_never_loosens_a_result(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    message = "Can I give him a formal warning?"
    chat.say(
        message,
        understood(
            message, topics=["formal_warning"], actions=[("opt-warning", "a formal warning")]
        ),
    )
    chat.continuation = None  # lost (or tampered, expired, replayed)
    result = chat.say(
        "Yes.",
        understood(
            "Yes.", topics=["formal_warning"], actions=[("opt-warning", "a formal warning")], turn=0
        ),
    )
    # Nothing trusted came back: the warning stays blocked and HeroOS asks again.
    assert "given_opportunity_to_explain" not in evaluation(result).facts.engine
    assert kind(result) == "block"
    assert evaluation(result).missing[0].key == "given_opportunity_to_explain"


def test_an_off_topic_turn_never_drops_trusted_state(artifacts: Artifacts) -> None:
    """A turn with nothing to evaluate carries the state; the next turn still blocks."""
    chat = Conversation(artifacts)
    facts = [
        fact(
            "proposed_suspension_days", "20", "for 20 days", turn=0, provenance="prior_user_message"
        )
    ]
    opening = "I want to suspend him without pay for 20 days as punishment."
    chat.say(
        opening,
        understood(
            opening,
            topics=["disciplinary_suspension"],
            actions=[("opt-suspension", "suspend him")],
            facts=[fact("proposed_suspension_days", "20", "for 20 days")],
        ),
    )
    while (
        evaluation(
            result := chat.say(
                "Yes.", understood("Yes.", topics=["disciplinary_suspension"], facts=facts)
            )
        )
        .missing[0]
        .kind
        != "insistence"
    ):
        pass
    blocked = chat.say(
        "Yes, I still want to go ahead.", understood("Yes, I still want to go ahead.")
    )
    assert kind(blocked) == "block" and kind(result) == "warning"
    aside = chat.say(
        "Can you write me a Python script?", understanding(intent="unsupported", workflow=None)
    )
    assert aside.outcome is None
    back = "So, about that suspension."
    again = chat.say(
        back,
        understood(
            back,
            topics=["disciplinary_suspension"],
            actions=[("opt-suspension", "that suspension")],
            facts=facts,
            turn=chat.turn,
        ),
    )
    assert kind(again) == "block"  # the insistence and the trusted facts came back
    assert evaluation(again).facts.engine["proposed_suspension_days"] == 20


def test_another_matters_state_is_never_applied(artifacts: Artifacts) -> None:
    chat = Conversation(artifacts)
    message = "Can I give him a formal warning?"
    chat.say(
        message,
        understood(
            message, topics=["formal_warning"], actions=[("opt-warning", "a formal warning")]
        ),
    )
    chat.say("Yes.", understood("Yes.", topics=["formal_warning"]))
    other = "Separately, her trial ends soon and I want to end her employment."
    result = chat.say(
        other,
        understood(
            other,
            workflow=PROBATION,
            topics=["trial_end"],
            actions=[("sp-end", "end her employment")],
            turn=2,
        ),
    )
    assert evaluation(result).workflow == PROBATION
    assert "given_opportunity_to_explain" not in evaluation(result).facts.engine
