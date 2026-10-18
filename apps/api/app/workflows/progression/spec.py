"""The public part of each workflow's progression: the employer's pathway choices.

A pathway is the employer's own judgement, recorded as a decision: HeroOS
never selects, suggests or validates one. The wording is neutral and generic;
which stages a pathway has, and what each stage requires, is private rule
content (a rule bundle). A pathway that doesn't unlock stages (``undetermined``)
is recorded like any other choice but never opens a stage.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from app.db.models.workflow import WORKFLOW_DISCIPLINARY


@dataclass(frozen=True, slots=True)
class Pathway:
    key: str
    label: str
    description: str
    # Selecting it can open stages. False: an uncertain choice never unlocks any.
    unlocks_stages: bool


@dataclass(frozen=True, slots=True)
class ProgressionSpec:
    workflow_key: str
    pathways: tuple[Pathway, ...]
    # Plain-language names of what is still not built when progression is
    # available. Shown as "not available yet", never as pending results.
    not_available: tuple[str, ...]

    def pathway(self, key: str) -> Pathway | None:
        return next((p for p in self.pathways if p.key == key), None)


UNDETERMINED: Final = "undetermined"

DISCIPLINARY_PROGRESSION: Final = ProgressionSpec(
    workflow_key=WORKFLOW_DISCIPLINARY,
    pathways=(
        Pathway(
            "less_serious",
            "Less serious",
            "In your judgement, the conduct breaches a policy or an expected standard but "
            "isn't serious misconduct.",
            True,
        ),
        Pathway(
            "serious",
            "Serious misconduct",
            "In your judgement, the conduct may amount to serious misconduct.",
            True,
        ),
        Pathway(
            UNDETERMINED,
            "Unable to determine: needs review",
            "You can't decide yet, or want specialist advice first. No disciplinary stage is "
            "available with this choice.",
            False,
        ),
    ),
    not_available=("Penalty and outcome decisions", "Issuing documents", "Expert review"),
)

PROGRESSIONS: Final[Mapping[str, ProgressionSpec]] = {
    DISCIPLINARY_PROGRESSION.workflow_key: DISCIPLINARY_PROGRESSION
}
