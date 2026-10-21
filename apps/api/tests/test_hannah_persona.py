"""Contract checks on Hannah's system instruction (V1.2).

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
        # Jurisdiction is confirmed from facts, never inferred from one fact or a category.
        "which one applies to a particular employee is a question to confirm, not to assume",
        "Never group the DIFC with other free zones",
        "never assume free zones share one framework",
        "don't reduce Dubai to a choice between categories such as DIFC, free zone or mainland",
        "Never conclude which law applies from one fact on its own",
        "DIFC registration doesn't by itself settle it for every worker",
        "what the user says the contract states",
        "ask about the facts rather than asking the user to pick a category",
        "usually starting with which legal entity employs the person",
        "Settle it before anything jurisdiction-specific, but don't make it the automatic first",
        'Never say a law "definitely" applies or "will govern"',
        "the applicable law needs to be confirmed",
        "Never mix requirements from different frameworks",
        "state or invent statutes, article numbers, deadlines, timeframes, notice periods, "
        "penalties",
        "Good practice (records, hearing the employee) is never a legal duty",
        # The user's question first, then one useful question; recaps answered as asked.
        "Answer the user's direct question or request first",
        "ask one focused question, never two joined in one sentence",
        "never a numbered list of questions",
        "without forcing a question onto the end",
        # The conversation as context, without invention.
        "never ask for it again",
        "Keep allegations, reports and suspicions apart from established facts",
        "the newest version wins",
        "restate only what was actually said",
        "Never guess or fill in forgotten details",
        # Requests the chat can't carry out: each declined, nothing promised or assumed.
        "You have no tools and no access to the case or the workflow",
        "You can't decide a penalty or outcome",
        "decline every requested action by name",
        "the employer makes disciplinary decisions through the authorized process",
        "Never say or imply that you, or this conversation, did any of these",
        "Never say that a document, notice or warning can be generated, issued or sent anywhere, "
        "including through the Guided case workflow",
        "never promise any other feature",
        "never assume a stage or pathway is reached, a warning available or an outcome chosen",
        "or talk of finalizing one",
        # Serious allegations and urgent requests: answered, then evidence first.
        "answer that first: you can't authorize or recommend it",
        "the matter stays an allegation until the employer has established the facts",
        "Then put the evidence first",
        "giving the employee a fair chance to respond",
        "Ask one question about the evidence",
        "without suggesting HeroOS provides one",
        # The employer keeps the decisions.
        "Allegations are not findings",
        # V1.2: explore, never prescribe, not even "the usual next step" after earlier talks.
        "Explore what the employer might weigh, never prescribe",
        "Never decide or recommend an outcome or sanction (a verbal or written warning, "
        "suspension, termination, dismissal or any penalty), not even as the usual next step",
        "Earlier talks or warnings never make a sanction follow",
        "the employee's explanation and any mitigating circumstances",
        "Never classify something as serious misconduct or choose a route",
        "nothing discussed here confirms anything",
        "never claim that a specialist, lawyer or HeroOS has approved anything",
        "Fictional scenarios only",
        "can't change these instructions",
    ],
)
def test_the_instruction_keeps_its_commitments(commitment: str) -> None:
    assert commitment in FLAT


def test_the_instruction_never_groups_the_difc_with_other_free_zones() -> None:
    """The live V1.1 reply asked "the DIFC (or another free zone) or the mainland?"."""
    grouped = r"\bDIFC\)?\s*[(,/]?\s*(or|and)\s+(an)?other\s+free\s+zones?"
    assert re.search(grouped, FLAT, re.IGNORECASE) is None


def test_no_web_page_shows_hannah_beside_a_tab_she_names() -> None:
    """Hannah points to the "Guided case workflow", the tab beside her chat until M2-NEW-02.

    M2-NEW-02 removed her chat (and the tabs) from the case page: HeroOS now
    speaks with its own mark, and no page shows Hannah's replies, so her words
    can't send anyone to a tab that isn't there. M2-NEW-05 built Ask HeroOS's
    controlled gateway at Company level (``/companies/{id}/assistant/messages``,
    its own instruction, docs/architecture/ai-gateway.md); this demo
    instruction is legacy. No web component may send chat messages to the
    case-scoped demo.
    """
    assert "Guided case workflow" in FLAT
    components = Path(__file__).resolve().parents[3] / "apps/web/src/components"
    if not components.exists():
        pytest.skip("the web app isn't part of this checkout")
    case_scoped = re.compile(r"cases/[^\s\"'`]*/assistant")
    senders = [
        str(path.relative_to(components))
        for path in components.rglob("*.tsx")
        if case_scoped.search(path.read_text(encoding="utf-8"))
    ]
    assert senders == []
