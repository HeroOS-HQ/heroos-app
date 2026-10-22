"""M2-NEW-08: Disciplinary as the end-to-end reference workflow, through the real application.

The same harness as test_http.py (SQLite stand-ins, Cognito tokens verified by
the production provider, the real gateway on the fictional execution content,
a scripted provider), with the synthetic progression rules installed and the
synthetic demo screening on, so a Case can move through its formal stages:

- Ask HeroOS is the entry and the conversation: a greeting gets a greeting, a
  situation becomes a Case, ordinary trusted facts reach it through the shared
  mutation pipeline;
- every formal step (pathway, stages, checklists) is the employer's own
  request through the Case's routes; the AI reads the Case's position
  (``case_progress``), never writes it, and never claims it did;
- an employer decision's prerequisite can need the Case's formal record (a
  completed stage, a stage checklist answer): the chat never satisfies it, and
  a stage another administrator completes while HeroOS answers relaxes the
  result at commit, discarding the stale wording;
- hypothetical and explicit decisions, action-level Expert Review that never
  pauses the Case, jurisdiction isolation and change, and the 08/09 boundary.

Scenario letters follow the M2-NEW-08 brief (A-Q). Everything is fictional.
"""

import uuid
from collections.abc import Generator
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.assistant.gateway.service import GREETING, AiGateway, FounderTurn, GatewayReply
from app.assistant.limits import UsageLimits
from app.auth.dependencies import get_authentication_provider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.companies.blueprint import CompanyBlueprintContext
from app.conversations.checkpoint import decode
from app.db.base import Base
from app.db.models import (
    AssistantConversation,
    AssistantMessage,
    AssistantTurn,
    AssistantTurnEvaluation,
    CaseFact,
    CompanyBlueprint,
    Membership,
    WorkflowDecisionRecord,
    WorkflowProgressEvent,
    WorkflowSubmission,
)
from app.db.session import get_db
from app.evaluation.evaluator import EvaluationRequest, evaluate_conversation
from app.evaluation.model import TrustedFactState, TwoState
from app.evaluation.presentation import CASE_STEP_NOTE
from app.main import create_app
from app.workflows.conditions import Tri
from app.workflows.definition import SAFETY_SCREENING
from tests.auth.conftest import CognitoTokenFactory, SeedData, bearer
from tests.auth.test_company_admin_api import make_admin
from tests.auth.test_company_api import staging_settings
from tests.auth.test_workflow_api import admin_alice, alice  # noqa: F401  (pytest fixtures)
from tests.evaluation.test_golden import understood
from tests.fixtures.evaluation import Artifacts, codec, rule_bundle
from tests.fixtures.gateway import ScriptedProvider, response

SAFE = "Thanks. Let's take this one step at a time."
ABSENT = "An employee hasn't come to work for three days and isn't responding."
INITIAL = {
    "incident.narrative": "[SYNTHETIC] Three days absent without contact.",
    "incident.date": "2026-10-10",
    "incident.history": "new",
    "incident.discussed_with_employee": "no",
    "incident.evidence_available": "yes",
}
CONTEXT = {
    "context.location": "at_work",
    "history.same_incident_sanction": "no",
    "context.policy_awareness": "yes",
    "evidence.witnesses": "no",
}
CLEAR = {q.key: "no" for q in SAFETY_SCREENING.questions}
OUTCOME = ("opt-outcome", "issue the penalty notice")
OUTCOME_TITLE = "Example disciplinary_penalty_notice"
DISMISSAL_TITLE = "Example dismissal_without_notice"
NOTICE = "Test stage A: Written notice"
MEETING = "Test stage C: Meeting"


def absent(
    message: str = ABSENT,
    turn: int = 0,
    topics: tuple[str, ...] = ("misconduct_level",),
    **kwargs: Any,
) -> dict[str, Any]:
    return understood(message, topics=list(topics), turn=turn, **kwargs)


def hypothetical(data: dict[str, Any], action: str, words: str, turn: int) -> dict[str, Any]:
    data["hypothetical_actions"] = [
        {"action": action, "source_turn": turn, "support_excerpt": words}
    ]
    return data


class Journey:
    """One administrator: Ask HeroOS turns and the Case's own controls, through the real routes."""

    def __init__(
        self,
        db: sessionmaker[Session],
        auth: CognitoAccessTokenProvider,
        artifacts: Artifacts,
        headers: dict[str, str],
        company: uuid.UUID,
    ) -> None:
        self.db, self.auth, self.artifacts = db, auth, artifacts
        self.headers, self.company = headers, company
        self.evaluation = artifacts.service()
        self.rules = rule_bundle(artifacts.disciplinary)
        self.conversation: str | None = None
        self.revision = 0
        self.case: str | None = None
        self.chat: ScriptedProvider | None = None
        self.gateway_class: type[AiGateway] = AiGateway

    def client(self, chat: ScriptedProvider | None = None) -> TestClient:
        app = create_app(
            staging_settings().model_copy(update={"heroos_sensitive_screening": "synthetic_demo"})
        )
        # The synthetic progression rules (with their conversation section), installed.
        app.state.rule_bundle = self.rules
        app.state.ai_gateway = self.gateway_class(
            enabled=True,
            provider=chat or ScriptedProvider(understood("x")),
            approval="TEST-APPROVAL-1",
            allow_development_knowledge=True,
            limits=UsageLimits(account_limit=500, global_per_minute=500, global_per_day=5000),
            evaluation=self.evaluation,
            continuations=codec(),
        )

        def _db() -> Generator[Session, None, None]:
            with self.db() as session:
                yield session

        app.dependency_overrides[get_authentication_provider] = lambda: self.auth
        app.dependency_overrides[get_db] = _db
        return TestClient(app)

    # --- Ask HeroOS ---------------------------------------------------------------------------

    def ask(self, message: str, proposal: Any, reply: Any = None) -> dict[str, Any]:
        self.chat = ScriptedProvider(proposal, reply or response(SAFE, ["q1"]))
        body: dict[str, Any] = {
            "message": message,
            "turn_key": str(uuid.uuid4()),
            "expected_revision": self.revision,
        }
        if self.conversation is not None:
            body["conversation_id"] = self.conversation
        answered = self.client(self.chat).post(
            f"/companies/{self.company}/assistant/messages", headers=self.headers, json=body
        )
        assert answered.status_code == 200, answered.text
        data: dict[str, Any] = answered.json()
        self.conversation = data["conversation"]["id"]
        self.revision = data["conversation"]["revision"]
        case = data["conversation"]["case"]
        self.case = None if case is None else case["id"]
        return data

    def detail(self, client: TestClient | None = None) -> dict[str, Any]:
        found = (client or self.client()).get(
            f"/companies/{self.company}/assistant/conversations/{self.conversation}",
            headers=self.headers,
        )
        assert found.status_code == 200, found.text
        detail: dict[str, Any] = found.json()
        return detail

    def sections(self) -> dict[str, Any]:
        """What the response phase of the last turn was given (the model's data)."""
        assert self.chat is not None
        calls = self.chat.phase("response")
        assert calls, "no response request"
        data: dict[str, Any] = calls[0].data
        return data

    # --- the Case's own controls (the employer's requests) ------------------------------------

    def view(self) -> dict[str, Any]:
        found = self.client().get(
            f"/companies/{self.company}/cases/{self.case}/workflow", headers=self.headers
        )
        assert found.status_code == 200, found.text
        view: dict[str, Any] = found.json()
        return view

    def put(self, step: str, answers: dict[str, str]) -> dict[str, Any]:
        current = self.view()
        changed = {k: v for k, v in answers.items() if current["answers"].get(k) != v}
        saved = self.client().put(
            f"/companies/{self.company}/cases/{self.case}/workflow/steps/{step}/answers",
            headers=self.headers,
            json={
                "expected_revision": current["workflow"]["revision"],
                "submission_key": str(uuid.uuid4()),
                "answers": changed,
            },
        )
        assert saved.status_code == 200, saved.text
        view: dict[str, Any] = saved.json()
        return view

    def intake(self) -> dict[str, Any]:
        """The whole intake through the answers route (the "Review case details" form's)."""
        self.put("initial_facts", INITIAL)
        self.put("jurisdiction", {"jurisdiction.case_confirmation": self.jurisdiction()})
        self.put("incident_context", CONTEXT)
        return self.put("safety_screening", CLEAR)

    def jurisdiction(self) -> str:
        question = next(
            q for s in self.view()["steps"] if s["key"] == "jurisdiction" for q in s["questions"]
        )
        value: str = question["options"][0]["value"]
        return value

    def pathway(self, choice: str) -> dict[str, Any]:
        view = self.view()
        chosen = self.client().post(
            f"/companies/{self.company}/cases/{self.case}/workflow/progression/pathway",
            headers=self.headers,
            json={
                "expected_revision": view["workflow"]["revision"],
                "request_key": str(uuid.uuid4()),
                "pathway": choice,
            },
        )
        assert chosen.status_code == 200, chosen.text
        result: dict[str, Any] = chosen.json()
        return result

    def transition(self, key: str, acknowledged: list[str] | None = None) -> dict[str, Any]:
        view = self.view()
        moved = self.client().post(
            f"/companies/{self.company}/cases/{self.case}/workflow/progression/transitions",
            headers=self.headers,
            json={
                "expected_revision": view["workflow"]["revision"],
                "request_key": str(uuid.uuid4()),
                "transition": key,
                "acknowledged_warnings": acknowledged or [],
            },
        )
        assert moved.status_code == 200, moved.text
        result: dict[str, Any] = moved.json()
        assert result["progression"]["attempt"]["outcome"] == "applied", result["progression"][
            "attempt"
        ]
        return result

    def investigate(self) -> None:
        """The serious pathway's notice and meeting stages, as the employer records them."""
        self.transition("start:test_notice")
        self.put("test_notice", {"progress.test_notice.notice_given": "yes"})
        self.transition("complete:test_notice")
        self.transition("start:test_meeting")
        self.put("test_meeting", {"progress.test_meeting.meeting_held": "yes"})
        self.transition("complete:test_meeting")


@pytest.fixture
def journey(
    db: sessionmaker[Session],
    cognito_provider: CognitoAccessTokenProvider,
    artifacts: Artifacts,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> Journey:
    return Journey(db, cognito_provider, artifacts, admin_alice, seed.company_a)


def colleague(
    db: sessionmaker[Session], seed: SeedData, make_cognito_token: CognitoTokenFactory, of: Journey
) -> Journey:
    """carol: another active administrator of Company A (her own sign-in), on the same Case."""
    with db() as session:
        session.add(Membership(company_id=seed.company_a, user_id=seed.carol))
        session.commit()
    make_admin(db, seed.company_a, seed.carol)
    other = Journey(
        db, of.auth, of.artifacts, bearer(make_cognito_token("carol-subject")), seed.company_a
    )
    other.rules, other.evaluation = of.rules, of.evaluation
    other.conversation, other.revision, other.case = of.conversation, of.revision, of.case
    return other


def rows(db: sessionmaker[Session], model: type[Base]) -> int:
    with db() as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def progress_events(db: sessionmaker[Session]) -> list[WorkflowProgressEvent]:
    with db() as session:
        return list(session.scalars(select(WorkflowProgressEvent)).all())


def to_difc(db: sessionmaker[Session], company: uuid.UUID) -> None:
    """The operator confirms another employment jurisdiction for the Company (its Blueprint)."""
    with db() as session:
        session.execute(
            update(CompanyBlueprint)
            .where(CompanyBlueprint.company_id == company)
            .values(
                licensing_location="difc",
                licensing_authority=None,
                employment_jurisdiction="difc",
                confirmed_licensing_location="difc",
                confirmed_licensing_authority=None,
                jurisdiction_confirmed_at=datetime.now(UTC),
            )
        )
        session.commit()


def latest_record(db: sessionmaker[Session]) -> dict[str, Any]:
    """The newest turn's evaluation record (by turn order: SQLite stores whole seconds)."""
    with db() as session:
        found = session.scalars(
            select(AssistantTurnEvaluation)
            .join(AssistantTurn, AssistantTurn.id == AssistantTurnEvaluation.turn_id)
            .order_by(AssistantTurn.sequence.desc())
        ).first()
        assert found is not None
        record: dict[str, Any] = found.record
        return record


def last_heroos(data: dict[str, Any]) -> dict[str, Any]:
    message: dict[str, Any] = data["messages"][-1]
    assert message["author"] == "heroos"
    return message


def at_the_meeting(journey: Journey) -> None:
    """A Federal Case through Ask HeroOS, its intake, the serious pathway, the notice stage."""
    journey.ask(ABSENT, absent())
    journey.intake()
    journey.pathway("serious")
    journey.transition("start:test_notice")
    journey.put("test_notice", {"progress.test_notice.notice_given": "yes"})
    journey.transition("complete:test_notice")
    journey.transition("start:test_meeting")


# --- A: natural disciplinary intake ------------------------------------------------------------


def test_a_a_greeting_gets_a_greeting_and_a_situation_becomes_a_case(
    journey: Journey, db: sessionmaker[Session]
) -> None:
    hello = journey.ask("Hi Hannah", absent("Hi Hannah"))
    # No model request for a greeting and nothing evaluated. Chat-first Case: the conversation
    # has its bare Case from the first message, but "Hi" is no fact.
    assert journey.chat is not None and journey.chat.calls == []
    assert last_heroos(hello)["text"] == GREETING
    assert hello["conversation"]["case"]["title"] == "New case"
    greeted = journey.case
    assert greeted is not None and rows(db, CaseFact) == 0

    situation = journey.ask(ABSENT, absent(turn=1, topics=("workplace_reminder",)))
    # The workflow attaches to the same Case; the situation is its narrative.
    assert journey.case == greeted
    assert situation["conversation"]["status"]["workflow"]["key"] == "disciplinary"
    assert journey.view()["answers"]["incident.narrative"] == ABSENT
    # One focused question, phrased by HeroOS (never the whole question group).
    targets = journey.sections()["approved_knowledge"]["question_targets"]
    assert 1 <= len(targets) <= 3
    assert last_heroos(situation)["text"].startswith(SAFE)

    # HeroOS asked one thing (whether the standard was explained); the founder's direct answer
    # is an ordinary trusted fact: it reaches the Case through the shared pipeline (an Ask
    # HeroOS submission), with no form.
    with db() as session:
        stored = session.scalars(select(AssistantConversation.checkpoint)).one()
    checkpoint = decode(stored)
    assert checkpoint is not None
    assert [a.key for a in checkpoint.state.asked] == ["employee_aware_of_relevant_policy"]
    journey.ask("Yes.", absent("Yes.", turn=2, topics=("workplace_reminder",)))
    view = journey.view()
    assert view["answers"]["context.policy_awareness"] == "yes"
    with db() as session:
        origins = session.execute(
            select(WorkflowSubmission.step_key, WorkflowSubmission.origin).order_by(
                WorkflowSubmission.revision
            )
        ).all()
    # The narrative, then the answer: both Ask HeroOS submissions.
    assert [tuple(o) for o in origins] == [("ask_heroos", "assistant")] * 2


# --- B, C: pathway ownership and serious misconduct --------------------------------------------


def test_b_c_the_pathway_is_the_employers_and_a_serious_concern_is_no_finding(
    journey: Journey, db: sessionmaker[Session]
) -> None:
    serious = "He took money from the till. This is serious."
    data = journey.ask(
        serious,
        understood(serious, pathway="serious", topics=["misconduct_level"]),
        # The model classifies the conduct: never shown.
        response("This sounds like serious misconduct, so dismissal is the next step."),
    )
    reply = last_heroos(data)["text"]
    assert "sounds like serious misconduct" not in reply
    # The AI's candidate stays a candidate: no pathway recorded, no stage, no decision.
    assert progress_events(db) == []
    assert rows(db, WorkflowDecisionRecord) == 0
    assert journey.view()["progression"]["pathway"] is None
    record = latest_record(db)
    assert record["pathway"] == {
        "candidate": "serious",
        "ownership": "employer_confirmation_required",
    }
    assert record["actions"] == []  # describing serious conduct asks for no dismissal

    # The employer records the pathway, in the Case, explicitly.
    journey.intake()
    chosen = journey.pathway("serious")
    assert chosen["progression"]["pathway"]["label"] == "Serious misconduct"
    # Ask HeroOS reads it next turn, as the employer's (never HeroOS's) decision.
    journey.ask("What happens now?", absent("What happens now?", turn=1))
    progress = journey.sections()["case_progress"]
    assert progress["pathway"]["label"] == "Serious misconduct"
    assert "HeroOS didn't classify" in progress["pathway"]["decided_by"]
    assert progress["next_stages"] == [NOTICE]
    # Formal progression remains required: no stage completed, dismissal not reachable here.
    assert progress["stages_completed"] == []
    assert [e.kind for e in progress_events(db)] == ["pathway_selected"]


# --- D: Ask HeroOS reads the Case's progression; chat never moves it ---------------------------


def test_d_ask_reads_the_stage_in_progress_and_then_the_new_position(
    journey: Journey, db: sessionmaker[Session]
) -> None:
    journey.ask(ABSENT, absent())
    journey.intake()
    journey.pathway("serious")
    journey.transition("start:test_notice")
    data = journey.ask("Where are we?", absent("Where are we?", turn=1))
    progress = journey.sections()["case_progress"]
    assert progress["stage_in_progress"] == NOTICE
    assert progress["stage_still_needs"] == ["Test notice given"]
    assert progress["company_can_do_now_in_case"] == []  # the checklist comes first
    position = data["conversation"]["status"]["position"]
    assert position == {
        "state": "in_stage",
        "label": "Stage in progress",
        "pathway": "Serious misconduct",
        "stage": NOTICE,
        "stage_in_progress": True,
        "held_steps": [],
    }
    # Nothing the model sees is an internal id, a rule or a raw row.
    text = repr(progress)
    assert "test_notice" not in text and "progress." not in text and "rule" not in text

    # "Mark it complete" in the chat moves nothing, and a claim that it did is never shown.
    before = len(progress_events(db))
    asked = "Mark the notice stage complete."
    claimed = journey.ask(
        asked, absent(asked, turn=2), response("Done: I completed the stage for you.")
    )
    assert "I completed the stage" not in last_heroos(claimed)["text"]
    assert len(progress_events(db)) == before

    # The employer completes it in the Case; the next turn reads the new position.
    journey.put("test_notice", {"progress.test_notice.notice_given": "yes"})
    journey.transition("complete:test_notice")
    journey.ask("And now?", absent("And now?", turn=3))
    progress = journey.sections()["case_progress"]
    assert progress["stage_in_progress"] is None
    assert progress["stages_completed"] == [NOTICE]
    assert set(progress["next_stages"]) == {"Test stage B (optional): Paid pause", MEETING}


# --- E, L, O: a prerequisite only the Case establishes; recovery; another administrator --------


def test_e_l_a_case_step_prerequisite_blocks_and_relaxes_once_recorded(
    journey: Journey, db: sessionmaker[Session]
) -> None:
    journey.ask(ABSENT, absent())
    journey.intake()
    journey.pathway("serious")
    want = "I want to issue the penalty notice."
    # The founder says the investigation is done: words never satisfy a Case step.
    said = "The investigation is done and he was heard."
    blocked = journey.ask(said + " " + want, absent(said + " " + want, turn=1, actions=[OUTCOME]))
    outcome = last_heroos(blocked)["outcome"]
    assert outcome["kind"] == "block"
    assert CASE_STEP_NOTE in outcome["message"]
    action = latest_record(db)["actions"][0]
    assert action["disposition"] == "block" and action["next_step"] == "complete_case_step"
    assert action["missing"] == []  # never asked in the chat: it's the Case's record
    assert {"rule:outcome_investigation", "rule:outcome_response"} <= set(action["reasons"])
    # A Block holds the step, never the Case: the formal workflow carries on.
    assert blocked["conversation"]["status"]["lifecycle"] == "in_progress"
    assert any(a["allowed"] for a in journey.view()["progression"]["actions"])

    # The employer records the investigation in the Case: a fresh evaluation relaxes it.
    journey.investigate()
    again = journey.ask(want, absent(want, turn=2, actions=[OUTCOME]))
    assert last_heroos(again)["outcome"]["kind"] == "guidance"
    assert latest_record(db)["case_progress"]["applied"] is True


def test_l_o_a_stage_completed_by_another_administrator_meanwhile_wins_at_commit(
    journey: Journey,
    db: sessionmaker[Session],
    seed: SeedData,
    make_cognito_token: CognitoTokenFactory,
) -> None:
    at_the_meeting(journey)
    journey.put("test_meeting", {"progress.test_meeting.meeting_held": "yes"})
    carol = colleague(db, seed, make_cognito_token, journey)

    class Meanwhile(AiGateway):
        """carol completes the meeting stage while HeroOS answers (no row is locked meanwhile)."""

        def respond(self, company: CompanyBlueprintContext, turn: FounderTurn) -> GatewayReply:
            prepared = super().respond(company, turn)
            carol.transition("complete:test_meeting")
            return prepared

    journey.gateway_class = Meanwhile
    want = "Can I issue the penalty notice now?"
    stale = "Not yet: the meeting stage still has to be completed first."
    data = journey.ask(want, absent(want, turn=1, actions=[OUTCOME]), response(stale))
    heroos = last_heroos(data)
    # The fresh authoritative result wins, and the stale model wording is discarded.
    assert heroos["outcome"]["kind"] == "guidance"
    assert stale not in heroos["text"]
    assert heroos["text"].startswith("This case changed while I was answering")
    assert latest_record(db)["actions"][0]["disposition"] == "allow"
    with db() as session:
        stored = session.scalars(select(AssistantMessage.content)).all()
    assert all(stale not in text for text in stored)


# --- F: Federal suspension (duration, prerequisites, unknowns) ---------------------------------


@pytest.mark.parametrize(
    ("facts", "insists", "disposition", "next_step"),
    [
        # Within the fictional cap, both prerequisites ENGINE_TRUSTED: no rule prevents it
        # (never "lawful" or "approved": still the employer's decision).
        ({"days": 5, "investigated": "yes", "heard": "yes"}, None, "allow", "continue_methodology"),
        # A prerequisite missing: a Block, never Guidance.
        ({"days": 5, "heard": "yes"}, None, "block", "establish_prerequisite"),
        # Beyond the supported route: a caution first (two-state)...
        ({"days": 20, "investigated": "yes", "heard": "yes"}, None, "warn", "consider_caution"),
        # ...and a Block once the employer explicitly insists.
        ({"days": 20, "investigated": "yes", "heard": "yes"}, Tri.TRUE, "block", None),
        # "Not sure" is unknown, never "no": the step can't be clear.
        ({"days": 5, "investigated": "yes", "heard": "not_sure"}, None, "block", None),
        # The duration unknown: the cap can't be checked, so it stays a caution, never clear.
        ({"investigated": "yes", "heard": "yes"}, None, "warn", None),
    ],
    ids=["clear", "missing", "over_cap", "insists", "not_sure", "no_duration"],
)
def test_f_federal_suspension_duration_prerequisites_and_unknowns(
    artifacts: Artifacts,
    facts: dict[str, Any],
    insists: Tri | None,
    disposition: str,
    next_step: str | None,
) -> None:
    names = {
        "days": "proposed_suspension_days",
        "investigated": "investigation_completed",
        "heard": "given_opportunity_to_explain",
    }
    engine = {names[k]: v for k, v in facts.items()}
    two_state = (
        {} if insists is None else {"fictional_cap": TwoState("fictional_cap", True, True, insists)}
    )
    evaluation = evaluate_conversation(
        artifacts.snapshot(),
        EvaluationRequest(
            matter="supported",
            workflow="disciplinary",
            company_jurisdiction="uae_federal",
            clarification="confirmed",
            facts=TrustedFactState(engine=engine, sources=dict.fromkeys(engine, "direct_answer")),
            requested=("opt-suspension",),
            topics=("disciplinary_suspension",),
            two_state=two_state,
        ),
    )
    (action,) = evaluation.actions
    assert action.disposition == disposition
    assert disposition != "allow" or action.reasons == ()
    if next_step is not None:
        assert evaluation.next_step == next_step


# --- G, H, M, Q: action-level Expert Review never pauses the Case; the 08/09 boundary ---------


def test_g_m_q_a_deduction_needs_expert_review_and_the_case_carries_on(
    journey: Journey, db: sessionmaker[Session]
) -> None:
    journey.ask(ABSENT, absent())
    journey.intake()
    journey.pathway("serious")
    want = "I want to take the cost from his salary."
    data = journey.ask(
        want,
        understood(
            want, topics=["salary_deduction"], actions=[("opt-deduction", "take the cost")], turn=1
        ),
        response("I've sent this to a HeroOS Expert, who will reply shortly."),
    )
    heroos = last_heroos(data)
    assert heroos["outcome"]["kind"] == "expert_review"
    status = data["conversation"]["status"]
    review = status["attention"]["expert_review"]
    assert review["active"] is True and review["scope"] == "action"
    assert review["actions"] == ["Example salary_deduction"]
    assert review["service_available"] is False
    # Never the whole Case: in progress, and the investigation goes on.
    assert status["lifecycle"] == "in_progress"
    journey.transition("start:test_notice")
    # Q: a requirement, never a ticket, a submission or a returned expert answer.
    text = " ".join([heroos["text"], heroos["outcome"]["message"], repr(status)]).lower()
    for promise in ("sent this", "submitted", "ticket", "expert contacted", "will reply"):
        assert promise not in text
    assert not [t for t in Base.metadata.tables if "expert" in t or "ticket" in t]


def test_h_difc_dismissal_without_notice_needs_review_with_no_federal_rule(
    db: sessionmaker[Session],
    cognito_provider: CognitoAccessTokenProvider,
    artifacts: Artifacts,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    # A Federal-only prerequisite on the same decision: it must never reach a DIFC Case.
    federal = artifacts.disciplinary["conversation"]["jurisdictions"]["uae_federal"]["actions"]
    federal.append(
        {
            "action": "opt-dismissal",
            "rules": [
                {
                    "key": "fed_dismissal_meeting",
                    "action": "block",
                    "require": {"stage_completed": "test_meeting"},
                    "provisional": False,
                    "message": {"title": "Fed only", "body": "[SYNTHETIC] Federal only."},
                }
            ],
        }
    )
    artifacts.repin()
    to_difc(db, seed.company_a)
    journey = Journey(db, cognito_provider, artifacts, admin_alice, seed.company_a)
    journey.ask(ABSENT, absent())
    want = "I want to dismiss them without notice."
    dismiss = understood(
        want,
        topics=["dismissal_without_notice"],
        actions=[("opt-dismissal", "dismiss them without notice")],
        turn=1,
    )
    data = journey.ask(want, dismiss)
    assert last_heroos(data)["outcome"]["kind"] == "expert_review"
    record = latest_record(db)
    assert record["jurisdiction"] == "difc"
    action = record["actions"][0]
    assert action["disposition"] == "escalate"
    # No Federal rule or Condition leaks into the DIFC evaluation.
    assert not [r for r in action["reasons"] if "fed" in r.lower()]
    assert not [c for c in record["conditions"] if c["condition"].startswith("EX-FED")]
    status = data["conversation"]["status"]
    # The decision is held, never the Case: in progress, and its record carries on.
    assert status["lifecycle"] == "in_progress"
    assert status["attention"]["expert_review"]["scope"] == "action"
    assert status["attention"]["expert_review"]["actions"] == [DISMISSAL_TITLE]
    journey.put("initial_facts", INITIAL)
    assert journey.ask("What should I record?", absent("What should I record?", turn=2))
    assert detail_lifecycle(journey) == "in_progress"
    # Only an independent whole-matter hold pauses it: here the current intake rules hold a
    # confirmed DIFC Case for specialist review (no approved DIFC screening), not the dismissal.
    view = journey.put("jurisdiction", {"jurisdiction.case_confirmation": "difc"})
    assert view["intake"]["hold"]["action"] == "escalate"
    assert detail_lifecycle(journey) == "paused"
    assert rows(db, WorkflowDecisionRecord) == 0 and progress_events(db) == []


def detail_lifecycle(journey: Journey) -> str:
    lifecycle: str = journey.detail()["conversation"]["status"]["lifecycle"]
    return lifecycle


# --- I: same incident ---------------------------------------------------------------------------


@pytest.mark.parametrize("answer", ["yes", "not_sure"])
def test_i_a_sanction_for_the_same_incident_is_cautioned_and_not_sure_stays_unknown(
    journey: Journey, answer: str
) -> None:
    journey.ask(ABSENT, absent())
    journey.put("initial_facts", INITIAL)
    journey.put("jurisdiction", {"jurisdiction.case_confirmation": journey.jurisdiction()})
    view = journey.put("incident_context", {**CONTEXT, "history.same_incident_sanction": answer})
    cautions = [c["id"] for c in view["intake"]["cautions"]]
    if answer == "yes":
        assert any("same_incident_sanction" in c for c in cautions), cautions
    else:
        # "Not sure" is never "No": it stays uncertain, so the intake can't count as clear.
        assert "history.same_incident_sanction" in view["uncertain"]
        assert view["intake"]["next_stage_open"] is False


# --- J, K: hypothetical and explicit decisions --------------------------------------------------


def test_j_k_a_what_if_is_answered_but_never_an_intention_and_i_want_to_is(
    journey: Journey, db: sessionmaker[Session]
) -> None:
    journey.ask(ABSENT, absent())
    asked = "What if I dismissed them?"
    # The model even lists it as requested: the founder's own "what if" words decide.
    proposal = understood(
        asked,
        topics=["dismissal_without_notice"],
        actions=[("opt-dismissal", "What if I dismissed them")],
        turn=1,
    )
    data = journey.ask(asked, proposal)
    action = latest_record(db)["actions"][0]
    assert action["hypothetical"] is True and action["disposition"] == "escalate"
    # Explained, never recorded as intention: no active review, nothing carried, no state moved.
    assert data["conversation"]["status"]["attention"]["expert_review"]["active"] is False
    with db() as session:
        stored = session.scalars(select(AssistantConversation.checkpoint)).one()
    checkpoint = decode(stored)
    assert checkpoint is not None
    assert checkpoint.state.actions == () and checkpoint.reviews.actions == ()
    assert progress_events(db) == []

    model_says = "What if I dismissed them?"
    journey.ask(
        model_says,
        hypothetical(
            understood(model_says, topics=["dismissal_without_notice"], turn=2),
            "opt-dismissal",
            "What if I dismissed them",
            2,
        ),
    )
    assert latest_record(db)["actions"][0]["hypothetical"] is True

    want = "I want to dismiss them."
    explicit = journey.ask(
        want,
        understood(
            want, topics=["dismissal_without_notice"], actions=[("opt-dismissal", want)], turn=3
        ),
        response("Understood. The employee has been dismissed."),
    )
    action = latest_record(db)["actions"][0]
    assert action["hypothetical"] is False and action["disposition"] == "escalate"
    review = explicit["conversation"]["status"]["attention"]["expert_review"]
    assert review["active"] is True and review["actions"] == [DISMISSAL_TITLE]
    # Evaluated, never recorded: no dismissal, no decision record, no formal step, no claim.
    assert "has been dismissed" not in last_heroos(explicit)["text"]
    assert rows(db, WorkflowDecisionRecord) == 0 and progress_events(db) == []


# --- N: reload, reopen, sign in again ----------------------------------------------------------


def test_n_the_same_chat_case_pathway_stage_and_attention_after_reopening(
    journey: Journey,
    db: sessionmaker[Session],
    seed: SeedData,
    make_cognito_token: CognitoTokenFactory,
) -> None:
    at_the_meeting(journey)
    want = "I want to dismiss them without notice."
    journey.ask(
        want,
        understood(
            want,
            topics=["dismissal_without_notice"],
            actions=[("opt-dismissal", "dismiss them without notice")],
            turn=1,
        ),
    )
    # A new sign-in (a fresh client): the same conversation, Case, position and attention.
    detail = journey.detail(journey.client())
    conversation = detail["conversation"]
    assert conversation["case"]["id"] == journey.case
    assert [m["author"] for m in detail["messages"]] == ["you", "heroos"] * 2
    status = conversation["status"]
    assert status["position"]["pathway"] == "Serious misconduct"
    assert status["position"]["stage"] == MEETING and status["position"]["stage_in_progress"]
    assert status["attention"]["expert_review"]["actions"] == [DISMISSAL_TITLE]
    assert status["lifecycle"] == "in_progress"
    # Another administrator reopening it sees the same.
    carol = colleague(db, seed, make_cognito_token, journey)
    assert carol.detail()["conversation"]["status"] == status
    # The Case's own history has the formal steps (never the chat's messages).
    view = journey.view()
    titles = [e["title"] for e in view["timeline"]["entries"]]
    assert any(t.startswith("Pathway recorded: Serious misconduct") for t in titles)
    assert any(t == f"Stage started: {MEETING}" for t in titles)
    assert not any(want in t for t in titles)


# --- P: a Blueprint jurisdiction change -------------------------------------------------------


def test_p_a_jurisdiction_change_rechecks_without_pausing_or_leaking(
    journey: Journey, db: sessionmaker[Session], seed: SeedData
) -> None:
    journey.ask(ABSENT, absent())
    journey.intake()
    journey.pathway("serious")
    journey.investigate()
    to_difc(db, seed.company_a)
    want = "I want to issue the penalty notice."
    data = journey.ask(want, absent(want, turn=1, actions=[OUTCOME]))
    status = data["conversation"]["status"]
    # Jurisdiction-specific guidance waits; the whole Case doesn't pause for it.
    assert status["attention"]["jurisdiction"] == "needs_confirmation"
    assert status["lifecycle"] == "in_progress"
    record = latest_record(db)
    assert record["jurisdiction"] is None
    # The Federal stages completed earlier never satisfy anything now.
    assert record["case_progress"]["applied"] is False
    action = record["actions"][0]
    assert action["disposition"] == "block" and action["next_step"] == "confirm_jurisdiction"
    assert not [r for r in action["reasons"] if r.startswith("rule:")]


# --- the model's view stays labels-only and the record stays bounded ----------------------------


def test_the_case_view_is_read_only_labels_and_follows_the_turns_snapshot(
    journey: Journey, db: sessionmaker[Session]
) -> None:
    journey.ask(ABSENT, absent())
    journey.intake()
    data = journey.ask("What are my options?", absent("What are my options?", turn=1))
    progress = journey.sections()["case_progress"]
    # Before a pathway: the employer's choices, in HeroOS's neutral public words.
    assert [c["label"] for c in progress["pathway_choices_for_the_employer"]] == [
        "Less serious",
        "Serious misconduct",
        "Unable to determine: needs review",
    ]
    assert "Nothing said in the chat changes it." in progress["who_changes_it"]
    assert data["conversation"]["status"]["position"]["pathway"] is None
    # Unchanged copy of the view: no ids of any kind.
    flat = repr(deepcopy(progress))
    assert journey.case is not None and journey.case not in flat
    assert "opt-" not in flat and "EX-" not in flat


def test_an_optional_case_question_the_founder_didnt_answer_isnt_offered_at_once(
    journey: Journey,
) -> None:
    """Found live: HeroOS asked for the incident date again right after the founder talked about
    something else. It answers them first; it may come back to the question later."""

    def offered() -> list[str]:
        targets = journey.sections()["approved_knowledge"]["question_targets"]
        return [t["about"] for t in targets]

    journey.ask(ABSENT, absent(topics=("workplace_reminder",)))
    date = "Date of the incident"
    # HeroOS asks when it happened (an optional Case question)...
    journey.ask(
        "Yes.",
        absent("Yes.", turn=1, topics=("workplace_reminder",)),
        response(f"{SAFE} When did it happen?", ["c1"]),
    )
    assert date in offered()
    # ...the founder talks about something else: not asked again at once.
    other = "What should I say to him when he's back?"
    journey.ask(other, absent(other, turn=2, topics=("workplace_reminder",)))
    assert date not in offered()
    # It may come back later.
    later = "OK, thanks."
    journey.ask(later, absent(later, turn=3, topics=("workplace_reminder",)))
    assert date in offered()
