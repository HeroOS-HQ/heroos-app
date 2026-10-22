"""M2-NEW-07 Part 2: the persistent Ask HeroOS contract through the real application.

SQLite stand-ins (RLS, grants and real races: tests/tenant_isolation), Cognito
tokens verified by the production provider, the real gateway on the fictional
execution content, and a scripted provider.

- a first turn retried after a lost response replays (no model request); the same key
  with another message is 409; a stale revision is 409 before any model request;
- another administrator reads and continues the Company's conversation, and authors are
  relative to the viewer; another Company sees nothing; a member sees nothing;
- the status: lifecycle, attention (needs information, Expert Review), checks and the
  latest outcome, each from its own source; an action's review never pauses the Case and
  only an explicit withdrawal (or a fresh evaluation) ends it; a matter-level review needs
  no Case; a technical outage never touches the lifecycle; the service's availability is a
  current capability;
- a Blueprint jurisdiction change never carries one jurisdiction's state into another;
- conversations and messages page by stable cursors; the model sees a bounded window of a
  long conversation that stays whole in the product.
"""

import json
import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.assistant.gateway.service import AiGateway
from app.assistant.limits import UsageLimits
from app.assistant.provider import AssistantError
from app.auth.dependencies import get_authentication_provider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.conversations import status as status_module
from app.conversations.checkpoint import decode
from app.db.models import (
    AssistantConversation,
    AssistantTurnEvaluation,
    CompanyBlueprint,
    Membership,
    WorkflowInstance,
)
from app.db.session import get_db
from app.main import create_app
from tests.auth.conftest import CognitoTokenFactory, SeedData, bearer
from tests.auth.test_company_admin_api import make_admin
from tests.auth.test_company_api import staging_settings
from tests.auth.test_workflow_api import admin_alice, alice, bob  # noqa: F401  (pytest fixtures)
from tests.conversations.conftest import SAFE, Founder, counts
from tests.evaluation.test_golden import understood
from tests.fixtures.evaluation import Artifacts, codec
from tests.fixtures.gateway import ScriptedProvider, response, understanding

LATE = "My employee has been late three times this month. What should I do?"
FIRE = "I think she took money from the till. Can I fire her today?"
DISMISSAL_TITLE = "Example dismissal_without_notice"
UNSET: Any = object()


def late(message: str = LATE, turn: int = 0, **kwargs: Any) -> dict[str, Any]:
    return understood(
        message, pathway="less_serious", topics=["workplace_reminder"], turn=turn, **kwargs
    )


def fire(message: str = FIRE, turn: int = 0) -> dict[str, Any]:
    return understood(
        message,
        topics=["dismissal_without_notice"],
        actions=[("opt-dismissal", "fire her today")],
        turn=turn,
    )


class Http:
    """One administrator's browser: only its words, a turn key, the conversation, its revision."""

    def __init__(
        self,
        db: sessionmaker[Session],
        provider: CognitoAccessTokenProvider,
        artifacts: Artifacts,
        headers: dict[str, str],
        company: uuid.UUID,
    ) -> None:
        self.db, self.auth, self.artifacts = db, provider, artifacts
        self.evaluation = artifacts.service()
        self.headers, self.company = headers, company
        self.conversation: str | None = None
        self.revision = 0
        self.chat: ScriptedProvider | None = None
        self.last: Any = None

    def client(self, chat: ScriptedProvider | None = None, **gateway: Any) -> TestClient:
        app = create_app(staging_settings())
        app.state.ai_gateway = AiGateway(
            enabled=True,
            provider=chat or ScriptedProvider(understanding()),
            approval="TEST-APPROVAL-1",
            allow_development_knowledge=True,
            limits=UsageLimits(account_limit=500, global_per_minute=500, global_per_day=5000),
            evaluation=gateway.get("evaluation", self.evaluation),
            continuations=codec(),
        )

        def _db() -> Generator[Session, None, None]:
            with self.db() as session:
                yield session

        app.dependency_overrides[get_authentication_provider] = lambda: self.auth
        app.dependency_overrides[get_db] = _db
        return TestClient(app)

    def post(
        self,
        message: str,
        proposal: Any,
        reply: Any = None,
        *,
        key: str | None = None,
        conversation: Any = UNSET,
        revision: int | None = None,
    ) -> Any:
        self.chat = ScriptedProvider(proposal, reply or response(SAFE, ["q1"]))
        target = self.conversation if conversation is UNSET else conversation
        body: dict[str, Any] = {
            "message": message,
            "turn_key": key or str(uuid.uuid4()),
            "expected_revision": (self.revision if target else 0) if revision is None else revision,
        }
        if target is not None:
            body["conversation_id"] = target
        answered = self.client(self.chat).post(
            f"/companies/{self.company}/assistant/messages", headers=self.headers, json=body
        )
        self.last = answered
        if answered.status_code == 200:
            data = answered.json()
            self.conversation = data["conversation"]["id"]
            self.revision = data["conversation"]["revision"]
        return answered

    def get(self, path: str = "", **params: Any) -> Any:
        base = f"/companies/{self.company}/assistant/conversations"
        return self.client().get(base + path, headers=self.headers, params=params)

    def detail(self, **params: Any) -> Any:
        found = self.get(f"/{self.conversation}", **params)
        assert found.status_code == 200, found.text
        return found.json()

    def status(self) -> dict[str, Any]:
        status: dict[str, Any] = self.detail()["conversation"]["status"]
        return status


@pytest.fixture
def browser(
    db: sessionmaker[Session],
    cognito_provider: CognitoAccessTokenProvider,
    artifacts: Artifacts,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> Http:
    return Http(db, cognito_provider, artifacts, admin_alice, seed.company_a)


def colleague(
    db: sessionmaker[Session],
    seed: SeedData,
    make_cognito_token: CognitoTokenFactory,
    browser: Http,
) -> Http:
    """carol: another active administrator of Company A (her own sign-in)."""
    with db() as session:
        session.add(Membership(company_id=seed.company_a, user_id=seed.carol))
        session.commit()
    make_admin(db, seed.company_a, seed.carol)
    other = Http(
        db,
        browser.auth,
        browser.artifacts,
        bearer(make_cognito_token("carol-subject")),
        seed.company_a,
    )
    other.conversation, other.revision = browser.conversation, browser.revision
    return other


# --- replay and revisions ------------------------------------------------------------------------


def test_a_first_turn_retried_after_a_lost_response_replays(
    browser: Http, db: sessionmaker[Session]
) -> None:
    key = str(uuid.uuid4())
    first = browser.post(LATE, late(), key=key, conversation=None)
    assert first.status_code == 200
    stored = counts(db)
    # The response never arrived: the browser sends exactly the same request again.
    again = browser.post(LATE, late(), key=key, conversation=None, revision=0)
    assert again.status_code == 200
    assert browser.chat is not None and browser.chat.calls == []  # no model request
    assert again.json()["replayed"] is True
    assert again.json()["messages"] == first.json()["messages"]
    assert again.json()["conversation"]["id"] == first.json()["conversation"]["id"]
    assert counts(db) == stored
    assert (stored["assistant_conversations"], stored["assistant_turns"]) == (1, 1)
    assert (stored["assistant_messages"], stored["assistant_turn_evaluations"]) == (2, 1)
    assert stored["cases"] == 1
    # The same key with another message is another request.
    changed = browser.post("Something else.", late(), key=key, conversation=None, revision=0)
    assert changed.status_code == 409 and changed.json() == {"detail": "Conflict"}
    assert counts(db) == stored


def test_a_stale_revision_is_refused_before_any_model_request(
    browser: Http, db: sessionmaker[Session]
) -> None:
    browser.post(LATE, late())
    browser.post("Yes.", late("Yes.", 1))
    stored = counts(db)
    stale = browser.post("He was late again.", late("He was late again.", 2), revision=1)
    assert stale.status_code == 409
    assert browser.chat is not None and browser.chat.calls == []
    assert counts(db) == stored
    unknown = browser.post("Hello.", late("Hello."), conversation=str(uuid.uuid4()), revision=0)
    assert unknown.status_code == 404


# --- the Company's conversation ---------------------------------------------------------------


def test_another_administrator_reads_and_continues_it(
    browser: Http,
    db: sessionmaker[Session],
    seed: SeedData,
    make_cognito_token: CognitoTokenFactory,
) -> None:
    browser.post(LATE, late())
    carol = colleague(db, seed, make_cognito_token, browser)
    seen = carol.detail()
    # alice's message is never carol's "you".
    assert [m["author"] for m in seen["messages"]] == ["another_administrator", "heroos"]
    answered = carol.post("Yes.", late("Yes.", 1))
    assert answered.status_code == 200
    assert answered.json()["messages"][0]["author"] == "you"
    browser.revision = carol.revision
    mine = browser.detail()
    assert [m["author"] for m in mine["messages"]] == [
        "you",
        "heroos",
        "another_administrator",
        "heroos",
    ]
    for message in mine["messages"]:
        assert set(message) == {
            "sequence", "author", "text", "safe_next_step", "conversation_state", "outcome",
            "created_at",
        }  # fmt: skip
    assert str(seed.carol) not in str(mine) and str(seed.alice) not in str(mine)


def test_another_company_and_a_member_see_nothing(
    browser: Http,
    db: sessionmaker[Session],
    seed: SeedData,
    alice: dict[str, str],  # noqa: F811
    bob: dict[str, str],  # noqa: F811
) -> None:
    browser.post(LATE, late())
    conversation = browser.conversation
    make_admin(db, seed.company_b, seed.bob)
    intruder = Http(db, browser.auth, browser.artifacts, bob, seed.company_b)
    # Company B's own routes: A's conversation is indistinguishable from none.
    assert intruder.get(f"/{conversation}").status_code == 404
    assert intruder.get(f"/{conversation}/messages").status_code == 404
    assert intruder.get().json() == {"items": [], "next_before": None}
    case_id = browser.detail()["conversation"]["case"]["id"]
    assert intruder.get(case_id=case_id).json() == {"items": [], "next_before": None}
    answered = intruder.post("Hi.", late("Hi."), conversation=conversation, revision=1)
    assert answered.status_code == 404
    # Company A's routes: bob isn't a member.
    across = Http(db, browser.auth, browser.artifacts, bob, seed.company_a)
    assert across.get(f"/{conversation}").status_code == 403
    # A member of A who isn't an administrator: nothing either.
    with db() as session:
        session.execute(
            update(Membership)
            .where(Membership.company_id == seed.company_a, Membership.user_id == seed.alice)
            .values(role="member")
        )
        session.commit()
    member = Http(db, browser.auth, browser.artifacts, alice, seed.company_a)
    assert member.get().status_code == 403
    assert member.get(f"/{conversation}").status_code == 403


def test_a_cases_conversation_is_found_by_its_case(browser: Http) -> None:
    """The Case page's link to the chat it started from (a Case has at most one)."""
    first = browser.post(LATE, late()).json()["conversation"]
    case_id = first["case"]["id"]
    browser.post(LATE, late(), conversation=None)  # another conversation, its own Case
    found = browser.get(case_id=case_id).json()
    assert [item["id"] for item in found["items"]] == [first["id"]]
    assert found["items"][0]["case"]["id"] == case_id and found["next_before"] is None
    assert browser.get(case_id=str(uuid.uuid4())).json() == {"items": [], "next_before": None}
    cursor = f"1.{'a' * 32}"
    assert browser.get(case_id=case_id, before=cursor).status_code == 422
    assert browser.get(case_id="not-a-case").status_code == 422


def test_no_internal_evaluation_reaches_a_read(browser: Http) -> None:
    browser.post(FIRE, fire())
    text = browser.get(f"/{browser.conversation}").text + browser.get().text
    for private in (
        "heroos.conversation-evaluation", "heroos.assistant-checkpoint", "engine_trusted",
        "snapshot", "profile_digest", "opt-dismissal", "EX-", "rule:", "withdrawn",
        "record", "turn_key",
    ):  # fmt: skip
        assert private not in text, private


# --- the status, one dimension at a time ----------------------------------------------------------


def test_an_actions_review_never_pauses_the_case(browser: Http) -> None:
    body = browser.post(FIRE, fire()).json()
    status = body["conversation"]["status"]
    assert status["lifecycle"] == "in_progress"
    assert status["attention"]["expert_review"] == {
        "active": True,
        "scope": "action",
        "actions": [DISMISSAL_TITLE],
        "service_available": False,
    }
    assert (status["checks"], status["latest_outcome"]) == ("ready", "expert_review")
    # The investigation goes on; a turn about something else changes no review.
    asked = "How should the investigation be run?"
    answered = browser.post(asked, understood(asked, topics=["serious_investigation"], turn=1))
    status = answered.json()["conversation"]["status"]
    assert status["lifecycle"] == "in_progress"
    assert status["latest_outcome"] != "expert_review"
    assert status["attention"]["expert_review"]["actions"] == [DISMISSAL_TITLE]


def withdrawing(message: str, excerpt: str, turn: int) -> dict[str, Any]:
    data = understood(message, topics=["serious_investigation"], turn=turn)
    data["withdrawn_actions"] = [
        {"action": "opt-dismissal", "source_turn": turn, "support_excerpt": excerpt}
    ]
    return data


def test_only_an_explicit_withdrawal_ends_an_actions_review(
    browser: Http, db: sessionmaker[Session]
) -> None:
    browser.post(FIRE, fire())
    # The model claims a withdrawal the founder's words don't make: nothing changes.
    vague = "Let's look at the investigation."
    browser.post(vague, withdrawing(vague, "look at the investigation", 1))
    assert browser.status()["attention"]["expert_review"]["active"] is True
    said = "We're no longer considering dismissal."
    browser.post(said, withdrawing(said, "no longer considering dismissal", 2))
    review = browser.status()["attention"]["expert_review"]
    assert review == {"active": False, "scope": None, "actions": [], "service_available": False}
    # History stays: the first turn's record still says the dismissal needed review.
    with db() as session:
        records = [
            (row.record, row.withdrawn_actions)
            for row in session.scalars(select(AssistantTurnEvaluation)).all()
        ]
    assert any(
        a["action"] == "opt-dismissal" and a["review"] for r, _ in records for a in r["actions"]
    )
    assert ["opt-dismissal"] in [w for _, w in records]


def test_a_matter_level_review_needs_no_case(browser: Http) -> None:
    said = "Help me plan staffing strategy for 2027."
    body = browser.post(said, understanding(intent="other_hr")).json()
    conversation = body["conversation"]
    assert conversation["case"] is None
    status = conversation["status"]
    assert status["lifecycle"] is None and status["workflow"] is None
    assert status["checks"] == "not_applicable"
    assert status["attention"]["expert_review"] == {
        "active": True,
        "scope": "matter",
        "actions": [],
        "service_available": False,
    }
    assert status["latest_outcome"] == "expert_review"


def test_needing_information_is_attention_not_a_lifecycle(browser: Http) -> None:
    said = "I want to suspend him without pay for 20 days as punishment."
    data = understood(
        said, topics=["disciplinary_suspension"], actions=[("opt-suspension", "suspend him")]
    )
    status = browser.post(said, data).json()["conversation"]["status"]
    assert status["attention"]["needs_information"] is True
    assert (status["lifecycle"], status["latest_outcome"]) == ("in_progress", "block")
    assert status["attention"]["expert_review"]["active"] is False


def test_a_technical_outage_never_touches_the_lifecycle(
    browser: Http, artifacts: Artifacts
) -> None:
    browser.post(LATE, late())
    healthy = browser.evaluation
    pinned = artifacts.profile["workflows"][0]["knowledge_runtime_digest"]
    artifacts.profile["workflows"][0]["knowledge_runtime_digest"] = "f" * 64
    browser.evaluation = artifacts.service()  # the profile no longer matches the knowledge
    artifacts.profile["workflows"][0]["knowledge_runtime_digest"] = pinned
    status = browser.post("Yes.", late("Yes.", 1)).json()["conversation"]["status"]
    assert (status["lifecycle"], status["checks"], status["latest_outcome"]) == (
        "in_progress",
        "unavailable",
        "unavailable",
    )
    # The runtime recovers: the checks are ready again with no new turn and no Case event.
    browser.evaluation = healthy
    status = browser.status()
    assert (status["lifecycle"], status["checks"], status["latest_outcome"]) == (
        "in_progress",
        "ready",
        "unavailable",
    )


def test_the_review_service_is_a_current_capability(
    browser: Http, monkeypatch: pytest.MonkeyPatch, db: sessionmaker[Session]
) -> None:
    browser.post(FIRE, fire())
    monkeypatch.setattr(status_module, "expert_review_service_available", lambda: True)
    assert browser.status()["attention"]["expert_review"]["service_available"] is True
    # The historical record keeps what was true then.
    with db() as session:
        (record,) = session.scalars(select(AssistantTurnEvaluation.record)).all()
    assert record["reviews"][0]["service_available"] is False


# --- the Blueprint's jurisdiction changes ---------------------------------------------------------


def move_to_difc(db: sessionmaker[Session], company: uuid.UUID) -> None:
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


def records(db: sessionmaker[Session]) -> list[dict[str, Any]]:
    with db() as session:
        return [
            row.record
            for row in session.scalars(
                select(AssistantTurnEvaluation).order_by(AssistantTurnEvaluation.created_at)
            ).all()
        ]


def test_a_new_jurisdiction_never_inherits_the_old_ones_state(
    browser: Http, db: sessionmaker[Session], seed: SeedData
) -> None:
    browser.post(LATE, late())
    before = browser.detail()["messages"]
    move_to_difc(db, seed.company_a)
    browser.post("He was late again.", late("He was late again.", 1))
    first, second = records(db)
    assert (first["jurisdiction"], second["jurisdiction"]) == ("uae_federal", "difc")
    # Old chat and old evaluation unchanged; the trusted state was rebuilt and re-confirmed.
    assert browser.detail()["messages"][:2] == before
    with db() as session:
        (conversation,) = session.scalars(select(AssistantConversation)).all()
    checkpoint = decode(conversation.checkpoint)
    assert checkpoint is not None and checkpoint.company_jurisdiction == "difc"
    assert checkpoint.state.reconfirm is True


def test_a_case_confirmed_under_another_jurisdiction_holds_only_what_depends_on_it(
    browser: Http, db: sessionmaker[Session], seed: SeedData
) -> None:
    case_id = browser.post(LATE, late()).json()["conversation"]["case"]["id"]
    with db() as session:
        revision = session.scalar(select(WorkflowInstance.revision))
    saved = browser.client().put(
        f"/companies/{seed.company_a}/cases/{case_id}/workflow/steps/jurisdiction/answers",
        headers=browser.headers,
        json={
            "expected_revision": revision,
            "submission_key": str(uuid.uuid4()),
            "answers": {"jurisdiction.case_confirmation": "uae_federal"},
        },
    )
    assert saved.status_code == 200, saved.text
    move_to_difc(db, seed.company_a)
    # The Case's confirmation is outdated. The shared investigation guidance continues ...
    ask = "How should we look into what happened?"
    investigating = browser.post(
        ask, understood(ask, pathway="serious", topics=["serious_investigation"], turn=1)
    ).json()
    latest = records(db)[-1]
    assert latest["jurisdiction"] is None and latest["jurisdiction_state"] == "case_not_sure"
    assert latest["presentation"] == "guidance"
    assert browser.chat is not None
    data = browser.chat.phase("response")[0].data
    assert data["approved_knowledge"]["approved_guidance"]
    assert data["jurisdiction_note"].startswith("Not confirmed for this employee")
    # ... the Case is in progress, waiting only for the jurisdiction to be confirmed ...
    status = investigating["conversation"]["status"]
    assert status["lifecycle"] == "in_progress"
    assert status["attention"]["jurisdiction"] == "needs_confirmation"
    assert status["attention"]["needs_information"] is True
    # ... and a jurisdiction-specific decision is held until it is, with neither
    # jurisdiction's own text (no UAE Federal and no DIFC rule) reaching the model.
    suspend = "Can I suspend him without pay?"
    held = browser.post(
        suspend,
        understood(
            suspend,
            topics=["disciplinary_suspension"],
            actions=[("opt-suspension", "suspend him without pay")],
            turn=2,
        ),
    ).json()
    (step,) = records(db)[-1]["actions"]
    assert step["disposition"] == "block" and "jurisdiction:case_not_sure" in step["reasons"]
    assert held["messages"][1]["outcome"]["kind"] == "block"
    knowledge = json.dumps(browser.chat.phase("response")[0].data["approved_knowledge"])
    for text in ("DIFC Example Suspension", "In DIFC", "900 days"):
        assert text not in knowledge
    assert held["conversation"]["status"]["lifecycle"] == "in_progress"


# --- pages and bounded context ------------------------------------------------------------------


def test_conversations_page_by_a_stable_cursor(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: Any, browser: Http
) -> None:
    for i in range(5):
        Founder(db, artifacts, alice_context).say(f"Matter {i}.", late(f"Matter {i}."))
    seen: list[str] = []
    before = None
    pages = 0
    while True:
        page = browser.get(limit=2, **({} if before is None else {"before": before})).json()
        seen += [item["id"] for item in page["items"]]
        pages += 1
        before = page["next_before"]
        if before is None:
            break
    assert pages == 3 and len(seen) == len(set(seen)) == 5
    listed = browser.get(limit=50).json()["items"]
    assert [i["id"] for i in listed] == seen
    stamps = [i["updated_at"] for i in listed]
    assert stamps == sorted(stamps, reverse=True)
    assert set(listed[0]) == {"id", "title", "case", "created_at", "updated_at"}
    assert browser.get(before="not-a-cursor").status_code == 422


def test_messages_page_by_sequence_and_new_ones_never_move_older_pages(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: Any, browser: Http
) -> None:
    founder = Founder(db, artifacts, alice_context)
    for i in range(10):
        founder.say(f"Update {i}.", late(f"Update {i}.", turn=i))
    browser.conversation, browser.revision = str(founder.conversation_id), founder.revision
    first = browser.detail(limit=6)
    assert [m["sequence"] for m in first["messages"]] == list(range(15, 21))
    sequences = [m["sequence"] for m in first["messages"]]
    before = first["next_before"]
    founder.say("A new message.", late("A new message.", turn=10))  # appended meanwhile
    while before is not None:
        page = browser.get(f"/{browser.conversation}/messages", before=before, limit=6).json()
        sequences = [m["sequence"] for m in page["messages"]] + sequences
        before = page["next_before"]
    assert sequences == list(range(1, 21))
    assert browser.get(f"/{browser.conversation}/messages", before=0).status_code == 422
    assert browser.get(f"/{browser.conversation}/messages", limit=101).status_code == 422


def test_the_model_sees_a_bounded_window_of_a_long_conversation(
    db: sessionmaker[Session], artifacts: Artifacts, alice_context: Any, browser: Http
) -> None:
    founder = Founder(db, artifacts, alice_context)
    for i in range(12):
        founder.say(f"Update {i}.", late(f"Update {i}.", turn=min(i, 6)))
    assert founder.provider is not None
    sent = founder.provider.phase("understanding")[0].data["founder_messages"]
    # The latest founder messages only (the gateway's bound), never the whole history.
    assert [m["text"] for m in sent] == [f"Update {i}." for i in range(5, 12)]
    window = founder.provider.phase("response")[0].data["conversation"]
    assert len(window) <= 6 and "Update 0." not in str(window)
    # The product keeps every message.
    browser.conversation = str(founder.conversation_id)
    assert len(browser.detail(limit=100)["messages"]) == 24


# --- failed interactions and closure --------------------------------------------------------------


def test_a_fixed_safety_fallback_is_a_completed_interaction(
    browser: Http, db: sessionmaker[Session]
) -> None:
    """The provider fails after Expert Review was decided: the server's own words are stored."""
    answered = browser.post(FIRE, fire(), AssistantError("timeout"))
    assert answered.status_code == 200
    heroos = answered.json()["messages"][1]
    assert heroos["outcome"]["kind"] == "expert_review"
    assert counts(db)["assistant_turns"] == 1
    assert answered.json()["conversation"]["status"]["attention"]["expert_review"]["active"]


def test_a_polite_reply_never_closes_the_case(browser: Http, db: sessionmaker[Session]) -> None:
    case = browser.post(LATE, late()).json()["conversation"]["case"]
    thanks = "I'm happy, thanks."
    body = browser.post(thanks, understanding(intent="unclear")).json()
    assert body["conversation"]["case"] == case
    assert body["conversation"]["status"]["lifecycle"] == "in_progress"
    assert counts(db)["workflow_progress_events"] == counts(db)["workflow_decision_records"] == 0
