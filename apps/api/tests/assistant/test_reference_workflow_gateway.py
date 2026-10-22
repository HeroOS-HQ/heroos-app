"""M2-NEW-08 at the gateway: greetings, "what if" decisions, and what a reply may never claim.

- A greeting ("Hi Hannah") is answered with no model request: nothing to
  understand yet, and nothing is evaluated or stored as a fact.
- A decision asked about hypothetically is evaluated, never recorded as the
  employer's intention: the founder's own "what if" words decide, whatever the
  model read; "I want to..." is an intention.
- A reply never claims a formal step only the employer takes in the Case ("I
  started the investigation", "HeroOS selected the pathway") and never treats
  a serious concern as a finding ("this sounds like serious misconduct").
  Saying what the employer recorded stays allowed.
- The fixed instructions say the Case's position is read-only.
"""

import json
from typing import Any

import pytest

from app.assistant.gateway.catalog import routing_catalog
from app.assistant.gateway.prompts import RESPONSE_INSTRUCTION, UNDERSTANDING_INSTRUCTION
from app.assistant.gateway.proposals import check_evidence, hypothetical, parse_understanding
from app.assistant.gateway.service import GREETING, is_greeting
from app.assistant.response_safety import gateway_problem
from app.knowledge.bundle import KnowledgeBundle
from tests.fixtures.gateway import understanding

MESSAGES = ["One of my staff has been absent for three days.", "What if I dismissed them?"]


@pytest.mark.parametrize(
    "message",
    ["Hi", "hi hannah", "Hello there!", "Hey HeroOS", "Good morning", "Salam", "Hi Sarah",
     "hello, how are you?", "Hi again"],
)  # fmt: skip
def test_a_greeting_is_only_a_greeting(message: str) -> None:
    assert is_greeting(message)


@pytest.mark.parametrize(
    "message",
    [
        "Hi, one of my employees hasn't come in for three days.",
        "Hello, can I dismiss someone today?",
        "hi there I need help with a warning",
        "Thanks",
        "",
        "Good morning. My staff member stole money.",
    ],
)
def test_a_situation_is_never_a_greeting(message: str) -> None:
    assert not is_greeting(message)


def test_the_greeting_reply_asks_what_hr_can_help_with() -> None:
    assert GREETING.startswith("Hi! What can HR help you with today?")


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        ("What if I dismissed them", True),
        ("hypothetically, could we suspend him", True),
        ("In theory, could I deduct the cost", True),
        ("Suppose I gave a final warning", True),
        ("I want to dismiss them", False),
        ("Can I fire her today", False),
        ("Take the repair cost from his salary", False),
    ],
)
def test_hypothetical_words(words: str, expected: bool) -> None:
    assert hypothetical(words) is expected


def _actions(*items: tuple[str, int, str]) -> list[dict[str, Any]]:
    return [{"action": a, "source_turn": t, "support_excerpt": w} for a, t, w in items]


def test_a_what_if_is_never_an_intention_whatever_the_model_read(bundle: KnowledgeBundle) -> None:
    data = understanding(topics=["dismissal_without_notice"])
    # The model lists a "what if" as requested: the founder's own words make it hypothetical.
    data["requested_actions"] = _actions(("opt-dismissal", 1, "What if I dismissed them"))
    proposal = parse_understanding(json.dumps(data), routing_catalog(bundle), current_turn=1)
    checked, dropped = check_evidence(proposal, routing_catalog(bundle), MESSAGES, "")
    assert dropped == 0
    assert checked.actions == ()
    assert [a.action for a in checked.hypothetical] == ["opt-dismissal"]


def test_hypothetical_actions_need_the_founders_words_and_an_intention_wins(
    bundle: KnowledgeBundle,
) -> None:
    messages = [*MESSAGES, "Actually I want to dismiss them."]
    data = understanding(topics=["dismissal_without_notice"])
    data["hypothetical_actions"] = _actions(
        ("opt-dismissal", 1, "What if I dismissed them"),
        ("opt-deduction", 1, "made-up words"),  # not the founder's: dropped
    )
    data["requested_actions"] = _actions(("opt-dismissal", 2, "I want to dismiss them"))
    proposal = parse_understanding(json.dumps(data), routing_catalog(bundle), current_turn=2)
    checked, _ = check_evidence(proposal, routing_catalog(bundle), messages, "")
    assert [a.action for a in checked.actions] == ["opt-dismissal"]
    assert checked.hypothetical == ()


@pytest.mark.parametrize(
    "reply",
    [
        "I've started the investigation for you.",
        "I completed the stage, so you can move on.",
        "HeroOS selected the serious misconduct pathway.",
        "I have approved the dismissal.",
        "HeroOS has chosen the pathway for this case.",
    ],
)
def test_a_reply_never_claims_a_formal_step(reply: str) -> None:
    assert gateway_problem(reply) == "action_claim"


@pytest.mark.parametrize(
    "reply",
    [
        "This sounds like serious misconduct.",
        "What he did amounts to gross misconduct.",
        "Misconduct has been proven here.",
        "The conduct constitutes misconduct.",
    ],
)
def test_a_serious_concern_is_never_a_finding(reply: str) -> None:
    assert gateway_problem(reply) == "misconduct_finding"


@pytest.mark.parametrize(
    "reply",
    [
        "Your company has recorded the serious misconduct pathway. HeroOS didn't classify it.",
        "Your investigation stage is still in progress.",
        "The dismissal is held for Expert Review, but you can continue the investigation.",
        "Whether this amounts to misconduct is your judgement after a fair investigation.",
        "This is not necessarily misconduct: a concern isn't a finding.",
        "I can't start a stage for you: you do that in your case.",
        "You still need the employee-response step before HeroOS can evaluate that action.",
    ],
)
def test_saying_what_the_employer_recorded_stays_allowed(reply: str) -> None:
    assert gateway_problem(reply) is None


def test_the_instructions_keep_the_case_read_only_and_hypotheticals_apart() -> None:
    assert "case_progress" in RESPONSE_INSTRUCTION
    assert "read-only and authoritative" in RESPONSE_INSTRUCTION
    assert "never say you or HeroOS chose a pathway" in RESPONSE_INSTRUCTION
    assert '"hypothetical_actions"' in UNDERSTANDING_INSTRUCTION
    assert "never in requested_actions" in UNDERSTANDING_INSTRUCTION
