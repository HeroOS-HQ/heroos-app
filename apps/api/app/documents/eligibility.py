"""Whether a template may be previewed in a Case now (M2-04C): fail closed, server-side.

A template is available only when every one of these holds, checked in this
order (the first that fails is the reason):

1. workflow rules are installed (``rules_not_installed``);
2. the Case isn't on hold for specialist review and has no recorded
   escalation (``case_held``);
3. nothing stops the Case moving on: its jurisdiction is confirmed, the intake
   is recorded with a cleared screening, the rules cover the jurisdiction and
   serve the version the Case started under, and the workflow isn't closed
   (``case_not_ready``);
4. the template is offered in the Case's jurisdiction (``not_for_jurisdiction``);
5. it doesn't need a specialist's review first: no such review exists in
   HeroOS yet, so those templates are never offered (``specialist_review_required``);
6. the stage in progress is one the template is bound to (``not_at_this_stage``);
7. its precondition is definitely met: an unanswered or "Not sure" input
   never counts (``requirement_not_met``, ``requirement_unknown``).

Inputs are the progression evaluation (rules, intake gate, position) and the
Case's answers. Nothing here reads an employer decision record: a record can
never make a template available. Pure.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from app.documents.bundle import Template
from app.workflows.conditions import Tri
from app.workflows.progression import predicates
from app.workflows.progression.engine import ProgressionEvaluation

Reason = Literal[
    "rules_not_installed",
    "case_held",
    "case_not_ready",
    "not_for_jurisdiction",
    "specialist_review_required",
    "not_at_this_stage",
    "requirement_not_met",
    "requirement_unknown",
]
REASONS: Final = (
    "rules_not_installed",
    "case_held",
    "case_not_ready",
    "not_for_jurisdiction",
    "specialist_review_required",
    "not_at_this_stage",
    "requirement_not_met",
    "requirement_unknown",
)


@dataclass(frozen=True, slots=True)
class Availability:
    template: Template
    reason: Reason | None

    @property
    def available(self) -> bool:
        return self.reason is None


def stage_in_progress(progression: ProgressionEvaluation) -> str | None:
    """The stage of the current pathway that is in progress, if any."""
    return next((s.key for s, status in progression.stages if status == "in_progress"), None)


def availability(
    template: Template,
    *,
    jurisdiction: str | None,
    progression: ProgressionEvaluation | None,
    answers: Mapping[str, object],
) -> Availability:
    """Whether ``template`` may be previewed now, and if not, the first reason why."""

    def refused(reason: Reason) -> Availability:
        return Availability(template, reason)

    if progression is None or progression.bundle is None:
        return refused("rules_not_installed")
    if progression.gate == "case_held" or progression.state.escalated:
        return refused("case_held")
    if progression.gate is not None or jurisdiction is None:
        return refused("case_not_ready")
    binding = template.jurisdictions.get(jurisdiction)
    if binding is None:
        return refused("not_for_jurisdiction")
    if template.review != "employer":
        return refused("specialist_review_required")
    stage = stage_in_progress(progression)
    if stage is None or stage not in binding.stages:
        return refused("not_at_this_stage")
    if binding.require is not None:
        context = predicates.Context(answers, frozenset(progression.completed))
        truth = predicates.evaluate(binding.require, context)
        if truth is Tri.FALSE:
            return refused("requirement_not_met")
        if truth is not Tri.TRUE:
            return refused("requirement_unknown")
    return Availability(template, None)
