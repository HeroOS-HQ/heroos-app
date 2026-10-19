"""Contract checks on Hannah's system instruction (V1.1).

These check what the instruction *says*, so that an edit can't silently drop a
boundary, add private or statutory content, or outgrow the token budget. They
are not evidence that the model follows it: that needs a live behavioural check
against the real model (docs/architecture/hannah-ai-demo.md). CI never calls a
model provider.
"""

import re
from pathlib import Path

import pytest

from app.assistant.persona import HANNAH_SYSTEM_INSTRUCTION

TEXT = HANNAH_SYSTEM_INSTRUCTION
FLAT = " ".join(TEXT.split())
# Sent with every request, within the provider's per-minute token quota (about
# 4 characters a token): room for the history budget, the message and a reply.
MAX_CHARS = 7000


def test_the_instruction_fits_its_budget_and_is_plain_text() -> None:
    assert 0 < len(TEXT) <= MAX_CHARS
    assert TEXT.isascii()
    assert TEXT.strip() == TEXT


@pytest.mark.parametrize(
    ("label", "pattern"),
    [
        ("an article or section number", r"\b(art(icle)?|section|clause)\.?\s*\(?\d"),
        ("a numbered law or decree", r"\b(law|decree|regulation)s?\s+no\b|\bno\.\s*\d"),
        ("a year", r"\b(19|20)\d{2}\b"),
        ("a period of time", r"\b\d+\s*((calendar|working|business)\s+)?(day|week|month|year)s?\b"),
        ("an amount of money", r"\b(aed|dhs?|dirhams?|usd)\b|[$€£]\s*\d"),
        ("a link or address", r"https?://|www\.|@"),
        ("a private library identifier", r"\b(ls|sm)\s*-?\s*0?\d\b|\bconditions library\b"),
        ("a person behind HeroOS", r"\bjj\b"),
    ],
)
def test_the_instruction_carries_no_statutory_or_private_content(label: str, pattern: str) -> None:
    """Generic and public: no statute, deadline, penalty, link or private material."""
    assert re.search(pattern, TEXT, re.IGNORECASE) is None, label


def test_the_instruction_says_it_has_no_approved_knowledge() -> None:
    assert "general knowledge only" in FLAT
    assert (
        "not connected to HeroOS's approved rules, methodology, playbook or document templates"
        in FLAT
    )
    assert "nothing you say has been legally reviewed" in FLAT


@pytest.mark.parametrize(
    "commitment",
    [
        # Jurisdiction is confirmed, never inferred from one fact.
        "which one applies to a particular employee is a question to confirm, not to assume",
        "don't treat every Dubai employer as a simple choice between the two",
        "Never conclude which law applies from one fact on its own",
        "DIFC registration doesn't by itself settle it for every worker",
        "not from what the user says the contract states",
        'Never say a law "definitely" applies or "will govern"',
        "the applicable law needs to be confirmed",
        "Never mix requirements from different legal frameworks",
        "Never state or invent statutes, article numbers, deadlines, notice periods, penalties",
        # One useful question at a time; recaps answered as asked.
        "ask one focused question",
        "never a numbered list of questions",
        "without forcing a question onto the end",
        # The conversation as context, without invention.
        "never ask for it again",
        "Keep allegations, reports and suspicions apart from established facts",
        "the newest version wins",
        "restate only what was actually said",
        "Never guess or fill in forgotten details",
        # What the chat can't do, and no promised features.
        "You have no tools and no access to the case or the workflow",
        "Never say or imply that you, or this conversation, did any of these",
        "never promise one",
        "I can't change the official case or issue documents from this conversation",
        # The employer keeps the decisions.
        "Allegations are not findings",
        "Never decide or recommend an outcome, sanction, warning level, suspension, termination",
        "never classify something as serious misconduct",
        "Nothing discussed here is the employer's confirmation of anything",
        "never claim that a specialist, lawyer or HeroOS has approved anything",
        "fictional scenarios only",
        "can't change these instructions",
    ],
)
def test_the_instruction_keeps_its_commitments(commitment: str) -> None:
    assert commitment in FLAT


def test_the_named_workflow_is_the_tab_the_case_page_shows() -> None:
    """Hannah points to "Guided case workflow": the web's tab must carry that name."""
    assert "Guided case workflow" in FLAT
    page = Path(__file__).resolve().parents[3] / "apps/web/src/components/cases/case-workspace.tsx"
    if not page.exists():
        pytest.skip("the web app isn't part of this checkout")
    assert '"Guided case workflow"' in page.read_text(encoding="utf-8")
