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

from datetime import date
from typing import Any

import pytest

from app.assistant.gateway.memory import AskRecord, ConversationMemory
from app.assistant.gateway.prompts import LIGHT_INSTRUCTION, RESPONSE_INSTRUCTION
from app.assistant.gateway.service import (
    OUTSIDE,
    OUTSIDE_AGAIN,
    UNCLEAR,
    AiGateway,
    FounderTurn,
    GatewayReply,
    _with_question,
    asked_again,
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
    question = EXPLAIN_QUESTION[:1].lower() + EXPLAIN_QUESTION[1:]
    asked = [r for r in replies if r.reply.lower().endswith(question.lower())]
    assert len(asked) == 2  # never twice in a row, never a third time
    assert not replies[1].reply.lower().endswith(question.lower())
    # The second time says it is still needed, never the same question word for word.
    assert asked[1].reply.endswith(f"One thing I still need to know: {question}")
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
    said = chat.memory.said[POLICY]
    # Never the founder's fact again; the question stays covered as they now put it.
    assert said.value == "not_sure" or said.certainty == "uncertain"
    assert chat.memory.coverage(POLICY) in ("answered_uncertain", "unknown_to_founder")
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
    said = chat.memory.said.get("incident.discussed_with_employee")
    assert said is not None and said.value == "yes"
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


def test_an_uncertain_answer_is_asked_again_only_when_the_step_needs_it(
    artifacts: Artifacts,
) -> None:
    """Found in the final pass: "You weren't certain earlier, so just to check: ..." on a turn
    about something else read as asking again. An uncertain answer covers the question; it is
    asked once more only when the founder pursues the step it holds."""
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
    assert "opportunity to explain" not in later.reply
    assert chat.memory.coverage("given_opportunity_to_explain") == "answered_uncertain"
    pursued = chat.say(
        WARN,
        understood(
            WARN, topics=["formal_warning"], actions=[("opt-warning", "a formal warning")], turn=3
        ),
    )
    assert pursued.reply.endswith(
        "Before you go ahead, I need to check something you weren't sure about: could you tell "
        "me about given opportunity to explain?"
    )
    assert disposition(pursued) == "block"  # the uncertain answer never cleared the step
    assert "given_opportunity_to_explain" not in evaluation(pursued).facts.engine


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


def test_an_earlier_dont_know_never_answers_a_later_question(artifacts: Artifacts) -> None:
    """Found live: "i don't know to be honest" answered one question and was read, a turn later,
    as not knowing the next question asked."""
    chat = Remembering(artifacts)
    late = "He's late a lot."
    chat.say(late, understood(late, pathway="less_serious", topics=["workplace_reminder"]))
    unsure = "i don't know to be honest"
    first = chat.say(
        unsure,
        understood(
            unsure,
            pathway="less_serious",
            topics=["workplace_reminder"],
            facts=[fact(POLICY, "not_sure", unsure, turn=1)],
        ),
    )
    assert evaluation(first).facts.conversational[POLICY] == "not_sure"  # said plainly
    later = "OK, what now?"
    result = chat.say(
        later,
        understood(
            later,
            pathway="less_serious",
            topics=["workplace_reminder"],
            facts=[
                fact(
                    "incident.history", "not_sure", unsure, turn=1, provenance="prior_user_message"
                ),
            ],
        ),  # fmt: skip
    )
    assert "incident.history" not in evaluation(result).facts.conversational
    assert chat.memory.asked.get("incident.history") is None or (
        chat.memory.asked["incident.history"].last != "not_sure"
    )


def test_the_jurisdiction_question_asked_again_says_why_a_yes_or_no_helps(
    artifacts: Artifacts,
) -> None:
    chat = Remembering(artifacts)
    first = "Can I give him a formal warning? He's on our DIFC entity's payroll."

    def conflicted(message: str, previous: str = "no_question") -> dict[str, Any]:
        data = understood(
            message, topics=["formal_warning"], actions=[("opt-warning", "a formal warning")]
        )
        data["uncertainties"] = ["jurisdiction_conflict"]
        data["previous_question_answer"] = previous
        return data

    chat.say(first, conflicted(first))
    chat.say("His contract is with the DIFC company.", conflicted("x", "answered"))
    result = chat.say("What can I do meanwhile?", conflicted("y", "not_answered"))
    assert "To settle it for the case, a plain yes or no helps: is this employee employed" in (
        result.reply
    )


# --- where each reading came from: a correction replaces only what it corrects ----------------

MONDAY = "It happened on Monday and the manager spoke to him about it."
DISCUSSED = "incident.discussed_with_employee"


def on_monday(chat: Remembering) -> GatewayReply:
    return chat.say(
        MONDAY,
        understood(
            MONDAY,
            pathway="less_serious",
            topics=["workplace_reminder"],
            facts=[
                fact("incident.date", "2026-10-19", "on Monday"),
                fact(DISCUSSED, "yes", "the manager spoke to him about it"),
            ],
        ),
    )


def test_a_correction_replaces_only_the_reading_it_corrects(artifacts: Artifacts) -> None:
    """ "Actually, it was Tuesday" corrects the date; that the manager spoke to him stands, even
    when the understanding doesn't read it again (found in the final run: a correction dropped
    every other reading, and those facts were asked for again)."""
    chat = Remembering(artifacts)
    on_monday(chat)
    assert chat.memory.said[DISCUSSED].turn == chat.memory.said["incident.date"].turn == 0
    fix = "Actually, it was Tuesday."
    result = chat.say(
        fix,
        understood(
            fix,
            pathway="less_serious",
            topics=["workplace_reminder"],
            facts=[fact("incident.date", "2026-10-20", "it was Tuesday", turn=1)],
        ),
    )
    facts = evaluation(result).facts
    assert facts.conversational["incident.date"] == "2026-10-20"
    assert facts.conversational[DISCUSSED] == "yes"
    assert chat.memory.said["incident.date"].turn == 1
    assert chat.memory.said[DISCUSSED].value == "yes" and chat.memory.said[DISCUSSED].turn == 0
    known = chat.shown()["conversation_state"]["known"]
    assert any("discussed" in k["about"].lower() and k["value"] == "Yes" for k in known)


def test_saying_they_are_no_longer_sure_revokes_what_they_said_before(artifacts: Artifacts) -> None:
    """ "The manager warned her", then "Actually, I'm not sure the manager spoke to her": the later,
    less certain statement controls; the first is not kept because it came first, and it never
    comes back on a later turn."""
    chat = Remembering(artifacts)
    on_monday(chat)
    unsure = "Actually, I'm not sure the manager spoke to him."
    result = chat.say(
        unsure,
        understood(
            unsure,
            pathway="less_serious",
            topics=["workplace_reminder"],
            facts=[fact(DISCUSSED, "not_sure", "I'm not sure the manager spoke to him", turn=1)],
        ),
    )
    assert evaluation(result).facts.conversational.get(DISCUSSED) == "not_sure"
    later = "What should I do next?"
    result = chat.say(
        later, understood(later, pathway="less_serious", topics=["workplace_reminder"], turn=2)
    )
    facts = evaluation(result).facts
    assert (
        facts.conversational.get(DISCUSSED) in (None, "not_sure") and DISCUSSED not in facts.engine
    )
    assert facts.conversational["incident.date"] == "2026-10-19"  # untouched


def test_a_reading_dropped_by_a_correction_never_comes_back(artifacts: Artifacts) -> None:
    """Found while adding provenance: the reading a correction dropped stayed remembered, and
    the next turn brought it back as said."""
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
                fact(DISCUSSED, "yes", "raised with him before"),
            ],
        ),
    )
    fix = "Sorry, I got that wrong: that was another operative. For him it's the first time."
    chat.say(
        fix,
        understood(
            fix,
            pathway="less_serious",
            topics=["workplace_reminder"],
            facts=[fact("incident.history", "new", "For him it's the first time", turn=1)],
        ),
    )
    later = "OK. What happens next?"
    result = chat.say(
        later, understood(later, pathway="less_serious", topics=["workplace_reminder"], turn=2)
    )
    facts = evaluation(result).facts
    assert DISCUSSED not in facts.conversational and DISCUSSED not in chat.memory.said
    assert facts.conversational["incident.history"] == "new"


# --- final semantics pass: dates on the calendar, doubt per statement, exact fact meanings ------


class OnThursday(Remembering):
    """The scenario day of the natural-conversation corpus: Thursday 22 October 2026."""

    def gateway(self, provider: ScriptedProvider) -> AiGateway:
        ai = super().gateway(provider)
        ai.today = lambda: date(2026, 10, 22)
        return ai


ABSENT = "Our cleaner Lalaine has not reported for duty since Tuesday 20 October."


def test_a_day_and_month_without_a_year_take_the_year_from_today(artifacts: Artifacts) -> None:
    """Found in the hybrid certification: "since Tuesday 20 October" read as 2020-10-20 (the 20th
    was a Tuesday then too) and noted. The understanding reads the words; the server puts them
    on the calendar: the most recent such day, not after today."""
    chat = OnThursday(artifacts)
    result = chat.say(
        ABSENT,
        understood(ABSENT, facts=[fact("incident.date", "2020-10-20", "since Tuesday 20 October")]),
    )
    assert evaluation(result).facts.conversational["incident.date"] == "2026-10-20"
    assert chat.memory.said["incident.date"].value == "2026-10-20"


def test_a_day_and_month_no_year_fits_are_never_noted(artifacts: Artifacts) -> None:
    """20 October 2026 is a Tuesday: "Wednesday 20 October" names a day no recent year has, so the
    reading stays non-authoritative rather than a guessed year."""
    words = "She has not come in since Wednesday 20 October."
    chat = OnThursday(artifacts)
    result = chat.say(
        words,
        understood(
            words, facts=[fact("incident.date", "2026-10-20", "since Wednesday 20 October")]
        ),
    )
    assert "incident.date" not in evaluation(result).facts.conversational


def test_a_doubt_about_another_statement_leaves_the_plain_one_said(artifacts: Artifacts) -> None:
    """Found in the hybrid certification: "I haven't spoken to her about it, and honestly I don't
    think I need her side" lost its plain "no" to the opinion's "I don't think"."""
    words = "She was late again on Monday. I haven't spoken to her about it, and honestly I don't "
    words += "think I need her side."
    chat = OnThursday(artifacts)
    result = chat.say(
        words,
        understood(words, facts=[fact(DISCUSSED, "no", "I haven't spoken to her about it")]),
    )
    assert evaluation(result).facts.conversational[DISCUSSED] == "no"


def test_a_doubt_still_qualifies_the_statement_it_is_part_of(artifacts: Artifacts) -> None:
    """ "She didn't come in Monday. I think her manager tried calling her.": the absence is said,
    the manager's contact is uncertain (never noted, even read as explicit)."""
    words = "She didn't come in Monday. I think her manager tried calling her."
    chat = OnThursday(artifacts)
    result = chat.say(
        words,
        understood(words, facts=[fact(DISCUSSED, "yes", "her manager tried calling her")]),
    )
    assert DISCUSSED not in evaluation(result).facts.conversational
    assert chat.memory.said[DISCUSSED].certainty == "uncertain"


def test_the_understanding_sees_what_the_history_facts_mean_exactly(artifacts: Artifacts) -> None:
    """Found in the hybrid certification: "repeated till errors" and "not a one-off" were read as
    the issue having been raised before. A Case fact's exact meaning is in the catalog."""
    chat = OnThursday(artifacts)
    chat.say(LATE, understood(LATE, pathway="less_serious", topics=["workplace_reminder"]))
    assert chat.provider is not None
    catalog = chat.provider.phase("understanding")[0].data["routing_catalog"]
    means = {f["key"]: f.get("means", "") for f in catalog["facts"]}
    assert "keeps happening" in means["incident.history"]
    assert "matter now being handled" in means["incident.discussed_with_employee"]


# --- an answer in the founder's own words: bound only when it answers the question ---------------


def asked_policy(chat: Remembering) -> GatewayReply:
    result = chat.say(LATE, understood(LATE, pathway="less_serious", topics=["workplace_reminder"]))
    assert result.reply.endswith(POLICY_QUESTION)
    return result


def answer(chat: Remembering, words: str, previous: str, *facts: dict[str, Any]) -> GatewayReply:
    data = understood(words, pathway="less_serious", topics=["workplace_reminder"], facts=[*facts])
    data["previous_question_answer"] = previous
    return chat.say(words, data)


@pytest.mark.parametrize(
    "words",
    [
        "No. The rule was never explained to him and he was not given the policy.",
        "No, nobody ever explained it to him.",
        "Nope - he never got the policy.",
        "No and he never signed anything either.",
    ],
)
def test_a_reply_that_opens_with_the_answer_answers_the_question(
    artifacts: Artifacts, words: str
) -> None:
    """Found in the final run: "No. The rule was never explained to her ..." was not taken as the
    answer, and the same question came back three times. The opening "No" answers it when the
    understanding reads the reply as that answer; the rest is read for what else it says."""
    chat = Remembering(artifacts)
    asked_policy(chat)
    result = answer(chat, words, "answered", fact(POLICY, "no", words, turn=1))
    facts = evaluation(result).facts
    assert facts.engine[POLICY] == "no" and facts.sources[POLICY] == "direct_answer"
    assert POLICY_QUESTION.lower() not in result.reply.lower()


@pytest.mark.parametrize(
    ("words", "previous", "reading"),
    [
        # A yes or no about something else answers nothing (the brief's example).
        ("No, nobody has heard from him.", "not_answered", None),
        ("No, nobody has heard from him.", "answered", None),
        # Doubt anywhere keeps it from binding.
        ("Yes, I think so.", "answered", "yes"),
        ("No, but I'd need to check with his manager.", "answered", "no"),
        ("Yes. Well, I was told he got the handbook.", "answered", "yes"),
        # The understanding reads another answer than the opening word: nothing is bound.
        ("No, he knew the rule well.", "answered", "yes"),
        # No plain answer opens it.
        ("Nobody ever explained it to him.", "answered", "no"),
        ("No idea, sorry.", "does_not_know", None),
    ],
)
def test_an_opening_yes_or_no_answers_nothing_unless_the_reply_answers_the_question(
    artifacts: Artifacts, words: str, previous: str, reading: str | None
) -> None:
    chat = Remembering(artifacts)
    asked_policy(chat)
    facts = [] if reading is None else [fact(POLICY, reading, words, turn=1)]
    result = answer(chat, words, previous, *facts)
    assert evaluation(result).facts.engine.get(POLICY) is None


def test_an_answer_with_more_facts_binds_the_answer_and_reads_the_rest(
    artifacts: Artifacts,
) -> None:
    """ "No, and nobody has spoken to him about it yet": the opening answers the question asked;
    the rest is another reading (said, never trusted by the opening word)."""
    chat = Remembering(artifacts)
    asked_policy(chat)
    words = "No, and nobody has spoken to him about it yet."
    result = answer(
        chat,
        words,
        "answered",
        fact(POLICY, "no", "No", turn=1),
        fact(DISCUSSED, "no", "nobody has spoken to him about it yet", turn=1),
    )
    facts = evaluation(result).facts
    assert facts.engine[POLICY] == "no"
    assert facts.conversational.get(DISCUSSED) == "no" and DISCUSSED not in facts.engine


def test_a_question_answered_in_the_founders_own_words_is_not_asked_again(
    artifacts: Artifacts,
) -> None:
    """An answer the server can't rely on as it stands ("Nobody ever explained it to him") is
    noted, never trusted, and the same question is not asked again: the step stays held."""
    chat = Remembering(artifacts)
    asked_policy(chat)
    words = "Nobody ever explained it to him."
    result = answer(chat, words, "answered", fact(POLICY, "no", words, turn=1))
    facts = evaluation(result).facts
    assert POLICY not in facts.engine and facts.conversational[POLICY] == "no"
    assert POLICY_QUESTION.lower() not in result.reply.lower()
    for later in ("What else should I know?", "OK."):
        reply = chat.say(
            later, understood(later, pathway="less_serious", topics=["workplace_reminder"], turn=0)
        )
        assert POLICY_QUESTION.lower()[5:] not in reply.reply.lower()


def test_a_step_already_explained_is_marked_so_the_reply_doesnt_repeat_it(
    artifacts: Artifacts,
) -> None:
    """Found in the final run: the same "you can't take that step yet" in every reply. The
    response phase sees which step results an earlier reply already explained."""
    chat = Remembering(artifacts)
    warning(chat)
    steps = chat.shown()["heroos_outcome"]["steps"]
    assert all("already_told" not in step for step in steps)
    aside(chat, "What else should I do?")
    steps = chat.shown()["heroos_outcome"]["steps"]
    assert steps and all(step.get("already_told") is True for step in steps)


def test_a_question_the_founder_says_doesnt_fit_is_not_asked_again(artifacts: Artifacts) -> None:
    chat = Remembering(artifacts)
    first = warning(chat)
    assert first.reply.endswith(EXPLAIN_QUESTION)
    result = aside(chat, "n/a, that doesn't really fit here.", previous="does_not_apply")
    assert EXPLAIN_QUESTION not in result.reply
    assert disposition(result) == "block"  # the safeguard still holds the step
    for later in ("What else should I do?", "OK."):
        assert EXPLAIN_QUESTION.lower()[6:] not in aside(chat, later).reply.lower()


@pytest.mark.parametrize(
    "words",
    [
        "Thanks. One thing I still need to know:",
        "Thanks. one thing I still need to know:",
        "Thanks. To be sure I've got it right:",
    ],
)
def test_a_lead_in_the_reply_already_ends_with_is_not_said_twice(words: str) -> None:
    """Found in the final pass: "one thing I still need to know: one thing I still need to know:
    did the incident happen at work ...?" (the reply ended with the lead-in it had seen before)."""
    question = "One thing I still need to know: had the employee been told what was expected?"
    assert _with_question(words, question) == (
        "Thanks. One thing I still need to know: had the employee been told what was expected?"
    )


@pytest.mark.parametrize(
    ("question", "earlier", "expected"),
    [
        (
            f"Just to be sure I've understood: {POLICY_QUESTION[:1].lower()}{POLICY_QUESTION[1:]}",
            "unanswered",
            "One thing I still need to know: had the employee been told what was expected of them?",
        ),
        (
            POLICY_QUESTION,
            "hedged",
            "You weren't certain earlier, so just to check: had the employee been told what was "
            "expected of them?",
        ),
    ],
)
def test_a_question_asked_again_has_one_lead_in(question: str, earlier: str, expected: str) -> None:
    """Found in the final pass: "One thing I still need to know: just to be sure I've understood:
    has a disciplinary sanction ...?" (a confirmation asked a second time)."""
    assert asked_again(question, earlier) == expected


# --- question coverage: answered in the founder's story is not the same as trusted ----------

EXPLAIN = "given_opportunity_to_explain"
STORY = "Can I give him a formal warning? He already had his chance to explain himself."
STORY_WORDS = "He already had his chance to explain himself"
BEFORE_ACTING = "Before you go ahead, I need a plain answer on something you mentioned earlier:"


def narrated(chat: Remembering, *, basis: str = "explicit") -> GatewayReply:
    return chat.say(
        STORY,
        understood(
            STORY,
            topics=["formal_warning"],
            actions=[("opt-warning", "a formal warning")],
            facts=[fact(EXPLAIN, "yes", STORY_WORDS, basis=basis)],
        ),
        response(SAFE, []),
    )


@pytest.mark.parametrize("basis", ["explicit", "inferred"])
def test_a_question_answered_in_the_founders_story_is_not_asked_and_not_trusted(
    artifacts: Artifacts, basis: str
) -> None:
    """Found in the final pass: "nobody ever explained the rule to her", then at once "had the
    employee been told what was expected of them?". Said plainly or clearly implied ("inferred"
    with high confidence), the question is covered; the fact stays as untrusted as it was."""
    chat = Remembering(artifacts)
    result = narrated(chat, basis=basis)
    assert "opportunity to explain" not in result.reply
    assert EXPLAIN not in chat.memory.asked
    assert chat.memory.coverage(EXPLAIN) == "answered_from_narrative"
    facts = evaluation(result).facts
    assert EXPLAIN not in facts.engine  # never authoritative from the story
    assert disposition(result) == "block"  # the step it holds stays held
    label = next(m.label for m in evaluation(result).missing if m.key == EXPLAIN)
    outcome = chat.shown()["heroos_outcome"]
    assert outcome["mentioned_by_the_founder"]["about"] == [label]
    assert label not in outcome["still_needed"]
    if basis == "inferred":
        # Clearly implied: covers the question, never noted as the founder's fact.
        assert EXPLAIN not in facts.conversational
        assert chat.memory.said[EXPLAIN].certainty == "implied"
        known = chat.shown()["conversation_state"]["known"]
        assert {"status": "clear from what the founder said"} | {"about": label} in [
            {"status": k["status"], "about": k["about"]} for k in known
        ]


def test_a_narrative_answer_is_confirmed_once_when_the_founder_pursues_the_step(
    artifacts: Artifacts,
) -> None:
    """Confirmed only when HeroOS needs a fact it can rely on for the decision the founder is
    making, never merely because the question exists, and through the existing trust path."""
    chat = Remembering(artifacts)
    narrated(chat)
    later = aside(chat, "What should I prepare for the meeting?")  # not pursuing the step now
    assert "opportunity to explain" not in later.reply
    pursued = chat.say(
        WARN,
        understood(
            WARN, topics=["formal_warning"], actions=[("opt-warning", "a formal warning")], turn=2
        ),
    )
    assert pursued.reply.endswith(f"{BEFORE_ACTING} for given opportunity to explain, is it yes?")
    assert EXPLAIN not in evaluation(pursued).facts.engine
    confirmed = chat.say("Yes.", understood("Yes.", topics=["formal_warning"]), response(SAFE, []))
    facts = evaluation(confirmed).facts
    assert facts.engine[EXPLAIN] == "yes" and facts.sources[EXPLAIN] == "confirmation"


def test_a_hypothetical_step_never_asks_for_a_confirmation(artifacts: Artifacts) -> None:
    chat = Remembering(artifacts)
    narrated(chat)
    what_if = "Hypothetically, what if I gave him a formal warning?"
    data = understood(what_if, topics=["formal_warning"])
    data["hypothetical_actions"] = [
        {"action": "opt-warning", "source_turn": 1, "support_excerpt": "what if I gave him"}
    ]
    result = chat.say(what_if, data, response(SAFE, []))
    assert BEFORE_ACTING not in result.reply
    assert EXPLAIN not in chat.memory.asked


def test_implying_again_what_was_said_plainly_takes_nothing_back(artifacts: Artifacts) -> None:
    chat = Remembering(artifacts)
    narrated(chat)
    again = "He explained his side when we spoke."
    result = chat.say(
        again,
        understood(
            again,
            topics=["formal_warning"],
            facts=[fact(EXPLAIN, "yes", "He explained his side", turn=1, basis="inferred")],
        ),
        response(SAFE, []),
    )
    assert chat.memory.said[EXPLAIN].certainty == "stated"
    assert evaluation(result).facts.conversational[EXPLAIN] == "yes"
    assert EXPLAIN not in evaluation(result).facts.engine


def test_a_narrative_answer_made_uncertain_is_never_confirmed_as_said(
    artifacts: Artifacts,
) -> None:
    """ "Actually, I'm not sure he did": that question only is reduced to uncertain."""
    chat = Remembering(artifacts)
    narrated(chat)
    unsure = "Actually, I'm not sure he really got to explain."
    result = chat.say(
        unsure,
        understood(
            unsure,
            topics=["formal_warning"],
            facts=[
                fact(
                    EXPLAIN, "yes", "not sure he really got to explain", turn=1,
                    basis="inferred", confidence="low",
                )
            ],
        ),
        response(SAFE, []),
    )  # fmt: skip
    assert chat.memory.coverage(EXPLAIN) == "answered_uncertain"
    assert EXPLAIN not in evaluation(result).facts.conversational
    assert "opportunity to explain" not in result.reply


def test_the_servers_question_is_asked_once_wherever_the_reply_put_it(
    artifacts: Artifacts,
) -> None:
    """Found in the coverage pass: the model asked the question mid-reply and the server added it
    at the end: the same question twice in one reply."""
    chat = Remembering(artifacts)
    result = chat.say(
        WARN,
        understood(WARN, topics=["formal_warning"], actions=[("opt-warning", "a formal warning")]),
        response(f"{SAFE} Could you tell me whether he got to explain? It matters here.", ["q1"]),
    )
    assert result.reply == f"{SAFE} It matters here. {EXPLAIN_QUESTION}"


def test_the_model_never_asks_last_turns_unanswered_question_again(artifacts: Artifacts) -> None:
    """Found in the coverage pass: the server didn't ask the unanswered question again at once,
    and the model copied it into its own reply."""
    chat = Remembering(artifacts)
    warning(chat)
    message = "How long does this usually take?"
    data = understood(
        message, topics=["formal_warning"], actions=[("opt-warning", "a formal warning")], turn=0
    )
    data["previous_question_answer"] = "not_answered"
    result = chat.say(message, data, response(f"{SAFE} {EXPLAIN_QUESTION}", []))
    assert result.reply == SAFE


def test_an_approximate_answer_covers_its_question_only_as_rough(artifacts: Artifacts) -> None:
    """ "Approximate" is about the value's precision, not how directly it was said: the question is
    covered (never asked as if unanswered), the value is never noted or trusted."""
    chat = Remembering(artifacts)
    result = narrated(chat, basis="approximate")
    assert chat.memory.said[EXPLAIN].certainty == "rough"
    assert chat.memory.coverage(EXPLAIN) == "answered_uncertain"
    facts = evaluation(result).facts
    assert EXPLAIN not in facts.conversational and EXPLAIN not in facts.engine
    assert "opportunity to explain" not in result.reply
