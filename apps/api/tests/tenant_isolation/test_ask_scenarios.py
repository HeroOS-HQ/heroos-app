"""M2-NEW-07's end-to-end scenarios (A to L) on PostgreSQL, as the runtime role.

The production application (``create_app`` with staging settings) over HTTP,
Cognito-shaped tokens, pooled runtime connections and RLS; the fictional
knowledge, rule bundle and execution profile; a scripted model only (no
provider is ever called). Each test is one scenario, driven the way the
browser's BFF drives the API: the founder's words, a turn key, the
conversation and the revision it last saw. Nothing else.

A  a supported attendance matter: stored, one real Case, a safe title,
   deterministic guidance; reopened from the Case; continued
B  unclear, then clarified: stored with no Case; then one Case, same conversation
C  DIFC dismissal: Expert Review for the dismissal only; the Case goes on; no ticket
D  the jurisdiction made uncertain: what depends on it waits; shared guidance goes on
E  a salary deduction: Expert Review, no amount, no ticket
F  outside HeroOS: stored, no Case
G  a correction: the old Case fact stays, the new one appends, the latest wins
H  a first turn retried after a lost response: one of everything, no second model call
I  a prerequisite recorded meanwhile: the fresh Guidance is stored, not the stale Block
J  the jurisdiction made uncertain meanwhile: the Expert Review is never loosened
K  another administrator: the same chat, attributed to the viewer, continued
L  a long conversation: every message kept and paged; the model sees a bounded window
"""

import json
import re
import uuid
from collections.abc import Callable, Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.assistant.gateway.service import MAX_CONVERSATION_TURNS, MAX_FOUNDER_TURNS, AiGateway
from app.assistant.limits import UsageLimits
from app.auth.dependencies import get_authentication_provider
from app.auth.models import AuthenticatedCompanyContext
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.cases.mutation import FormOrigin, apply_case_fact_changes, evaluate_case
from app.db.models import Membership
from app.db.session import get_db
from app.main import create_app
from app.repositories import workflows
from app.tenancy.scope import open_company_scope
from app.workflows.definition import CASE_JURISDICTION_KEY
from tests.conversations.test_reconciliation import policy_prerequisite
from tests.evaluation.test_golden import understood
from tests.fixtures.evaluation import Artifacts, codec
from tests.fixtures.gateway import ScriptedProvider, response, understanding
from tests.knowledge.conftest import (  # noqa: F401  (pytest fixtures)
    bundle_data,
    compiled,
    synthetic_mapping_path,
    synthetic_sources,
)
from tests.tenant_isolation.conftest import (
    Tenants,
    attribute_changes,
    count_rows,
)
from tests.tenant_isolation.test_api_routes import (  # noqa: F401  (pytest fixtures)
    ALICE,
    auth,
    provider,
    signing_key,
)
from tests.tenant_isolation.test_company_blueprint import answer, confirm
from tests.tenant_isolation.test_company_roles import set_role
from tests.tenant_isolation.test_gateway_routes import (  # noqa: F401  (pytest fixtures)
    http_engine,
    http_sessions,
    settings,
)

SAFE = "[SYNTHETIC] Thanks. HeroOS's approved approach starts with understanding what happened."
AUTHORITY = "[SYNTHETIC] Licensing authority"
CAROL = "carol-subject"
POLICY = "employee_aware_of_relevant_policy"
POLICY_QUESTION = "context.policy_awareness"
NARRATIVE_QUESTION = "incident.narrative"
TITLE = re.compile(r"^Disciplinary case · \d{1,2} [A-Z][a-z]{2}$")
TICKETS = re.compile(r"ticket|submitted|notified|awaiting|we.ll reply|sent to", re.IGNORECASE)


def late(message: str, turn: int = 0, **kwargs: Any) -> dict[str, Any]:
    return understood(
        message, pathway="less_serious", topics=["workplace_reminder"], turn=turn, **kwargs
    )


def serious(message: str, turn: int = 0, **kwargs: Any) -> dict[str, Any]:
    return understood(
        message, pathway="serious", topics=["serious_investigation"], turn=turn, **kwargs
    )


class During:
    """The real gateway; ``action`` runs after the model answered, before the turn is stored."""

    def __init__(self, inner: AiGateway, action: Callable[[], None]) -> None:
        self._inner, self._action = inner, action

    def respond(self, company: Any, turn: Any) -> Any:
        reply = self._inner.respond(company, turn)
        self._action()
        return reply

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class Admin:
    """One administrator's browser, through the production application."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        tokens: CognitoAccessTokenProvider,
        artifacts: Artifacts,
        headers: dict[str, str],
        company: uuid.UUID,
    ) -> None:
        self.app = create_app(settings())

        def _db() -> Generator[Session, None, None]:
            with sessions() as db:
                yield db

        self.app.dependency_overrides[get_authentication_provider] = lambda: tokens
        self.app.dependency_overrides[get_db] = _db
        self.client = TestClient(self.app)
        self.evaluation = artifacts.service()
        self.headers, self.company = headers, company
        self.conversation: str | None = None
        self.revision = 0
        self.chat: ScriptedProvider | None = None

    def say(
        self,
        message: str,
        proposal: Any,
        reply: Any = None,
        *,
        key: str | None = None,
        during: Callable[[], None] | None = None,
    ) -> Any:
        self.chat = ScriptedProvider(proposal, reply or response(SAFE, ["q1"]))
        gateway = AiGateway(
            enabled=True,
            provider=self.chat,
            approval="TEST-APPROVAL-1",
            allow_development_knowledge=True,
            limits=UsageLimits(account_limit=500, global_per_minute=500, global_per_day=5000),
            evaluation=self.evaluation,
            continuations=codec(),
        )
        self.app.state.ai_gateway = gateway if during is None else During(gateway, during)
        body: dict[str, Any] = {
            "message": message,
            "turn_key": key or str(uuid.uuid4()),
            "expected_revision": self.revision if self.conversation else 0,
        }
        if self.conversation:
            body["conversation_id"] = self.conversation
        answered = self.client.post(
            f"/companies/{self.company}/assistant/messages", headers=self.headers, json=body
        )
        assert answered.status_code == 200, answered.text
        data = answered.json()
        self.conversation = data["conversation"]["id"]
        self.revision = data["conversation"]["revision"]
        return data

    def get(self, path: str = "", **params: Any) -> Any:
        found = self.client.get(
            f"/companies/{self.company}/assistant/conversations{path}",
            headers=self.headers,
            params=params,
        )
        assert found.status_code == 200, found.text
        return found.json()

    def detail(self, **params: Any) -> Any:
        return self.get(f"/{self.conversation}", **params)

    def response_data(self) -> dict[str, Any]:
        assert self.chat is not None
        data: dict[str, Any] = self.chat.phase("response")[-1].data
        return data


@pytest.fixture
def artifacts(bundle_data: dict[str, Any]) -> Artifacts:  # noqa: F811
    return Artifacts(bundle_data)


def confirmed(
    runtime_engine: Engine, operator_engine: Engine, tenants: Tenants, jurisdiction: str
) -> None:
    """Company A: alice is an administrator; the jurisdiction is operator-confirmed."""
    set_role(operator_engine, tenants.a.company, tenants.a.membership, "company_admin")
    if jurisdiction == "difc":
        answer(runtime_engine, tenants.a, "difc")
        confirm(operator_engine, tenants.a, "difc", "difc")
    else:
        answer(runtime_engine, tenants.a, "other", AUTHORITY)
        confirm(operator_engine, tenants.a, "uae_federal", "other", AUTHORITY)


@pytest.fixture
def alice(
    http_sessions: sessionmaker[Session],  # noqa: F811
    provider: CognitoAccessTokenProvider,  # noqa: F811
    artifacts: Artifacts,
    auth: Any,  # noqa: F811
    runtime_engine: Engine,
    operator_engine: Engine,
    tenants: Tenants,
) -> Admin:
    confirmed(runtime_engine, operator_engine, tenants, "uae_federal")
    return Admin(http_sessions, provider, artifacts, auth(ALICE), tenants.a.company)


def form_save(
    runtime_engine: Engine,
    context: AuthenticatedCompanyContext,
    case_id: str,
    answers: dict[str, object],
    step: str,
) -> None:
    """Another write to the Case through the structured path (a form save), committed."""
    with Session(runtime_engine, autoflush=False) as session:
        scope = open_company_scope(session, context)
        item = workflows.get_workflow_case(scope, uuid.UUID(case_id), for_update=True)
        assert item is not None
        state = evaluate_case(scope, item, "disabled", None)
        applied = apply_case_fact_changes(
            scope, item, state, origin=FormOrigin(step), changes=answers,
            expected_revision=item.instance.revision, idempotency_key=uuid.uuid4(),
            user_id=context.user_id, policy="disabled", bundle=None,
        )  # fmt: skip
        assert applied is not None
        scope.commit()


def case_facts(admin_engine: Engine, case_id: str) -> list[tuple[str, Any]]:
    with admin_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT f.fact_key, f.value FROM case_facts f "
                "JOIN workflow_instances i ON i.id = f.instance_id "
                "JOIN workflow_submissions s ON s.id = f.submission_id "
                "WHERE i.case_id = :case ORDER BY s.revision, f.fact_key"
            ),
            {"case": case_id},
        )
        return [(key, value) for key, value in rows]


def latest_record(admin_engine: Engine) -> dict[str, Any]:
    with admin_engine.connect() as conn:
        record: dict[str, Any] = conn.scalar(
            text("SELECT record FROM assistant_turn_evaluations ORDER BY created_at DESC LIMIT 1")
        )
    return record


def cases(admin_engine: Engine, company: uuid.UUID) -> int:
    with admin_engine.connect() as conn:
        found: int = conn.scalar(
            text("SELECT count(*) FROM cases WHERE company_id = :c"), {"c": company}
        )
    return found


# --- A ------------------------------------------------------------------------------------------


def test_a_a_supported_attendance_matter_opens_one_case_and_reopens_from_it(
    alice: Admin, admin_engine: Engine, tenants: Tenants
) -> None:
    before = cases(admin_engine, tenants.a.company)
    said = "[SYNTHETIC] One employee hasn't come to work for three days and isn't answering."
    first = alice.say(said, late(said))
    conversation = first["conversation"]
    assert conversation["case"] is not None and cases(admin_engine, tenants.a.company) == before + 1
    # A safe server-chosen title: never a name, nothing the founder typed.
    assert (
        TITLE.match(conversation["title"])
        and conversation["case"]["title"] == conversation["title"]
    )
    assert first["messages"][1]["outcome"]["kind"] == "guidance"
    assert conversation["status"]["lifecycle"] == "in_progress"
    # Away and back: the Case leads to its conversation, and the same chat is there.
    case_id = conversation["case"]["id"]
    (found,) = alice.get(case_id=case_id)["items"]
    assert found["id"] == conversation["id"]
    reopened = alice.detail()
    assert [m["text"] for m in reopened["messages"]] == [m["text"] for m in first["messages"]]
    assert [m["author"] for m in reopened["messages"]] == ["you", "heroos"]
    again = alice.say("[SYNTHETIC] He came back today.", late("[SYNTHETIC] He came back today.", 1))
    assert again["conversation"]["case"]["id"] == case_id
    assert len(alice.detail()["messages"]) == 4
    assert cases(admin_engine, tenants.a.company) == before + 1


# --- B ------------------------------------------------------------------------------------------


def test_b_unclear_then_clarified_attaches_one_case_to_the_same_conversation(
    alice: Admin, admin_engine: Engine, tenants: Tenants
) -> None:
    before = cases(admin_engine, tenants.a.company)
    first = alice.say(
        "[SYNTHETIC] I need help with an employee.", understanding(intent="unclear", workflow=None)
    )
    # Chat-first Case: the first message starts the conversation's Case, workflow not known yet.
    case = first["conversation"]["case"]
    assert case is not None and case["title"] == "New case"
    assert len(alice.detail()["messages"]) == 2
    said = "[SYNTHETIC] He has been late to work several times this month."
    second = alice.say(said, late(said, 1))
    assert second["conversation"]["id"] == first["conversation"]["id"]
    # The workflow attaches to that same Case: one Case for the conversation.
    assert second["conversation"]["case"]["id"] == case["id"]
    assert cases(admin_engine, tenants.a.company) == before + 1


# --- C ------------------------------------------------------------------------------------------


def test_c_a_difc_dismissal_needs_expert_review_while_the_investigation_goes_on(
    http_sessions: sessionmaker[Session],  # noqa: F811
    provider: CognitoAccessTokenProvider,  # noqa: F811
    artifacts: Artifacts,
    auth: Any,  # noqa: F811
    runtime_engine: Engine,
    operator_engine: Engine,
    tenants: Tenants,
) -> None:
    confirmed(runtime_engine, operator_engine, tenants, "difc")
    admin = Admin(http_sessions, provider, artifacts, auth(ALICE), tenants.a.company)
    ask = "[SYNTHETIC] We suspect serious misconduct by one of our team. How should we investigate?"
    investigating = admin.say(ask, serious(ask))
    assert investigating["messages"][1]["outcome"]["kind"] == "guidance"
    fire = "[SYNTHETIC] Can I dismiss them immediately without notice?"
    dismissing = admin.say(
        fire, serious(fire, 1, actions=[("opt-dismissal", "dismiss them immediately")])
    )
    heroos = dismissing["messages"][1]
    assert heroos["outcome"]["kind"] == "expert_review"
    status = dismissing["conversation"]["status"]
    review = status["attention"]["expert_review"]
    assert (review["active"], review["scope"], review["service_available"]) == (
        True,
        "action",
        False,
    )
    # The dismissal's review never pauses the Case: the investigation goes on.
    assert status["lifecycle"] == "in_progress"
    assert not TICKETS.search(json.dumps(heroos))
    more = "[SYNTHETIC] What should the investigation cover?"
    going_on = admin.say(more, serious(more, 2))
    assert going_on["messages"][1]["outcome"]["kind"] == "guidance"
    assert going_on["conversation"]["status"]["lifecycle"] == "in_progress"
    assert going_on["conversation"]["status"]["attention"]["expert_review"]["active"] is True


# --- D ------------------------------------------------------------------------------------------


def test_d_an_uncertain_jurisdiction_holds_only_what_depends_on_it(
    alice: Admin, runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    said = "[SYNTHETIC] An employee keeps arriving late."
    case_id = alice.say(said, late(said))["conversation"]["case"]["id"]
    form_save(
        runtime_engine,
        tenants.a.context,
        case_id,
        {CASE_JURISDICTION_KEY: "not_sure"},
        "jurisdiction",
    )
    ask = "[SYNTHETIC] How should we look into what happened?"
    shared = alice.say(ask, serious(ask, 1))
    record = latest_record(admin_engine)
    assert (record["jurisdiction_state"], record["jurisdiction"]) == ("case_not_sure", None)
    assert shared["messages"][1]["outcome"]["kind"] == "guidance"
    data = alice.response_data()
    assert data["approved_knowledge"]["approved_guidance"]
    assert data["jurisdiction_note"].startswith("Not confirmed for this employee")
    status = shared["conversation"]["status"]
    assert status["lifecycle"] == "in_progress"
    assert status["attention"]["jurisdiction"] == "needs_confirmation"
    suspend = "[SYNTHETIC] Can I suspend him without pay?"
    held = alice.say(
        suspend,
        understood(
            suspend,
            topics=["disciplinary_suspension"],
            actions=[("opt-suspension", "suspend him without pay")],
            turn=2,
        ),
    )
    (step,) = latest_record(admin_engine)["actions"]
    assert step["disposition"] == "block" and "jurisdiction:case_not_sure" in step["reasons"]
    assert held["messages"][1]["outcome"]["kind"] == "block"
    knowledge = json.dumps(alice.response_data()["approved_knowledge"])
    for jurisdiction_specific in ("DIFC Example Suspension", "In DIFC", "900 days"):
        assert jurisdiction_specific not in knowledge


# --- E, F ---------------------------------------------------------------------------------------


def test_e_a_salary_deduction_needs_expert_review_and_no_amount(alice: Admin) -> None:
    said = "[SYNTHETIC] He damaged a laptop. Take the repair cost from his salary."
    result = alice.say(
        said,
        understood(
            said,
            topics=["salary_deduction"],
            actions=[("opt-deduction", "Take the repair cost from his salary")],
        ),
        response("[SYNTHETIC] You could deduct up to AED 500 a month from his salary."),
    )
    heroos = result["messages"][1]
    assert heroos["outcome"]["kind"] == "expert_review"
    assert "500" not in heroos["text"]
    assert not TICKETS.search(json.dumps(heroos))
    assert (
        result["conversation"]["status"]["attention"]["expert_review"]["service_available"] is False
    )


def test_f_outside_heroos_is_stored_in_its_case_without_a_workflow(
    alice: Admin, admin_engine: Engine, tenants: Tenants
) -> None:
    before = cases(admin_engine, tenants.a.company)
    result = alice.say(
        "[SYNTHETIC] Help me debug JavaScript.", understanding(intent="unsupported", workflow=None)
    )
    # Chat-first Case: the conversation has its Case, and no workflow attaches to it.
    case = result["conversation"]["case"]
    assert case is not None and case["title"] == "New case"
    assert len(alice.detail()["messages"]) == 2
    assert cases(admin_engine, tenants.a.company) == before + 1
    with admin_engine.connect() as conn:
        assert not conn.scalar(
            text("SELECT count(*) FROM workflow_instances WHERE case_id = :case"),
            {"case": case["id"]},
        )


# --- G ------------------------------------------------------------------------------------------


def test_g_a_correction_appends_and_the_latest_wins(
    alice: Admin, runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    said = "[SYNTHETIC] My employee has been late three times this month."
    case_id = alice.say(said, late(said))["conversation"]["case"]["id"]
    alice.say("No.", late("No.", 1))  # the direct answer to HeroOS's question: a Case fact
    # The founder's first message is the Case's narrative (chat-first Case).
    narrative = (NARRATIVE_QUESTION, said)
    assert case_facts(admin_engine, case_id) == [narrative, (POLICY_QUESTION, "no")]
    # The correction, recorded on the Case: appended, the old fact kept, the latest wins.
    form_save(
        runtime_engine, tenants.a.context, case_id, {POLICY_QUESTION: "yes"}, "incident_context"
    )
    assert case_facts(admin_engine, case_id) == [
        narrative,
        (POLICY_QUESTION, "no"),
        (POLICY_QUESTION, "yes"),
    ]
    alice.say("[SYNTHETIC] Thanks.", late("[SYNTHETIC] Thanks.", 2))
    assert latest_record(admin_engine)["facts"]["engine_trusted"][POLICY] == "yes"
    assert len(alice.detail()["messages"]) == 6  # the conversation is kept whole


# --- H ------------------------------------------------------------------------------------------


def test_h_a_retried_first_turn_is_stored_once(
    alice: Admin, admin_sessions: sessionmaker[Session]
) -> None:
    said = "[SYNTHETIC] An employee keeps arriving late."
    key = str(uuid.uuid4())
    first = alice.say(said, late(said), key=key)
    chat = alice.chat
    assert chat is not None and len(chat.calls) == 2
    # The response was lost; the browser sends the same request again.
    alice.conversation, alice.revision = None, 0
    again = alice.say(said, late(said), key=key)
    assert again["replayed"] is True and again["messages"] == first["messages"]
    assert alice.chat is not None and alice.chat.calls == []  # no second model request
    with admin_sessions() as db:
        counts = {
            table: count_rows(db, table)
            for table in (
                "assistant_conversations", "assistant_turns", "assistant_messages",
                "assistant_turn_evaluations",
            )
        }  # fmt: skip
    assert counts == {
        "assistant_conversations": 1,
        "assistant_turns": 1,
        "assistant_messages": 2,
        "assistant_turn_evaluations": 1,
    }


# --- I, J ---------------------------------------------------------------------------------------


def test_i_a_prerequisite_recorded_meanwhile_stores_the_fresh_guidance(
    http_sessions: sessionmaker[Session],  # noqa: F811
    provider: CognitoAccessTokenProvider,  # noqa: F811
    artifacts: Artifacts,
    auth: Any,  # noqa: F811
    runtime_engine: Engine,
    operator_engine: Engine,
    admin_engine: Engine,
    tenants: Tenants,
) -> None:
    confirmed(runtime_engine, operator_engine, tenants, "uae_federal")
    policy_prerequisite(artifacts)
    admin = Admin(http_sessions, provider, artifacts, auth(ALICE), tenants.a.company)
    said = "[SYNTHETIC] An employee keeps arriving late."
    case_id = admin.say(said, late(said))["conversation"]["case"]["id"]
    form_save(
        runtime_engine, tenants.a.context, case_id, {POLICY_QUESTION: "no"}, "incident_context"
    )
    warn = "[SYNTHETIC] Can I give him a written warning?"
    proposal = late(warn, 1, actions=[("opt-warning", "a written warning")])
    assert admin.say(warn, proposal)["messages"][1]["outcome"]["kind"] == "block"
    again = "[SYNTHETIC] And now, can I give him a written warning?"
    result = admin.say(
        again,
        late(again, 2, actions=[("opt-warning", "a written warning")]),
        during=lambda: form_save(
            runtime_engine, tenants.a.context, case_id, {POLICY_QUESTION: "yes"}, "incident_context"
        ),
    )
    heroos = result["messages"][1]
    assert heroos["outcome"]["kind"] == "guidance"
    assert heroos["text"].startswith("This case changed while I was answering")
    assert SAFE not in heroos["text"]
    record = latest_record(admin_engine)
    assert record["presentation"] == "guidance"
    assert [a["disposition"] for a in record["actions"]] == ["allow"]


def test_j_an_uncertain_jurisdiction_meanwhile_never_loosens_an_expert_review(
    alice: Admin, runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    said = "[SYNTHETIC] An employee keeps arriving late."
    case_id = alice.say(said, late(said))["conversation"]["case"]["id"]
    fire = "[SYNTHETIC] Can I dismiss him without notice?"
    result = alice.say(
        fire,
        understood(
            fire,
            pathway="serious",
            topics=["dismissal_without_notice"],
            actions=[("opt-dismissal", "dismiss him without notice")],
            turn=1,
        ),
        during=lambda: form_save(
            runtime_engine,
            tenants.a.context,
            case_id,
            {CASE_JURISDICTION_KEY: "not_sure"},
            "jurisdiction",
        ),  # fmt: skip
    )
    assert result["messages"][1]["outcome"]["kind"] == "expert_review"
    assert latest_record(admin_engine)["presentation"] == "expert_review"
    assert result["conversation"]["status"]["attention"]["expert_review"]["active"] is True


# --- K ------------------------------------------------------------------------------------------


def test_k_another_administrator_reads_and_continues_the_same_chat(
    alice: Admin,
    http_sessions: sessionmaker[Session],  # noqa: F811
    provider: CognitoAccessTokenProvider,  # noqa: F811
    artifacts: Artifacts,
    auth: Any,  # noqa: F811
    admin_sessions: sessionmaker[Session],
    tenants: Tenants,
) -> None:
    with admin_sessions() as db:
        attribute_changes(db)
        db.add(
            Membership(company_id=tenants.a.company, user_id=tenants.carol, role="company_admin")
        )
        db.commit()
    said = "[SYNTHETIC] An employee keeps arriving late."
    case_id = alice.say(said, late(said))["conversation"]["case"]["id"]
    carol = Admin(http_sessions, provider, artifacts, auth(CAROL), tenants.a.company)
    (found,) = carol.get(case_id=case_id)["items"]
    carol.conversation = found["id"]
    seen = carol.detail()
    carol.revision = seen["conversation"]["revision"]
    assert [m["author"] for m in seen["messages"]] == ["another_administrator", "heroos"]
    reply = "[SYNTHETIC] I spoke to him this morning."
    continued = carol.say(reply, late(reply, 1))
    assert continued["conversation"]["id"] == alice.conversation
    assert [m["author"] for m in alice.detail()["messages"]] == [
        "you", "heroos", "another_administrator", "heroos",
    ]  # fmt: skip
    # No identity of either administrator reaches the other.
    assert "@" not in json.dumps(seen) and "subject" not in json.dumps(seen)


# --- L ------------------------------------------------------------------------------------------


def test_l_a_long_conversation_keeps_every_message_and_bounds_the_models_view(
    alice: Admin,
) -> None:
    turns = 14
    for i in range(turns):
        said = f"[SYNTHETIC] Update {i}: he was late again."
        alice.say(said, late(said))
    founder_messages = alice.chat.phase("understanding")[-1].data["founder_messages"]  # type: ignore[union-attr]
    conversation = alice.response_data()["conversation"]
    # Bounded: the model sees a recent window (the current message and the latest earlier
    # ones), never the whole history.
    assert len(founder_messages) == MAX_FOUNDER_TURNS + 1
    assert founder_messages[-1]["text"] == f"[SYNTHETIC] Update {turns - 1}: he was late again."
    assert len(conversation) <= MAX_CONVERSATION_TURNS
    # Every message is kept, and read a page at a time, oldest first.
    page = alice.detail(limit=10)
    texts = [m["text"] for m in page["messages"]]
    before = page["next_before"]
    while before is not None:
        older = alice.get(f"/{alice.conversation}/messages", before=before, limit=10)
        texts = [m["text"] for m in older["messages"]] + texts
        before = older["next_before"]
    assert len(texts) == 2 * turns
    assert texts[0] == "[SYNTHETIC] Update 0: he was late again."
    assert texts[-2] == f"[SYNTHETIC] Update {turns - 1}: he was late again."
