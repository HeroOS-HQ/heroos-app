"""Validation findings: one record per problem, with a fixed code and a severity.

Severities, from least to most serious:

- ``INFO``: recorded, nothing to do (e.g. a known title variant);
- ``WARNING``: stale or tidy-up metadata that doesn't change the runtime;
- ``REVIEW_REQUIRED``: a person must decide; the runtime stays conservative;
- ``QUARANTINED``: the affected automatic route is withheld from the runtime;
- ``FATAL``: the bundle is invalid and isn't written.

A finding's id is derived from what it is about, never from its position, so
an unrelated new finding never renames another one.
"""

import re
from dataclasses import dataclass, field
from typing import Final

SEVERITY_ORDER: Final = ("INFO", "WARNING", "REVIEW_REQUIRED", "QUARANTINED", "FATAL")
_SLUG: Final = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class Ref:
    source_id: str
    location: str
    content_sha256: str

    def data(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "location": self.location,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    severity: str
    subject_kind: str
    subject_id: str
    check: str
    detail: str
    refs: tuple[Ref, ...] = ()

    @property
    def id(self) -> str:
        raw = f"{self.code}.{self.subject_kind}.{self.subject_id}.{self.check}"
        return _SLUG.sub("-", raw)[:80]

    @property
    def subject_slug(self) -> str:
        """The subject as an id (a rule number "14" becomes "rule-14")."""
        slug = _SLUG.sub("-", self.subject_id)
        if not slug[:1].isalpha():
            slug = f"{self.subject_kind}-{slug}"
        return slug[:80]

    def data(self) -> dict[str, object]:
        return {
            "id": self.id,
            "code": self.code,
            "severity": self.severity,
            "subject": {"kind": self.subject_kind, "id": self.subject_slug},
            "detail": self.detail[:600],
            "refs": [r.data() for r in self.refs],
        }


@dataclass(slots=True)
class Findings:
    items: list[Finding] = field(default_factory=list)

    def add(
        self,
        code: str,
        severity: str,
        subject_kind: str,
        subject_id: str,
        check: str,
        detail: str,
        refs: tuple[Ref, ...] = (),
    ) -> Finding:
        assert severity in SEVERITY_ORDER, severity
        finding = Finding(code, severity, subject_kind, subject_id, check, detail, refs)
        if all(f.id != finding.id for f in self.items):
            self.items.append(finding)
        return next(f for f in self.items if f.id == finding.id)

    def sorted(self) -> list[Finding]:
        return sorted(
            self.items,
            key=lambda f: (-SEVERITY_ORDER.index(f.severity), f.code, f.subject_id, f.check),
        )

    def fatal(self) -> list[Finding]:
        return [f for f in self.items if f.severity == "FATAL"]

    def counts(self) -> dict[str, int]:
        return {s: sum(1 for f in self.items if f.severity == s) for s in SEVERITY_ORDER}
