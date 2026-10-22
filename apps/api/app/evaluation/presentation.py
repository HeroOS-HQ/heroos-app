"""What the founder sees of an evaluation: the outcome card, the safe next step and fixed replies.

The **outcome card** is composed here, by the server, from the deterministic
evaluation: its kind (Guidance, Warning, Block, Expert Review; or "checks
unavailable", a technical state that is never an HR outcome), a title, a
message and one line per requested step. Business and legal wording comes
from approved content (option and Condition titles, Condition guidance, rule
bundle messages); only generic platform wording lives in this code. A
Condition whose legal basis isn't confirmed is always qualified as a
practical caution, never stated as law.

The **safe next step** is an intent the evaluator chose (``NextStep``) with
fixed wording here; the AI may rephrase it, and its phrasing is replaced by
the fixed one if it fails a check. It is never a sanction.

The **AI view** (``outcome_view``) is the minimized result the response phase
may phrase: the state, each step's result in words, the approved cautions,
what is still needed and the safe next step, with the rule that it can't be
changed. ``outcome_contradiction`` reads the reply for the clear ways a reply
could undo it ("you can go ahead and dismiss them" under a Block, "no
specialist review is needed" under Expert Review, "nothing to address" under a
Warning). ``fallback_reply`` keeps a Block, a Warning or an Expert Review in
place when the model fails or is replaced: AI availability never weakens a
deterministic result.

Expert Review is a requirement, not a service: nothing here says a review was
requested, assigned, submitted or will respond (M2-NEW-09 owns that).
"""

import re
from dataclasses import dataclass
from typing import Final, Literal

from app.evaluation.model import (
    PRESENTATIONS,
    ActionEvaluation,
    ConversationEvaluation,
    MissingRequirement,
    NextStep,
    Note,
    Presentation,
    Value,
)
from app.evaluation.snapshot import FactSchema

OutcomeKind = Literal["guidance", "warning", "block", "expert_review", "unavailable"]
JURISDICTION_NAMES: Final = {"uae_federal": "UAE Federal", "difc": "DIFC"}

TITLES: Final[dict[OutcomeKind, str]] = {
    "guidance": "Guidance",
    "warning": "Warning",
    "block": "Not yet",
    "expert_review": "Expert Review",
    "unavailable": "Checks unavailable",
}
NEXT_STEPS: Final[dict[NextStep, str]] = {
    "continue_methodology": (
        "Keep working through the approved steps, starting with the facts of what happened."
    ),
    "answer_question": "Answer HeroOS's question so it can apply the approved guidance.",
    "establish_prerequisite": "Establish what's still needed before you take this step.",
    "consider_caution": "Consider the caution before you decide anything.",
    "obtain_specialist_review": (
        "Keep documenting and following the approved process, and get specialist review before "
        "the step that's held."
    ),
    "confirm_jurisdiction": "Confirm which employment jurisdiction applies to this employee.",
    "choose_matter": (
        "Choose which matter to work through first: HeroOS takes one matter at a time."
    ),
    "seek_specialist_advice": "Speak to a qualified HR or employment specialist about this.",
    "complete_case_step": (
        "Complete what's still needed through the case's own workflow stages; HeroOS reads it "
        "from the case, not from the chat."
    ),
}
STEP_RESULTS: Final[dict[str, str]] = {
    "escalate": "needs specialist review before it is taken",
    "block": "can't safely proceed yet",
    "unknown": "not confirmed yet: HeroOS can't check all of its safeguards",
    "warn": "a caution applies",
    "allow": "no HeroOS rule prevents it on what's established so far (still your decision)",
}
PROVISIONAL: Final = "A practical caution: its legal basis isn't confirmed."
UNAVAILABLE_MESSAGE: Final = (
    "HeroOS's deterministic checks aren't available right now, so this reply can't say whether "
    "any step can proceed. Nothing is decided here."
)
REVIEW_NOTE: Final = (
    "HeroOS can't arrange a specialist review yet; you can keep working through the approved "
    "steps meanwhile."
)
UNSUPPORTED_HR: Final = (
    "This needs a qualified HR or employment specialist: HeroOS's approved guidance doesn't "
    "cover it."
)
PROVIDER_NOTE: Final = "HeroOS couldn't put together a fuller reply just now."
# M2-NEW-08: a prerequisite only the Case's formal record establishes.
CASE_STEP_NOTE: Final = (
    "This depends on your case's own record: what your company has completed in its workflow "
    "stages and checklists. What's said in the chat doesn't change it."
)


@dataclass(frozen=True, slots=True)
class OutcomeItem:
    kind: Presentation
    text: str


@dataclass(frozen=True, slots=True)
class Outcome:
    kind: OutcomeKind
    title: str
    message: str
    items: tuple[OutcomeItem, ...] = ()


def display(schema: FactSchema | None, value: Value) -> str:
    """A canonical value as the founder would say it."""
    if schema is not None:
        label = next((o.label for o in schema.options if o.value == value), None)
        if label is not None:
            return label
    return str(value).replace("_", " ")


QUESTION_WORDS: Final = frozenset({"whether", "what", "which", "how", "when", "who", "where", "if"})


def requirement_question(
    requirement: MissingRequirement,
    *,
    schema: FactSchema | None,
    action_titles: dict[str, str],
    jurisdiction: str | None,
    prompt: str | None = None,
) -> str:
    """A plain, server-owned question for one missing requirement.

    ``prompt``: the definition's own question for the fact, when it has one (natural English,
    found live: the label assembled into "Could you tell me more about this: whether ...?"
    read as a form). A confirmation is then the same direct question again, saying why, and
    the founder's answer is parsed against the question itself (``app.evaluation.facts``): a
    "yes" means yes to what was asked, never "yes, that's right" to a reading. A fact with no
    question of its own is confirmed as before ("is it <value>?").
    """
    if requirement.kind == "insistence":
        held = [action_titles[a] for a in requirement.actions if a in action_titles]
        target = held[0].lower() if held else "this step"
        return f"Knowing this caution, do you still intend to go ahead with {target}?"
    if requirement.kind == "jurisdiction":
        name = JURISDICTION_NAMES.get(jurisdiction or "", "")
        return (
            f"Is this employee employed under your company's confirmed employment jurisdiction "
            f"({name})?"
            if name
            else "Which legal entity employs this person?"
        )
    if prompt is not None:
        if requirement.kind == "confirmation":
            return f"So I can rely on it for this step: {prompt[:1].lower() + prompt[1:]}"
        return prompt
    label = requirement.label.rstrip(".")
    lowered = label[:1].lower() + label[1:]
    if requirement.kind == "confirmation" and requirement.candidate is not None:
        # No question of its own: "yes" confirms the server's canonical reading.
        return f"Just to confirm: {lowered}: {display(schema, requirement.candidate)}?"
    if label.split(" ", 1)[0].lower() in QUESTION_WORDS:
        return f"Could you tell me {lowered}?"
    return f"Could you tell me about {lowered}?"


def _note_text(note: Note) -> str:
    text = " ".join(t.strip() for t in note.text if t.strip())
    sentence = f"{note.title}." if not text else f"{note.title}: {text}"
    return f"{sentence} {PROVISIONAL}" if note.provisional else sentence


def _still_needed(missing: tuple[MissingRequirement, ...], keys: tuple[str, ...]) -> list[str]:
    labels = [m.label for m in missing if m.key in keys and m.kind in ("fact", "confirmation")]
    return list(dict.fromkeys(labels))


def _action_message(
    action: ActionEvaluation, evaluation: ConversationEvaluation, company_confirmed: bool
) -> str:
    title = action.title
    if action.disposition == "escalate":
        return f"Specialist review is required before {title.lower()}. {REVIEW_NOTE}"
    parts: list[str] = []
    if action.disposition == "block":
        parts.append(f"Don't take this step yet: {title.lower()} can't safely proceed yet.")
        if "jurisdiction" in action.missing:
            parts.append(
                "HeroOS needs to confirm which employment jurisdiction applies to this employee."
                if company_confirmed
                else "Your company's employment jurisdiction needs to be confirmed in its Company "
                "Blueprint first."
            )
        if any(r.startswith("not_available:") for r in action.reasons):
            parts.append(
                f"{title} isn't available for your company under HeroOS's approved guidance."
            )
        if action.next_step == "complete_case_step":
            parts.append(CASE_STEP_NOTE)
    elif action.disposition == "unknown":
        parts.append(
            f"HeroOS can't yet confirm that {title.lower()} is clear of the approved safeguards, "
            "so treat it as not cleared."
        )
    elif action.disposition == "warn":
        parts.append(f"A caution applies to {title.lower()}.")
    else:
        parts.append(
            f"No HeroOS rule prevents {title.lower()} on what's established so far. It's still "
            "your decision, after the required steps."
        )
    parts += [_note_text(n) for n in action.notes]
    needed = _still_needed(evaluation.missing, action.missing)
    if needed:
        parts.append("Still needed: " + "; ".join(n.rstrip(".") for n in needed) + ".")
    return " ".join(parts)


def outcome(
    evaluation: ConversationEvaluation, *, company_confirmed: bool = True
) -> Outcome | None:
    """The outcome card for this turn; None when there is no outcome to show."""
    if not evaluation.ready:
        return Outcome("unavailable", TITLES["unavailable"], UNAVAILABLE_MESSAGE)
    if evaluation.matter == "unsupported_hr":
        return Outcome("expert_review", TITLES["expert_review"], UNSUPPORTED_HR)
    presentation = evaluation.presentation
    if presentation is None:
        return None
    items = tuple(
        OutcomeItem(PRESENTATIONS[a.disposition], f"{a.title}: {STEP_RESULTS[a.disposition]}")
        for a in evaluation.actions
    )
    # The strongest step speaks first; the others keep their own line.
    ranked = sorted(
        evaluation.actions,
        key=lambda a: ("allow", "warn", "unknown", "block", "escalate").index(a.disposition),
        reverse=True,
    )
    lead = ranked[0] if ranked else None
    parts: list[str] = []
    if lead is not None and PRESENTATIONS[lead.disposition] == presentation:
        parts.append(_action_message(lead, evaluation, company_confirmed))
    for caution in evaluation.cautions:
        if not any(caution.note in a.notes for a in evaluation.actions):
            parts.append(_note_text(caution.note))
    if presentation == "expert_review" and not parts:
        parts.append(
            "Specialist review is needed: this employee may be employed under a different "
            f"jurisdiction from your company's confirmed one. {REVIEW_NOTE}"
        )
    if not parts:
        parts.append("HeroOS's approved guidance applies here. The decision stays with you.")
    title = TITLES[presentation]
    if presentation == "block" and lead is not None and lead.disposition == "block":
        title = f"Not yet: {lead.title}"
    return Outcome(presentation, title, " ".join(parts), items if len(items) > 1 else ())


def next_step_text(evaluation: ConversationEvaluation) -> str | None:
    return None if evaluation.next_step is None else NEXT_STEPS[evaluation.next_step]


MEANING: Final[dict[Presentation, str]] = {
    "guidance": (
        "approved guidance may continue; this never means an action is approved, lawful or "
        "recommended"
    ),
    "warning": "a caution applies; the founder remains free to continue",
    "block": "the step named below can't safely proceed yet; the conversation continues",
    "expert_review": (
        "the step named below needs specialist review before it is taken; HeroOS has no review "
        "service yet, so never say a review was requested, assigned or will respond"
    ),
}
OUTCOME_RULES: Final = (
    "HeroOS's deterministic checks decided this outcome, not you. Phrase it naturally in your "
    "reply; never soften, remove or contradict it, and never add another outcome.",
    "Never say a step that can't proceed or needs specialist review may go ahead, and never say "
    "no specialist review is needed.",
    "Keep your safe_next_step to the same meaning as the safe next step given here.",
)


def outcome_view(
    evaluation: ConversationEvaluation, card: Outcome | None
) -> tuple[dict[str, object] | None, tuple[str, ...]]:
    """The minimized result the response phase may phrase, and its texts (for grounding)."""
    if card is None:
        return None, ()
    if card.kind == "unavailable":
        view: dict[str, object] = {
            "state": "checks_unavailable",
            "meaning": (
                "HeroOS's deterministic checks aren't available: say nothing about whether any "
                "step can proceed, and never present one as allowed"
            ),
        }
        return view, ()
    presentation: Presentation = card.kind  # not "unavailable" (returned above)
    steps = [
        {
            "step": a.title,
            "result": STEP_RESULTS[a.disposition],
            # A "what if": explain it as such, never as what the employer intends.
            "asked": "hypothetically" if a.hypothetical else "as the employer's intention",
        }
        for a in evaluation.actions
    ]
    cautions = [
        {
            "title": c.note.title,
            "text": list(c.note.text),
            "legal_basis": "not confirmed: present only as a practical caution, never as the law"
            if c.note.provisional
            else "confirmed",
        }
        for c in evaluation.cautions
    ]
    needed = [m.label for m in evaluation.missing if m.kind in ("fact", "confirmation")]
    step = next_step_text(evaluation)
    view = {
        "state": presentation,
        "meaning": MEANING[presentation],
        "summary": card.message,
        "steps": steps,
        "cautions": cautions,
        "still_needed": needed,
        "safe_next_step": step,
        "rules": list(OUTCOME_RULES),
    }
    texts = (
        card.message,
        *(a.title for a in evaluation.actions),
        *(t for c in evaluation.cautions for t in (c.note.title, *c.note.text)),
        *needed,
        *([step] if step else []),
    )
    return view, texts


# --- the contradiction check -------------------------------------------------------------

_SANCTIONS: Final = (
    r"(?:dismiss\w*|terminat\w*|fir(?:e|ing)|sack\w*|suspen\w*|deduct\w*|dock\w*|warning"
    r"|penalt\w*)"
)
_GO_AHEAD: Final = re.compile(
    r"\b(?:you\s+can|you\s+may|you(?:'re|\s+are)\s+free\s+to|feel\s+free\s+to|it(?:'s|\s+is)\s+"
    r"(?:fine|ok(?:ay)?|safe)\s+to)\s+(?:now\s+)?(?:go\s+ahead|proceed|move\s+forward)"
    rf"(?:\s+and\s+\w+|\s+with\s+(?:the\s+|a\s+|your\s+)?{_SANCTIONS}|\s*[.!,]|\s*$)",
    re.IGNORECASE,
)
_NO_REVIEW: Final = (
    re.compile(
        r"\bno\s+(?:need\s+for\s+(?:an?\s+)?)?(?:specialist|expert|legal)\s+(?:review|advice|input)"
        r"(?:\s+is\s+(?:needed|required|necessary))?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:don't|do\s+not|won't|will\s+not|doesn't|does\s+not|wouldn't|would\s+not)\s+need"
        r"\s+(?:an?\s+|any\s+)?(?:specialist|expert|legal)\s+(?:review|advice|input|sign-off)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:specialist|expert|legal)\s+review\s+(?:isn't|is\s+not|won't\s+be|will\s+not\s+be)"
        r"\s+(?:needed|required|necessary)",
        re.IGNORECASE,
    ),
)
_ALL_CLEAR: Final = (
    re.compile(
        r"\bnothing\s+(?:you\s+need\s+|for\s+you\s+)?to\s+(?:address|worry\s+about|consider)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:there(?:'s|\s+is|\s+are)\s+)?no\s+(?:cautions?|concerns?|issues?|risks?)\s+"
        r"(?:apply|applies|here|at\s+all|to\s+(?:address|consider))",
        re.IGNORECASE,
    ),
    re.compile(r"\byou(?:'re|\s+are)\s+(?:all\s+)?(?:clear|good\s+to\s+go)\b", re.IGNORECASE),
)

ContradictionCheck = Literal["contradicts_hold", "contradicts_review", "contradicts_caution"]


def outcome_contradiction(
    texts: list[str], evaluation: ConversationEvaluation
) -> ContradictionCheck | None:
    """The first way the reply undoes the deterministic outcome, or None."""
    held = any(a.disposition in ("block", "escalate", "unknown") for a in evaluation.actions)
    review = (
        any(r.required for r in evaluation.reviews) or evaluation.presentation == "expert_review"
    )
    caution = evaluation.presentation == "warning" or bool(evaluation.cautions)
    for text in texts:
        if held and _GO_AHEAD.search(text):
            return "contradicts_hold"
        if review and any(p.search(text) for p in _NO_REVIEW):
            return "contradicts_review"
        if caution and any(p.search(text) for p in _ALL_CLEAR):
            return "contradicts_caution"
    return None


def fallback_reply(
    evaluation: ConversationEvaluation,
    card: Outcome | None,
    *,
    lead: str,
    question: str | None,
    provider_note: bool = False,
) -> str:
    """A reply composed only from fixed text and the deterministic result (no model text)."""
    parts = [lead] if lead else []
    if provider_note:
        parts.append(PROVIDER_NOTE)
    if card is not None and card.kind != "unavailable":
        parts.append(card.message)
        parts += [f"{i.text}." for i in card.items]
    if question:
        parts.append(question)
    return " ".join(p.strip() for p in parts if p.strip())
