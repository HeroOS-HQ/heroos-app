"""A conversation's status, projected deterministically: never one enum for everything.

```text
status
├── lifecycle        the Case's: in_progress, or paused for a whole-matter hold
├── workflow         the Case's workflow (key and title)
├── attention
│   ├── needs_information   the latest turn's checks need an answer (or the jurisdiction does)
│   ├── jurisdiction        needs_confirmation: jurisdiction-specific guidance waits for it
│   └── expert_review       active, its scope (a decision or the matter) and the decisions
├── checks           ready / unavailable / not_applicable (technical; never a lifecycle)
└── latest_outcome   the last outcome shown (guidance, warning, block, expert_review,
                     unavailable, none); never the Case's lifecycle
```

Each dimension comes from its own authoritative source: the Case's intake
evaluation (lifecycle), the active reviews (``checkpoint.Reviews``), the latest
turn's evaluation record (needs information), the Case's intake and the latest
turn's evaluation (jurisdiction), the runtime as it is now (checks) and the
last HeroOS message (latest outcome). An action-level review never pauses the
Case: the investigation goes on while, say, a dismissal without notice waits
for Expert Review. There is no closed, resolved, dismissed or approved
lifecycle, and nothing is inferred from a polite reply.

Only a whole-matter hold pauses the Case: the intake's specialist-review hold
(an escalation, a high-risk screening, an employee under another or an
unsupported jurisdiction), which nothing in the product releases. A
jurisdiction that needs confirming (unconfirmed, "Not sure", a Case
confirmation the Blueprint has since outdated, a conflict in the founder's
words) is attention, not lifecycle: what depends on the jurisdiction waits
(the structured stages, every one of which belongs to one jurisdiction's
programme, and every jurisdiction-specific decision), while the shared
guidance the approved runtime marks shared continues. The employer lifts it
by confirming one answer.

Whether HeroOS's Expert Review *service* is available is a current capability
(``expert_review_service_available``), never read from a historical record:
an old record's ``service_available`` stays what was true then.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Literal, cast

from app.conversations.checkpoint import Reviews

Lifecycle = Literal["in_progress", "paused"]
JurisdictionAttention = Literal["needs_confirmation"]
Checks = Literal["ready", "unavailable", "not_applicable"]
LatestOutcome = Literal["guidance", "warning", "block", "expert_review", "unavailable", "none"]
ReviewScope = Literal["action", "matter"]
OUTCOMES: Final = ("guidance", "warning", "block", "expert_review", "unavailable")
# The intake's and the evaluation's states in which jurisdiction-specific guidance waits.
UNCONFIRMED: Final = frozenset({
    "company_unconfirmed", "case_not_sure", "case_confirmation_outdated", "conversation_conflict",
})  # fmt: skip
# A decision whose title the current runtime doesn't know (it is never shown by id).
UNNAMED_DECISION: Final = "A decision you asked about"


def expert_review_service_available() -> bool:
    """HeroOS can take an Expert Review request now (M2-NEW-09 adds the service; not yet)."""
    return False


@dataclass(frozen=True, slots=True)
class ExpertReview:
    active: bool
    scope: ReviewScope | None
    # The decisions it holds, by their titles (never an option id).
    actions: tuple[str, ...]
    # Current capability, not a historical record's.
    service_available: bool


@dataclass(frozen=True, slots=True)
class ConversationStatus:
    lifecycle: Lifecycle | None
    workflow: str | None
    workflow_title: str | None
    needs_information: bool
    jurisdiction: JurisdictionAttention | None
    expert_review: ExpertReview
    checks: Checks
    latest_outcome: LatestOutcome


def project(
    *,
    case_hold: bool | None,
    jurisdiction_states: Iterable[str | None],
    workflow: str | None,
    workflow_title: str | None,
    reviews: Reviews,
    latest_record: Mapping[str, object] | None,
    latest_outcome: str | None,
    checks: Checks,
    action_titles: Mapping[str, str],
) -> ConversationStatus:
    """``case_hold``: the attached Case's intake holds the whole matter (None: no Case).

    ``jurisdiction_states``: the Case's intake jurisdiction status and the latest
    turn's evaluation jurisdiction state, whichever there are.
    """
    lifecycle: Lifecycle | None = None if case_hold is None else (
        "paused" if case_hold else "in_progress"
    )  # fmt: skip
    missing = None if latest_record is None else latest_record.get("missing")
    outcome: LatestOutcome = (
        cast(LatestOutcome, latest_outcome) if latest_outcome in OUTCOMES else "none"
    )
    jurisdiction: JurisdictionAttention | None = (
        "needs_confirmation" if any(s in UNCONFIRMED for s in jurisdiction_states) else None
    )
    scope: ReviewScope | None = (
        "matter" if reviews.matter else "action" if reviews.actions else None
    )
    return ConversationStatus(
        lifecycle=lifecycle,
        workflow=workflow,
        workflow_title=workflow_title,
        needs_information=(isinstance(missing, list) and bool(missing)) or jurisdiction is not None,
        jurisdiction=jurisdiction,
        expert_review=ExpertReview(
            active=scope is not None,
            scope=scope,
            actions=tuple(
                dict.fromkeys(action_titles.get(a, UNNAMED_DECISION) for a in reviews.actions)
            ),
            service_available=expert_review_service_available(),
        ),
        checks=checks,
        latest_outcome=outcome,
    )
