"""The Conditions workbook: every sheet read, each used only for its role.

- **Conditions Library** (operational): every row is validated and
  normalized; only the runtime slice is published, the rest is counted.
- **Reference Data** (operational where an active runtime Condition needs it).
- **Documents**, **Blueprint Fields**, **Legend** (validation): cross-checked
  against the actual templates, the Company Blueprint and the rows.
- **Structural Findings**, **Disciplinary Coverage** (audit only) and **Test
  Company Example** (test only): counted and reported, never runtime advice.

A spreadsheet value is data, never code: an action like "warn (first pass);
block if the employer insists" is matched against fixed patterns into an
``action_policy``; anything else is a ``MALFORMED_ACTION`` finding. The raw
cells are kept verbatim for audit.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from scripts.knowledge.findings import Findings, Ref
from scripts.knowledge.sources import sha256_text
from scripts.xlsx_reader import Sheet, Workbook

CONDITION_COLUMNS: Final = (
    "id", "jurisdiction", "type", "trigger", "title", "guidance", "action", "source",
    "last_reviewed", "citation_status", "enforcement_status", "enforcement_note",
    "shared_across", "blueprint_or_workflow_field", "notes",
)  # fmt: skip
JURISDICTION_CODES: Final = {
    "UAE-FED": "uae_federal",
    "DIFC": "difc",
    "SHARED": "shared",
    "GLOBAL": "global",
}
CONDITION_TYPES: Final = ("precondition", "step_caution", "blocking")
CITATION: Final = ("confirmed", "needs_legal_review")
ENFORCEMENT: Final = ("active", "not_enforced")
CONDITION_ID: Final = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
# The action column's actual shapes. Nothing else is accepted.
_SIMPLE_ACTION: Final = {"warn": "warn", "block": "block", "escalate": "escalate"}
_INSISTS: Final = re.compile(
    r"^(warn|block)\s*\(first pass\);\s*(block|escalate)\s+if\s+the\s+employer\s+insists\b.*$",
    re.IGNORECASE | re.DOTALL,
)
_CONDITIONAL: Final = re.compile(
    r"^(warn|block);\s*(block|escalate)\s+if\s+(.+)$", re.IGNORECASE | re.DOTALL
)
_FACT_TOKEN: Final = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_WORKFLOW_WORD: Final = re.compile(r"^\s*([A-Za-z]+)")


@dataclass(frozen=True, slots=True)
class Row:
    number: int
    cells: dict[str, str]


def sheet_rows(sheet: Sheet, header_row: int = 1) -> tuple[dict[str, str], list[Row]]:
    """(column -> header, data rows as header -> value) of a header-row sheet."""
    rows = sheet.rows()
    header = {col: value.strip() for col, value in rows.get(header_row, {}).items()}
    data = []
    for number in sorted(n for n in rows if n > header_row):
        cells = {header[c]: v for c, v in rows[number].items() if c in header}
        if any(v.strip() for v in cells.values()):
            data.append(Row(number, cells))
    return header, data


def row_ref(source_id: str, sheet: str, row: Row) -> Ref:
    canonical = json.dumps(row.cells, sort_keys=True, ensure_ascii=False)
    return Ref(source_id, f"sheet {sheet} row {row.number}", sha256_text(canonical))


def normalize_action(raw: str) -> tuple[dict[str, object] | None, str | None]:
    """(action_policy, problem). Problem: None, "normalized" or "malformed"."""
    text = raw.strip()
    lowered = text.lower()
    if lowered in _SIMPLE_ACTION:
        return {"initial": _SIMPLE_ACTION[lowered], "follow_up": None}, None
    if lowered == "blocking":
        # "blocking" is a type in the Legend, not an action: the rule blocks.
        return {"initial": "block", "follow_up": None}, "normalized"
    match = _INSISTS.match(text)
    if match is not None:
        return {
            "initial": match.group(1).lower(),
            "follow_up": {
                "action": match.group(2).lower(),
                "when": "employer_insists",
                "clause": text,
            },
        }, None
    match = _CONDITIONAL.match(text)
    if match is not None:
        return {
            "initial": match.group(1).lower(),
            "follow_up": {
                "action": match.group(2).lower(),
                "when": "condition_specific",
                "clause": text,
            },
        }, None
    return None, "malformed"


def derive_workflow(shared_across: str, prefixes: Mapping[str, str]) -> str | None:
    """The playbook a row belongs to: the first playbook its ``shared_across`` names."""
    text = shared_across.strip()
    for prefix, workflow in prefixes.items():
        if text.lower().startswith(prefix.lower()):
            return workflow
    match = _WORKFLOW_WORD.match(text)
    return None if match is None else prefixes.get(match.group(1))


def fact_tokens(row: Row, single_words: frozenset[str]) -> list[str]:
    text = f"{row.cells.get('trigger', '')} {row.cells.get('blueprint_or_workflow_field', '')}"
    tokens = _FACT_TOKEN.findall(text)
    tokens += [w for w in re.findall(r"\b[a-z_]+\b", text) if w in single_words]
    return list(dict.fromkeys(tokens))


@dataclass(slots=True)
class ConditionRow:
    row: Row
    ref: Ref
    id: str
    workflow: str | None
    scope: str | None
    type: str | None
    action_policy: dict[str, object] | None
    citation_status: str | None
    enforcement_status: str | None
    valid: bool
    tokens: list[str]


def read_conditions(
    workbook: Workbook,
    source_id: str,
    sheet_name: str,
    prefixes: Mapping[str, str],
    single_words: frozenset[str],
    findings: Findings,
) -> list[ConditionRow]:
    sheet = workbook.sheet(sheet_name)
    if sheet is None:
        findings.add(
            "MISSING_SOURCE", "FATAL", "sheet", sheet_name, "present", "conditions sheet missing"
        )
        return []
    header, rows = sheet_rows(sheet)
    missing = [c for c in CONDITION_COLUMNS if c not in header.values()]
    if missing:
        findings.add(
            "INVALID_ROW", "FATAL", "sheet", sheet_name, "columns",
            f"missing columns: {', '.join(missing)}",
        )  # fmt: skip
        return []
    seen: dict[str, int] = {}
    out: list[ConditionRow] = []
    for row in rows:
        cells = row.cells
        ref = row_ref(source_id, sheet_name, row)
        condition_id = cells.get("id", "").strip()
        problems: list[str] = []
        if not CONDITION_ID.fullmatch(condition_id):
            problems.append("id")
        if condition_id in seen:
            findings.add(
                "DUPLICATE_ID", "FATAL", "condition", condition_id, f"row-{row.number}",
                f"duplicate Condition id (first on row {seen[condition_id]})", (ref,),
            )  # fmt: skip
        seen.setdefault(condition_id, row.number)
        scope = JURISDICTION_CODES.get(cells.get("jurisdiction", "").strip())
        if scope is None:
            problems.append("jurisdiction")
        kind = cells.get("type", "").strip()
        if kind not in CONDITION_TYPES:
            problems.append("type")
        citation = cells.get("citation_status", "").strip()
        if citation not in CITATION:
            problems.append("citation_status")
        enforcement = cells.get("enforcement_status", "").strip()
        if enforcement not in ENFORCEMENT:
            problems.append("enforcement_status")
        if enforcement == "not_enforced" and not cells.get("enforcement_note", "").strip():
            # The Legend requires the note whenever a row is not enforced.
            problems.append("enforcement_note")
        for column in ("title", "guidance", "trigger"):
            if not cells.get(column, "").strip():
                problems.append(column)
        policy, action_problem = normalize_action(cells.get("action", ""))
        if action_problem == "malformed":
            findings.add(
                "MALFORMED_ACTION", "FATAL", "condition", condition_id, "action",
                "action value matches no known shape and cannot be normalized", (ref,),
            )  # fmt: skip
        elif action_problem == "normalized":
            findings.add(
                "MALFORMED_ACTION", "WARNING", "condition", condition_id, "action",
                "action 'blocking' is a type value, not an action: normalized to block", (ref,),
            )  # fmt: skip
        elif policy is not None and policy["follow_up"] is not None:
            findings.add(
                "MALFORMED_ACTION", "INFO", "condition", condition_id, "action",
                "two-state action normalized into an initial action and a follow-up", (ref,),
            )  # fmt: skip
        workflow = derive_workflow(cells.get("shared_across", ""), prefixes)
        if workflow is None:
            problems.append("shared_across")
        elif (workflow == "global") != (scope == "global"):
            problems.append("global_mismatch")
        if problems:
            findings.add(
                "INVALID_ROW", "FATAL", "condition", condition_id or f"row-{row.number}",
                "fields", f"invalid or missing: {', '.join(problems)}", (ref,),
            )  # fmt: skip
        out.append(
            ConditionRow(
                row=row,
                ref=ref,
                id=condition_id,
                workflow=workflow,
                scope=scope,
                type=kind if kind in CONDITION_TYPES else None,
                action_policy=policy,
                citation_status=citation if citation in CITATION else None,
                enforcement_status=enforcement if enforcement in ENFORCEMENT else None,
                valid=not problems and action_problem != "malformed",
                tokens=fact_tokens(row, single_words),
            )
        )
    return out


def condition_counts(rows: list[ConditionRow]) -> dict[str, object]:
    def by(key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in rows:
            value = str(getattr(row, key))
            counts[value] = counts.get(value, 0) + 1
        return dict(sorted(counts.items()))

    def pair(enforcement: str, citation: str) -> int:
        return sum(
            1 for r in rows if r.enforcement_status == enforcement and r.citation_status == citation
        )

    actions: dict[str, int] = {}
    for row in rows:
        policy = row.action_policy
        name = "malformed" if policy is None else str(policy["initial"])
        if policy is not None and policy["follow_up"] is not None:
            follow = policy["follow_up"]
            assert isinstance(follow, dict)
            name = f"{name}->{follow['action']} ({follow['when']})"
        actions[name] = actions.get(name, 0) + 1
    raw_actions: dict[str, int] = {}
    for row in rows:
        value = row.row.cells.get("action", "").strip()
        raw_actions[value] = raw_actions.get(value, 0) + 1
    return {
        "total": len(rows),
        "by_workflow": by("workflow"),
        "by_jurisdiction": by("scope"),
        "by_type": by("type"),
        "by_enforcement_status": by("enforcement_status"),
        "by_citation_status": by("citation_status"),
        "by_action_policy": dict(sorted(actions.items())),
        "raw_action_values": dict(sorted(raw_actions.items())),
        "active_confirmed": pair("active", "confirmed"),
        "active_needs_legal_review": pair("active", "needs_legal_review"),
        "not_enforced_confirmed": pair("not_enforced", "confirmed"),
        "not_enforced_needs_legal_review": pair("not_enforced", "needs_legal_review"),
        "invalid_rows": sum(1 for r in rows if not r.valid),
    }


def split_ids(value: str) -> list[str]:
    """Condition ids in a comma-separated cell (a trailing remark in brackets is dropped)."""
    ids = []
    for part in value.split(","):
        token = re.sub(r"\(.*?\)", "", part).strip()
        if CONDITION_ID.fullmatch(token):
            ids.append(token)
    return ids


def split_numbered(content: str) -> list[str]:
    """``1. A ... 2. B ...`` -> ["1. A ...", "2. B ..."] (the list's own numbering)."""
    starts = [m.start() for m in re.finditer(r"(?:(?<=\s)|^)(\d{1,2})\.\s", content)]
    numbered = []
    expected = 1
    keep: list[int] = []
    for position in starts:
        number = int(re.match(r"(\d{1,2})", content[position:]).group(1))  # type: ignore[union-attr]  # matched above
        if number == expected:
            keep.append(position)
            expected += 1
    for i, position in enumerate(keep):
        end = keep[i + 1] if i + 1 < len(keep) else len(content)
        numbered.append(content[position:end].strip())
    return numbered
