"""A stored progress event as the read path sees it (``workflow_progress_events``)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.workflows.progression.engine import Decision, EventKind, ProgressEvent


@dataclass(frozen=True, slots=True)
class StoredEvent:
    id: UUID
    kind: EventKind
    transition: str
    pathway: str | None
    previous_pathway: str | None
    stage: str | None
    decision: Decision
    # Every result of the decision: codes, keys and outcomes only.
    reasons: Sequence[Mapping[str, object]]
    acknowledged: Sequence[str]
    revision: int
    request_key: UUID | None
    actor_user_id: UUID
    bundle_version: str
    occurred_at: datetime

    def engine(self) -> ProgressEvent:
        return ProgressEvent(
            kind=self.kind,
            transition=self.transition,
            pathway=self.pathway,
            stage=self.stage,
            decision=self.decision,
            revision=self.revision,
            bundle_version=self.bundle_version,
        )
