"""Conversation memory and question orchestration through the gateway (robustness pass).

The model is scripted; each test fixes what it proposes and proves what the server does with
it across turns, the way a persisted conversation carries its memory:

- what the founder said stays said after the understanding phase stops reading it, and a
  hedge or correction in the newest message replaces it (never trusted either way);
- a question the founder doesn't know, or left unanswered twice, is not asked again, while
  the safeguard it serves still holds the step;
- HeroOS's required question is its own, asked once per reply, in its own words;
- a reply that fails a check is rewritten once before the fixed fallback;
- a short reply, thanks or a goodbye in the middle of a matter continues it; a message with
  no matter gets a short reply in words (checked like any other), not a canned paragraph.
"""

from typing import Any

import pytest

from app.assistant.gateway.memory import AskRecord, ConversationMemory
from app.assistant.gateway.prompts import LIGHT_INSTRUCTION, RESPONSE_INSTRUCTION
from app.assistant.gateway.service import (
    OUTSIDE,
    OUTSIDE_AGAIN,
    UNCLEAR,
    FounderTurn,
    GatewayReply,
)
from app.assistant.provider import ChatTurn
from tests.evaluation.test_golden import SAFE, Conversation, evaluation, kind, understood
from tests.fixtures.evaluation import Artifacts
from tests.fixtures.gateway import ScriptedProvider, fact, response

WARN = "Can I give him a formal warning?"
EXPLAIN_QUESTION = "Could you tell me about given opportunity to explain?"
POLICY = "employee_aware_of_relevant_policy"
POLICY_QUESTION = "Had the employee been told what was expected of them?"


class Remembering(Conversation):
    """A persisted conversation: its memory comes back each turn, as its checkpoint keeps it."""

    def __init__(self, artifacts: Artifacts) -> None:
        super().__init__(artifacts)
        self.memory = ConversationMemory()

    def say(self, message: str, understanding: Any, reply: Any = None) -> GatewayReply:
        self.provider = ScriptedProvider(understanding, reply or response(SAFE, ["q1"]))
        result = self.gateway(self.provider).respond(
            self.founder,
            FounderTurn(message, self.history, self.continuation, memory=self.memory),
        )
        self.history += (ChatTurn("user", message), ChatTurn("assistant", result.reply))
        self.continuation = result.continuation
        self.memory = result.memory
        return result

    def shown(self) -> dict[str, Any]:
        assert self.provider is not None
        data: dict[str, Any] = self.provider.phase("response")[0].data
        return data


def warning(chat: Remembering) -> GatewayReply:
    return chat.say(
        WARN,
        understood(WARN, topics=["formal_warning"], actions=[("opt-warning", "a formal warning")]),
    )


def aside(chat: Remembering, message: str, previous: str = "not_answered") -> GatewayReply:
    # The understanding keeps reading the warning asked about in the first message.
    data = understood(
        message, topics=["formal_warning"], actions=[("opt-warning", "a formal warning")], turn=0
    )
    data["previous_question_answer"] = previous
    return chat.say(message, data)


def disposition(result: GatewayReply) -> str:
    return next(a.disposition for a in evaluation(result).actions if a.action == "opt-warning")


# --- not known, not answered ---------------------------------------------------------------


@pytest.mark.parametrize(
    "message", ["I'd need to check.", "No idea, I wasn't there.", "My manager might know."]
)
def test_a_question_the_founder_doesnt_know_is_not_asked_again(
    artifacts: Artifacts, message: str
) -> None:
    chat = Remembering(artifacts)
    first = warning(chat)
    assert first.reply.endswith(EXPLAIN_QUESTION) and kind(first) == "block"
    result = aside(chat, message, previous="does_not_know")
    assert EXPLAIN_QUESTION not in result.reply
    # The safeguard still holds the step: nothing about it became known.
    assert "given_opportunity_to_explain" not in evaluation(result).facts.engine
    assert disposition(result) == "block"
    state = chat.shown()["conversation_state"]
    assert state["founder_does_not_know"] == ["given opportunity to explain"]
    assert "don't know" in state["last_question"]["founder_reply"]
    for later in ("What else should I do?", "OK.", "And then?"):
        assert EXPLAIN_QUESTION not in aside(chat, later).reply


def test_an_unanswered_question_is_asked_at_most_twice(artifacts: Artifacts) -> None:
    chat = Remembering(artifacts)
    replies = [warning(chat)] + [
        aside(chat, f"Something else entirely, part {i}.") for i in range(5)
    ]
    asked = [r for r in replies if r.reply.endswith(EXPLAIN_QUESTION)]
    assert len(asked) == 2  # never twice in a row, never a third time
    assert not replies[1].reply.endswith(EXPLAIN_QUESTION)
    assert all(disposition(r) == "block" for r in replies)  # the Block never weakens
    assert chat.memory.asked["given_opportunity_to_explain"] == AskRecord(2, "unanswered")


# --- said stays said; the newest statement controls ----------------------------------------


def said_earlier(chat: Remembering) -> GatewayReply:
    message = "He's late a lot. I explained the attendance standard to him last month."
    return chat.say(
        message,
        understood(
            message,
            pathway="less_serious",
            topics=["workplace_reminder"],
            facts=[fact(POLICY, "yes", "I explained the attendance standard to him")],
        ),
    )


def test_a_fact_said_earlier_stays_said_when_the_understanding_no_longer_reads_it(
    artifacts: Artifacts,
) -> None:
    chat = Remembering(artifacts)
    said_earlier(chat)
    later = "What should I do next?"
    result = chat.say(
        later, understood(later, pathway="less_serious", topics=["workplace_reminder"], turn=1)
    )
    facts = evaluation(result).facts
    assert facts.conversational[POLICY] == "yes" and POLICY not in facts.engine  # never trusted
    shown = chat.shown()
    assert [t["about"] for t in shown["approved_knowledge"]["question_targets"]] == []
    known = shown["conversation_state"]["known"]
    assert {"about": "Standard explained", "value": "Yes", "status": "said by the founder"} in known
    assert POLICY_QUESTION not in result.reply


@pytest.mark.parametrize(
    "now",
    [
        fact(POLICY, "yes", "I think I explained it", turn=1, basis="inferred", confidence="low"),
        fact(POLICY, "not_sure", "not sure I explained it", turn=1),
    ],
)
def test_a_correction_that_reduces_certainty_reduces_it(
    artifacts: Artifacts, now: dict[str, Any]
) -> None:
    chat = Remembering(artifacts)
    said_earlier(chat)
    message = f"Wait, {now['support_excerpt']}."
    result = chat.say(
        message,
        understood(message, pathway="less_serious", topics=["workplace_reminder"], facts=[now]),
    )
    facts = evaluation(result).facts
    assert facts.conversational.get(POLICY) in (None, "not_sure")
    assert chat.memory.said.get(POLICY) in (None, "not_sure")
    assert POLICY not in facts.engine


# --- one question, in HeroOS's own words ---------------------------------------------------


@pytest.mark.parametrize(
    "words",
    [
        SAFE,
        f"{SAFE} Did he get a chance to explain himself?",
        "Has he had a chance to tell his side? Has anyone spoken to him yet?",
    ],
)
def test_heroos_asks_its_required_question_once_in_its_own_words(
    artifacts: Artifacts, words: str
) -> None:
    chat = Remembering(artifacts)
    result = chat.say(
        WARN,
        understood(WARN, topics=["formal_warning"], actions=[("opt-warning", "a formal warning")]),
        response(words, ["q1"]),
    )
    assert result.reply.endswith(EXPLAIN_QUESTION)
    assert result.reply.count("?") == 1
    assert result.handoff.asked == ("given_opportunity_to_explain",)
    targets = chat.shown()["approved_knowledge"]["question_targets"]
    assert targets[0]["heroos_asks_after_your_reply"] == EXPLAIN_QUESTION


# --- a reply that fails a check is rewritten once ----------------------------------------------

LATE = "My employee has been late three times this month."
UNGROUNDED = f"{SAFE} He has 30 days to improve."


def test_a_reply_that_fails_a_check_is_rewritten_once(artifacts: Artifacts) -> None:
    chat = Remembering(artifacts)
    result = chat.say(
        LATE,
        understood(LATE, pathway="less_serious", topics=["workplace_reminder"]),
        [response(UNGROUNDED, ["q1"]), response(SAFE, ["q1"])],
    )
    assert chat.provider is not None
    rewrite = chat.provider.phase("response")[1]
    assert rewrite.system == RESPONSE_INSTRUCTION
    assert "number of days" in rewrite.turns[-1].content  # a fixed note, never the reply
    assert result.reply.startswith(SAFE) and "30 days" not in result.reply


def test_a_rewrite_that_fails_again_leaves_the_servers_fallback(artifacts: Artifacts) -> None:
    chat = Remembering(artifacts)
    result = chat.say(
        LATE,
        understood(LATE, pathway="less_serious", topics=["workplace_reminder"]),
        response(UNGROUNDED, ["q1"]),
    )
    assert chat.provider is not None and len(chat.provider.calls) == 3
    assert "30 days" not in result.reply


# --- short replies, thanks and no matter -------------------------------------------------------


@pytest.mark.parametrize("intent", ["unclear", "conversational"])
def test_a_short_reply_in_a_matter_continues_it(artifacts: Artifacts, intent: str) -> None:
    chat = Remembering(artifacts)
    warning(chat)
    result = chat.say("sort of", understood("sort of", intent=intent, workflow=None))
    assert result.reply != UNCLEAR and evaluation(result).workflow == "disciplinary"
    assert chat.provider is not None
    assert chat.provider.phase("response")[0].system == RESPONSE_INSTRUCTION
    assert kind(result) == "block"  # the matter's own result, unchanged
    if intent == "conversational":
        # Thanks or a goodbye: no required question forced on the founder.
        assert EXPLAIN_QUESTION not in result.reply


def test_a_message_with_no_matter_gets_a_short_reply_in_words(artifacts: Artifacts) -> None:
    chat = Remembering(artifacts)
    words = "Of course. What's happening at work, and who is involved?"
    result = chat.say(
        "Hi, I was hoping to get some advice about a staff member.",
        understood("", intent="unclear", workflow=None),
        response(words, []),
    )
    assert result.reply == words and result.state == "clarifying"
    assert chat.provider is not None
    light = chat.provider.phase("response")[0]
    assert light.system == LIGHT_INSTRUCTION
    assert "heroos_scope" in light.data and "approved_knowledge" not in light.data


def test_a_short_reply_that_fails_a_check_is_the_fixed_text(artifacts: Artifacts) -> None:
    chat = Remembering(artifacts)
    result = chat.say(
        "Not sure where to start.",
        understood("", intent="unclear", workflow=None),
        response("Under Article 120 you have 30 days.", []),
    )
    assert result.reply == UNCLEAR


def test_the_same_refusal_is_shorter_after_the_first_time(artifacts: Artifacts) -> None:
    chat = Remembering(artifacts)
    replies = [
        chat.say(m, understood("", intent="unsupported", workflow=None)).reply
        for m in ("Write me a caption.", "Just a short one, with emojis.", "Please?")
    ]
    assert replies[0].startswith(OUTSIDE.split(",", 1)[0]) and replies[0] != OUTSIDE_AGAIN
    assert replies[1] == replies[2] == OUTSIDE_AGAIN


def test_an_announcement_of_the_question_is_left_out(artifacts: Artifacts) -> None:
    """Found live: "HeroOS will ask you next whether ..." and then the same question."""
    chat = Remembering(artifacts)
    words = f"{SAFE} HeroOS will ask you next whether he had a chance to explain, since it matters."
    result = chat.say(
        WARN,
        understood(WARN, topics=["formal_warning"], actions=[("opt-warning", "a formal warning")]),
        response(words, ["q1"]),
    )
    assert result.reply == f"{SAFE} {EXPLAIN_QUESTION}"


def test_a_correction_drops_what_the_understanding_no_longer_reads(artifacts: Artifacts) -> None:
    """Found live: "it was raised with him before" corrected to "that was another operative", and
    the reading "discussed with him" taken from the same words stayed noted."""
    chat = Remembering(artifacts)
    first = "He's careless with stock, it has been raised with him before."
    chat.say(
        first,
        understood(
            first,
            pathway="less_serious",
            topics=["workplace_reminder"],
            facts=[
                fact("incident.history", "raised_before", "it has been raised with him before"),
                fact("incident.discussed_with_employee", "yes", "raised with him before"),
            ],
        ),
    )
    assert chat.memory.said.get("incident.discussed_with_employee") == "yes"
    fix = "Sorry, I got that wrong: that was another operative. For him it's the first time."
    result = chat.say(
        fix,
        understood(
            fix,
            pathway="less_serious",
            topics=["workplace_reminder"],
            facts=[fact("incident.history", "new", "For him it's the first time", turn=1)],
        ),
    )
    facts = evaluation(result).facts
    assert facts.conversational.get("incident.history") == "new"
    assert "incident.discussed_with_employee" not in facts.conversational


def test_the_jurisdiction_question_is_not_asked_twice_in_a_row(artifacts: Artifacts) -> None:
    chat = Remembering(artifacts)
    question = "Is this employee employed under your company's confirmed employment jurisdiction"
    first = "Can I give him a formal warning? He's on our DIFC entity's payroll."
    data = understood(
        first, topics=["formal_warning"], actions=[("opt-warning", "a formal warning")]
    )
    data["uncertainties"] = ["jurisdiction_conflict"]
    opened = chat.say(first, data)
    assert question in opened.reply
    words = "His contract is with the DIFC company."
    again = understood(
        words, topics=["formal_warning"], actions=[("opt-warning", "a formal warning")]
    )
    again["uncertainties"] = ["jurisdiction_conflict"]
    result = chat.say(words, again)
    assert question not in result.reply
    # Unresolved, so its safeguard still holds the step.
    assert evaluation(result).jurisdiction_state == "conversation_conflict"
    assert disposition(result) == "block"


def test_a_question_asked_again_after_an_uncertain_answer_says_so(artifacts: Artifacts) -> None:
    chat = Remembering(artifacts)
    warning(chat)
    unsure = "I think so?"
    data = understood(
        unsure,
        topics=["formal_warning"],
        actions=[("opt-warning", "a formal warning")],
        facts=[fact("given_opportunity_to_explain", "yes", "I think so", turn=1)],
    )
    chat.say(unsure, data)  # hedged: not asked again at once
    later = aside(chat, "What else do I need?")
    assert later.reply.endswith(
        "You weren't certain earlier, so just to check: could you tell me about given "
        "opportunity to explain?"
    )


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        (f"{SAFE} It matters for the warning, so", f"{SAFE} It matters for the warning, so c"),
        (f"{SAFE} One thing first:", f"{SAFE} One thing first: c"),
        ("Thanks", "Thanks. C"),
    ],
)
def test_the_question_follows_the_reply_as_one_sentence(
    artifacts: Artifacts, words: str, expected: str
) -> None:
    chat = Remembering(artifacts)
    result = chat.say(
        WARN,
        understood(WARN, topics=["formal_warning"], actions=[("opt-warning", "a formal warning")]),
        response(words, ["q1"]),
    )
    assert result.reply.startswith(expected)
    assert result.reply.endswith("ould you tell me about given opportunity to explain?")
