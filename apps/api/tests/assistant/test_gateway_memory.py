"""What the conversation already covered (``app.assistant.gateway.memory``), as pure functions.

The memory only ever makes HeroOS ask less and acknowledge accurately: it is never trusted,
and the founder's newest statement controls it.
"""

import pytest

from app.assistant.gateway.memory import (
    JURISDICTION,
    MAX_REMEMBERED,
    STATED,
    AskRecord,
    ConversationMemory,
    conversation_view,
    record,
    resolve,
)
from app.evaluation.facts import NOT_SURE, Asked
from app.evaluation.model import TrustedFactState

KEY = "employee_aware_of_relevant_policy"
LABELS = {KEY: "Standard explained", "misconduct_level": "How serious it is"}


def facts(engine=None, conversational=None, sources=None) -> TrustedFactState:  # type: ignore[no-untyped-def]
    return TrustedFactState(
        engine=engine or {}, sources=sources or {}, conversational=conversational or {}
    )


def after(memory: ConversationMemory, previous: tuple[Asked, ...], **kwargs) -> ConversationMemory:  # type: ignore[no-untyped-def]
    defaults = dict(
        facts=facts(), stated=(), answered=False, does_not_know=False,
        jurisdiction_answered=False, said={}, hedged=(),
    )  # fmt: skip
    return resolve(memory, previous=previous, **{**defaults, **kwargs})


ASKED = record(ConversationMemory(), [("fact", KEY)])


@pytest.mark.parametrize(
    ("kwargs", "outcome"),
    [
        ({"stated": {KEY}}, "answered"),  # stated in any words
        ({"answered": True}, "answered"),  # a direct answer
        ({"facts": facts(engine={KEY: NOT_SURE})}, "not_sure"),
        ({"facts": facts(conversational={KEY: NOT_SURE}), "stated": {KEY}}, "not_sure"),
        ({"does_not_know": True}, "not_sure"),  # "I'd need to check", "I wasn't there"...
        ({}, "unanswered"),  # something else: never treated as an answer
    ],
)
def test_the_founders_reply_is_recorded_against_the_last_question(
    kwargs: dict[str, object], outcome: str
) -> None:
    memory = after(ASKED, (Asked("fact", KEY),), **kwargs)
    assert memory.asked[KEY] == AskRecord(1, outcome)  # type: ignore[arg-type]


def test_settled_is_said_answered_not_known_or_ignored_twice() -> None:
    once = after(ASKED, (Asked("fact", KEY),))
    assert KEY not in once.settled()  # unanswered once: HeroOS may come back to it
    twice = after(record(once, [("fact", KEY)]), (Asked("fact", KEY),))
    assert twice.asked[KEY] == AskRecord(2, "unanswered") and KEY in twice.settled()
    not_known = after(ASKED, (Asked("fact", KEY),), does_not_know=True)
    assert KEY in not_known.settled() and KEY in not_known.not_known()
    said = ConversationMemory(said={"misconduct_level": STATED})
    assert "misconduct_level" in said.settled()


def test_a_hedge_now_removes_what_was_said_before() -> None:
    earlier = ConversationMemory(said={KEY: "yes"})
    hedged = after(earlier, (), hedged={KEY})
    assert KEY not in hedged.said and KEY not in hedged.settled()
    corrected = after(earlier, (), said={KEY: "no"})
    assert corrected.said[KEY] == "no"  # the newest statement controls


def test_two_questions_at_once_are_never_answered_by_a_bare_reply() -> None:
    both = record(ConversationMemory(), [("fact", KEY), ("fact", "misconduct_level")])
    memory = after(both, (Asked("fact", KEY), Asked("fact", "misconduct_level")), answered=True,
                   does_not_know=True)  # fmt: skip
    assert {k: r.last for k, r in memory.asked.items()} == {
        KEY: "unanswered",
        "misconduct_level": "unanswered",
    }


def test_the_jurisdiction_question_and_insistence() -> None:
    asked = record(ConversationMemory(), [("jurisdiction", "jurisdiction"), ("insistence", "cap")])
    assert set(asked.asked) == {JURISDICTION}  # insistence: its safeguard's own protocol
    replied = after(asked, (Asked("jurisdiction", "jurisdiction"),), jurisdiction_answered=True)
    assert replied.asked[JURISDICTION].last == "answered"


def test_memory_stays_bounded() -> None:
    memory = ConversationMemory()
    for i in range(MAX_REMEMBERED + 10):
        memory = record(memory, [("fact", f"fact_{i}")])
    assert len(memory.asked) == MAX_REMEMBERED and f"fact_{MAX_REMEMBERED + 9}" in memory.asked


def test_the_view_says_what_is_known_not_known_and_how_the_last_question_went() -> None:
    memory = after(
        record(ConversationMemory(said={"misconduct_level": STATED}), [("fact", KEY)]),
        (Asked("fact", KEY),),
        does_not_know=True,
    )
    view = conversation_view(None, LABELS, facts(), memory, (Asked("fact", KEY),))
    assert view["known"] == [
        {"about": "How serious it is", "value": "see the conversation",
         "status": "said by the founder"}
    ]  # fmt: skip
    assert view["founder_does_not_know"] == ["Standard explained"]
    last = view["last_question"]
    assert isinstance(last, dict) and last["about"] == "Standard explained"
    assert "don't know" in last["founder_reply"]
    unanswered = after(ASKED, (Asked("fact", KEY),))
    view = conversation_view(None, LABELS, facts(), unanswered, (Asked("fact", KEY),))
    assert view["asked_before_without_an_answer"] == ["Standard explained"]
    assert "never treat it as answered" in view["last_question"]["founder_reply"]  # type: ignore[index]
    confirmed = facts(engine={KEY: "yes"}, sources={KEY: "direct_answer"})
    view = conversation_view(None, LABELS, confirmed, ConversationMemory(), ())
    assert view["known"] == [
        {"about": "Standard explained", "value": "yes", "status": "confirmed by the founder"}
    ]
    assert "last_question" not in view
