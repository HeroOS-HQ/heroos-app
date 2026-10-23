"""What the conversation already covered (``app.assistant.gateway.memory``), as pure functions.

The memory only ever makes HeroOS ask less and acknowledge accurately: it is never trusted,
and the founder's newest statement controls it.
"""

import pytest

from app.assistant.gateway.memory import (
    JURISDICTION,
    MAX_REMEMBERED,
    STATED,
    UNKNOWN_WORDS,
    AskRecord,
    ConversationMemory,
    Reading,
    conversation_view,
    provenance,
    record,
    resolve,
    superseded,
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
    said = ConversationMemory(said={"misconduct_level": Reading(STATED, 0)})
    assert "misconduct_level" in said.settled()


def test_a_hedge_now_removes_what_was_said_before() -> None:
    earlier = ConversationMemory(said={KEY: Reading("yes", 0)})
    hedged = after(earlier, (), hedged={KEY})
    assert KEY not in hedged.said and KEY not in hedged.settled()
    corrected = after(earlier, (), said={KEY: "no"}, sources={KEY: (1, 0)})
    assert corrected.said[KEY] == Reading("no", 1, 0)  # the newest statement controls


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
        record(ConversationMemory(said={"misconduct_level": Reading(STATED, 0)}), [("fact", KEY)]),
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


def test_an_uncertain_answer_is_recorded_as_such_and_asked_once_more_at_most() -> None:
    hedged = after(ASKED, (Asked("fact", KEY),), hedged={KEY}, uncertain={KEY})
    assert hedged.asked[KEY] == AskRecord(1, "hedged") and KEY not in hedged.settled()
    again = after(record(hedged, [("fact", KEY)]), (Asked("fact", KEY),), hedged={KEY})
    assert again.asked[KEY] == AskRecord(2, "approximate") and KEY in again.settled()
    assert again.asked_enough(KEY) and not hedged.asked_enough(KEY)
    view = conversation_view(None, LABELS, facts(), hedged, (Asked("fact", KEY),))
    assert view["answered_without_certainty"] == ["Standard explained"]
    assert "without being certain" in view["last_question"]["founder_reply"]  # type: ignore[index]


def test_a_rough_answer_is_never_acknowledged_as_an_uncertain_one() -> None:
    """ "Last week" is rough, not uncertain: the founder is never told they weren't certain."""
    rough = after(ASKED, (Asked("fact", KEY),), hedged={KEY})
    assert rough.asked[KEY] == AskRecord(1, "approximate")
    view = conversation_view(None, LABELS, facts(), rough, (Asked("fact", KEY),))
    assert view["answered_only_roughly"] == ["Standard explained"]
    assert view["answered_without_certainty"] == []
    reply = view["last_question"]["founder_reply"]  # type: ignore[index]
    assert "roughly" in reply and "never say they were" in reply


def test_founder_messages_are_numbered_and_readings_of_the_same_words_share_them() -> None:
    """Provenance: which founder message a reading came from, and which of its statements."""
    stated = [
        ("incident.date", 2, "Actually, it was Tuesday"),  # the current message
        ("incident.history", 0, "it has been raised with him before"),
        ("incident.discussed_with_employee", 0, "raised with him before"),
        ("evidence.witnesses", 0, "the whole shift saw it"),
        ("incident.date", 0, "on Monday"),  # read again from an older message: the newest wins
    ]
    sources = provenance(stated, current=2, turns=7)
    assert sources["incident.date"] == (7, 0)
    assert sources["incident.history"] == sources["incident.discussed_with_employee"] == (5, 0)
    assert sources["evidence.witnesses"] == (5, 1)
    memory = ConversationMemory(turns=7)
    after_turn = after(memory, (), said={"incident.date": "2026-10-20"}, sources=sources)
    assert after_turn.turns == 8 and after_turn.said["incident.date"] == Reading("2026-10-20", 7, 0)


def test_a_correction_supersedes_the_fact_and_what_rested_on_the_same_words_only() -> None:
    memory = ConversationMemory(
        said={
            "incident.history": Reading("raised_before", 0, 1),
            "incident.discussed_with_employee": Reading("yes", 0, 1),  # the same words
            "incident.date": Reading("2026-10-19", 0, 0),  # the same message, other words
            "evidence.witnesses": Reading("yes", 3, 1),  # another message
            "incident.evidence_available": Reading("yes", 0, UNKNOWN_WORDS),
        }
    )
    assert superseded(memory, {"incident.history"}, read_now=()) == {
        "incident.history",
        "incident.discussed_with_employee",
    }
    # Read again now, a reading stands on its own words.
    assert superseded(
        memory, {"incident.history"}, read_now={"incident.discussed_with_employee"}
    ) == {"incident.history"}
    assert superseded(memory, {"incident.date"}, read_now=()) == {"incident.date"}
    kept = after(memory, (), dropped={"incident.history", "incident.discussed_with_employee"})
    assert set(kept.said) == {"incident.date", "evidence.witnesses", "incident.evidence_available"}


def test_a_carried_reading_keeps_where_it_came_from() -> None:
    memory = ConversationMemory(said={KEY: Reading("no", 2, 1)}, turns=5)
    carried = after(memory, (), said={KEY: "no"})  # not read again this turn: no new source
    assert carried.said[KEY] == Reading("no", 2, 1)
    new = after(ConversationMemory(turns=5), (), said={KEY: "no"})  # noted before sources existed
    assert new.said[KEY] == Reading("no", 5, UNKNOWN_WORDS)


def test_a_question_that_doesnt_fit_is_never_asked_again() -> None:
    """ "n/a, he never came in": the founder said the question doesn't fit; it is accepted, never
    asked again, and never treated as an answer (the safeguard still holds the step)."""
    memory = after(ASKED, (Asked("fact", KEY),), does_not_apply=True)
    assert memory.asked[KEY] == AskRecord(1, "not_applicable")
    assert memory.asked_enough(KEY) and KEY in memory.settled() and KEY not in memory.said
    view = conversation_view(None, LABELS, facts(), memory, (Asked("fact", KEY),))
    assert "doesn't fit" in view["last_question"]["founder_reply"]  # type: ignore[index]


def test_the_step_results_already_explained_are_remembered_once() -> None:
    memory = record(ConversationMemory(), [], told=["opt-warning:unknown"])
    memory = record(memory, [], told=["opt-warning:unknown", "opt-dismissal:block"])
    assert memory.told == ("opt-warning:unknown", "opt-dismissal:block")
    assert after(memory, ()).told == memory.told  # the founder's message keeps it


# --- question coverage: answered conversationally is not the same as trusted -----------------


OTHER = "incident_discussed_with_employee"


@pytest.mark.parametrize(
    ("memory", "trusted", "coverage"),
    [
        (ConversationMemory(), {}, "unanswered"),
        (ConversationMemory(), {KEY: "no"}, "answered_explicitly"),
        (ConversationMemory(), {KEY: NOT_SURE}, "unknown_to_founder"),
        # "Nobody ever explained the rule to her": said plainly in the founder's story.
        (ConversationMemory(said={KEY: Reading("no", 0, 0)}), {}, "answered_from_narrative"),
        # "She says she just counted it wrong": clearly implied (the concern was put to her).
        (
            ConversationMemory(said={KEY: Reading("yes", 0, 0, "implied")}),
            {},
            "answered_from_narrative",
        ),
        # "I think somebody might have spoken to her": relevant, not clearly answered.
        (
            ConversationMemory(said={KEY: Reading("yes", 0, 0, "uncertain")}),
            {},
            "answered_uncertain",
        ),
        (ConversationMemory(said={KEY: Reading(STATED, 0, 0, "rough")}), {}, "answered_uncertain"),
        # "Not that I know of" is not knowing, never an authoritative "no".
        (ConversationMemory(said={KEY: Reading(NOT_SURE, 0, 0)}), {}, "unknown_to_founder"),
        (ConversationMemory(asked={KEY: AskRecord(1, "not_sure")}), {}, "unknown_to_founder"),
        # Answered HeroOS's question in words the server can't read as the answer.
        (ConversationMemory(asked={KEY: AskRecord(1, "answered")}), {}, "answered_from_narrative"),
        (ConversationMemory(asked={KEY: AskRecord(1, "hedged")}), {}, "answered_uncertain"),
        (ConversationMemory(asked={KEY: AskRecord(1, "not_applicable")}), {}, "not_applicable"),
        (ConversationMemory(asked={KEY: AskRecord(1, "unanswered")}), {}, "unanswered"),
    ],
)
def test_coverage_says_where_a_question_stands(
    memory: ConversationMemory, trusted: dict[str, str], coverage: str
) -> None:
    assert memory.coverage(KEY, trusted) == coverage


def test_a_question_whose_reading_was_taken_back_is_superseded() -> None:
    assert ConversationMemory().coverage(KEY, {}, withdrawn={KEY}) == "superseded"
    stated = ConversationMemory(said={KEY: Reading("no", 1, 0)})
    assert stated.coverage(KEY, {}, withdrawn={KEY}) == "answered_from_narrative"  # restated


def test_a_reading_that_only_covers_its_question_is_never_said_again_as_the_founders_fact() -> None:
    memory = ConversationMemory(
        said={
            KEY: Reading("yes", 0, 0, "implied"),
            OTHER: Reading("yes", 0, 1, "uncertain"),
            "misconduct_level": Reading("less_serious", 0, 2),
        }
    )
    view = conversation_view(None, {**LABELS, OTHER: "Discussed"}, None, memory, ())
    assert view["known"] == [
        {"about": "How serious it is", "value": "less serious", "status": "said by the founder"},
        {
            "about": "Standard explained",
            "value": "yes",
            "status": "clear from what the founder said",
        },
    ]
    assert view["answered_without_certainty"] == ["Discussed"]
    assert memory.settled() >= {KEY, OTHER}  # never asked as if the founder hadn't spoken


@pytest.mark.parametrize(
    ("uncertain", "implied", "certainty"),
    [({KEY}, set(), "uncertain"), (set(), {KEY}, "implied"), (set(), set(), "rough")],
)
def test_what_a_message_touches_without_stating_it_is_kept_as_covering_its_question(
    uncertain: set[str], implied: set[str], certainty: str
) -> None:
    memory = after(
        ConversationMemory(turns=1),
        (),
        hedged={KEY},
        uncertain=uncertain,
        implied=implied,
        touched={KEY: "yes"},
        sources={KEY: (1, 0)},
    )
    assert memory.said[KEY] == Reading("yes", 1, 0, certainty)  # type: ignore[arg-type]


def test_an_implied_answer_to_the_question_asked_is_an_answer() -> None:
    memory = after(ASKED, (Asked("fact", KEY),), hedged={KEY}, implied={KEY}, touched={KEY: "yes"})
    assert memory.asked[KEY].last == "answered"
    assert memory.coverage(KEY) == "answered_from_narrative"


def test_a_correction_to_uncertainty_reduces_that_question_only() -> None:
    """ "The manager warned him" then "actually, I don't know whether the manager spoke to him":
    that question is now uncertain; an unrelated reading stands."""
    earlier = ConversationMemory(
        said={OTHER: Reading("yes", 0, 0), "misconduct_level": Reading("less_serious", 0, 1)},
        turns=1,
    )
    dropped = superseded(earlier, {OTHER}, {OTHER})
    memory = after(
        earlier,
        (),
        hedged={OTHER},
        uncertain={OTHER},
        dropped=dropped,
        touched={OTHER: "yes"},
        sources={OTHER: (1, 0)},
    )
    assert memory.coverage(OTHER) == "answered_uncertain"
    assert memory.said["misconduct_level"] == Reading("less_serious", 0, 1)
    assert memory.coverage("misconduct_level") == "answered_from_narrative"


@pytest.mark.parametrize("hesitant", [True, False])
def test_a_reply_to_the_question_without_certainty_is_an_uncertain_answer(hesitant: bool) -> None:
    """ "I think so but I'm not 100% sure" with no reading of the fact: answered uncertainly (found
    in the coverage pass: recorded as no answer, and asked again later)."""
    memory = after(ASKED, (Asked("fact", KEY),), hesitant=hesitant)
    assert memory.asked[KEY].last == ("hedged" if hesitant else "unanswered")
