#!/usr/bin/env python3
"""Validate the Privacy & Security Decision Register and the JJ review packet.

Checks the governance rules in docs/privacy/decision-register.md §2-§5:
unique, contiguous PRIV IDs; required packet fields and sections; controlled
vocabularies; no decided status without JJ evidence; no legal confirmation
without evidence; no implemented policy without approval; and agreement between
packets, the summary table, the traceability matrix and the JJ review packet.

Standard library only. Usage:
    scripts/check-privacy-decisions.py              # check the repository
    scripts/check-privacy-decisions.py --self-test  # prove the checks fail on bad input
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTER = REPO_ROOT / "docs/privacy/decision-register.md"
JJ_PACKET = REPO_ROOT / "docs/privacy/jj-decision-review-packet.md"

STATUSES = {
    "Pending Analysis",
    "Ready for JJ Review",
    "Legal Review Required",
    "Approved",
    "Rejected",
    "Deferred",
    "Superseded",
}
DECIDED = {"Approved", "Rejected", "Deferred"}
JJ_DECISIONS = {
    "Pending",
    "Approved",
    "Approved with conditions",
    "Rejected",
    "Deferred",
    "Further analysis requested",
}
LEGAL = {"Required", "Review Required", "Not required", "Confirmed"}
IMPACTS = {
    "Not currently blocking",
    "Blocks M2 feature",
    "Blocks M3 production activation",
    "Blocks external data processing",
    "Blocks deletion implementation",
}
IMPLEMENTATION = {
    "Not started",
    "Technical foundation complete",
    "Blocked pending decision",
    "Implementation tracked",
    "Implemented",
    "Verified",
}
REQUIRES_APPROVAL = {"Implementation tracked", "Implemented", "Verified"}

Packet = dict[str, Any]

FIELDS = [
    "Status",
    "Decision owner",
    "Technical owner",
    "Legal/privacy review",
    "JJ decision",
    "Decision evidence",
    "Legal/privacy evidence",
    "Decision date",
    "Decision version",
    "Implementation impact",
    "Implementation status",
    "Related decisions",
    "First recorded",
]
SECTIONS = [
    "**Question",
    "**Technical facts.**",
    "**Options",
    "**Privacy implications.**",
    "**EU/GDPR-standard considerations.**",
    "**UAE considerations.**",
    "**Cost / operational implications.**",
    "**Engineering recommendation.**",
    "**Legal/privacy question.**",
    "**Implementation traceability.**",
    "**Re-review trigger.**",
    "**History.**",
]
EMPTY = {"—", "-", ""}

PACKET_HEADING = re.compile(r"^### (PRIV-\d{3}) — (.+)$", re.M)
ANY_ID = re.compile(r"PRIV-\d{3}")
STRICT_ID = re.compile(r"^PRIV-\d{3}$")


def strip_parens(value: str) -> str:
    return re.sub(r"\s*\([^)]*\)", "", value).strip()


def split_values(value: str) -> list[str]:
    return [v.strip() for v in strip_parens(value).split(";") if v.strip()]


def table_rows(block: str) -> list[list[str]]:
    rows = []
    for line in block.splitlines():
        if line.startswith("|") and not re.match(r"^\|[\s|:-]+\|$", line):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    end = text.find("\n---\n", start)
    return text[start : end if end >= 0 else len(text)]


def parse_packets(text: str, errors: list[str]) -> dict[str, Packet]:
    packets: dict[str, Packet] = {}
    matches = list(PACKET_HEADING.finditer(text))
    for i, m in enumerate(matches):
        pid, title = m.group(1), m.group(2).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        stop = re.search(r"^(---|## )", text[m.end() : end], re.M)
        body = text[m.end() : m.end() + stop.start()] if stop else text[m.end() : end]
        if pid in packets:
            errors.append(f"{pid}: duplicate decision packet")
            continue
        fields: dict[str, str] = {}
        for row in table_rows(body.split("**", 1)[0]):
            if len(row) != 2 or row[0] == "Field":
                continue
            if row[0] in fields:
                errors.append(f"{pid}: duplicate field '{row[0]}'")
            fields[row[0]] = row[1]
        packets[pid] = {"title": title, "fields": fields, "body": body}
    return packets


def check_packet(pid: str, packet: Packet, errors: list[str]) -> None:
    f = packet["fields"]
    for name in FIELDS:
        if name not in f:
            errors.append(f"{pid}: missing field '{name}'")
    for marker in SECTIONS:
        if marker not in packet["body"]:
            errors.append(f"{pid}: missing section {marker}")
    if any(name not in f for name in FIELDS):
        return

    status, jj, legal = f["Status"], f["JJ decision"], f["Legal/privacy review"]
    if status not in STATUSES:
        errors.append(f"{pid}: invalid Status '{status}'")
    if jj not in JJ_DECISIONS:
        errors.append(f"{pid}: invalid JJ decision '{jj}'")
    if legal not in LEGAL:
        errors.append(f"{pid}: invalid Legal/privacy review '{legal}'")
    for value in split_values(f["Implementation impact"]):
        if value not in IMPACTS:
            errors.append(f"{pid}: invalid Implementation impact '{value}'")
    implementation = split_values(f["Implementation status"])
    for value in implementation:
        if value not in IMPLEMENTATION:
            errors.append(f"{pid}: invalid Implementation status '{value}'")
    for value in ANY_ID.findall(f["Related decisions"]):
        if value == pid:
            errors.append(f"{pid}: relates to itself")

    if jj == "Pending":
        if status in DECIDED:
            errors.append(f"{pid}: Status '{status}' but JJ decision is Pending")
        if f["Decision version"] not in EMPTY:
            errors.append(f"{pid}: Decision version set without a JJ decision")
    else:
        if f["Decision evidence"] in EMPTY:
            errors.append(f"{pid}: JJ decision '{jj}' without Decision evidence")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", f["Decision date"]):
            errors.append(f"{pid}: JJ decision '{jj}' without a Decision date")
        if not re.fullmatch(r"v\d+", f["Decision version"]):
            errors.append(f"{pid}: JJ decision '{jj}' without a Decision version")
        if f"**Decision {f['Decision version']}" not in packet["body"]:
            errors.append(f"{pid}: no '**Decision {f['Decision version']}' block")

    if status == "Approved":
        if jj not in {"Approved", "Approved with conditions"}:
            errors.append(f"{pid}: Approved status but JJ decision is '{jj}'")
        if legal not in {"Confirmed", "Not required"}:
            errors.append(f"{pid}: Approved while legal/privacy review is '{legal}'")
    if status in {"Rejected", "Deferred"} and jj != status:
        errors.append(f"{pid}: Status '{status}' but JJ decision is '{jj}'")
    if legal in {"Confirmed", "Not required"} and f["Legal/privacy evidence"] in EMPTY:
        errors.append(f"{pid}: legal/privacy review '{legal}' without evidence")
    if status != "Approved" and REQUIRES_APPROVAL & set(implementation):
        errors.append(f"{pid}: implementation status needs an Approved decision")
    if status == "Superseded" and not ANY_ID.search(packet["body"].split("**History.**")[-1]):
        errors.append(f"{pid}: Superseded without a pointer to the replacing ID")


def check_register(text: str, errors: list[str]) -> dict[str, Packet]:
    packets = parse_packets(text, errors)
    if not packets:
        errors.append("register: no decision packets found")
        return packets
    ids = list(packets)
    for pid in ids:
        check_packet(pid, packets[pid], errors)
    expected = [f"PRIV-{n:03d}" for n in range(1, len(ids) + 1)]
    if sorted(ids) != expected:
        errors.append(f"register: IDs are not contiguous from PRIV-001: {sorted(ids)}")
    if ids != sorted(ids):
        errors.append("register: packets are not in ID order")

    summary = section(text, "## Decision Register\n")
    rows = [r for r in table_rows(summary) if r and STRICT_ID.match(r[0])]
    seen = [r[0] for r in rows]
    if len(seen) != len(set(seen)):
        errors.append("summary: duplicate IDs")
    if sorted(set(seen)) != sorted(ids):
        errors.append(f"summary: IDs differ from packets: {sorted(set(seen) ^ set(ids))}")
    for row in rows:
        pid = row[0]
        if pid not in packets or len(row) != 6:
            if len(row) != 6:
                errors.append(f"summary {pid}: expected 6 columns")
            continue
        f = packets[pid]["fields"]
        expected_row = [
            packets[pid]["title"],
            f.get("Status"),
            f.get("JJ decision"),
            f.get("Legal/privacy review"),
            "; ".join(split_values(f.get("Implementation impact", ""))),
        ]
        for column, have, want in zip(
            ["title", "Status", "JJ Decision", "Legal Review", "Implementation Impact"],
            row[1:],
            expected_row,
            strict=True,
        ):
            if have != want:
                errors.append(f"summary {pid}: {column} '{have}' != packet '{want}'")

    trace = section(text, "## Decision-to-Implementation Traceability\n")
    trace_rows = [r for r in table_rows(trace) if r and STRICT_ID.match(r[0])]
    trace_ids = [r[0] for r in trace_rows]
    if sorted(trace_ids) != sorted(ids) or len(trace_ids) != len(set(trace_ids)):
        errors.append("traceability: matrix must list every decision exactly once")
    for row in trace_rows:
        pid = row[0]
        if pid in packets and len(row) >= 4:
            want = packets[pid]["fields"].get("Implementation status")
            if row[3] != want:
                errors.append(f"traceability {pid}: status '{row[3]}' != packet '{want}'")
    return packets


def check_jj_packet(text: str, packets: dict[str, Packet], errors: list[str]) -> None:
    statuses = {pid: p["fields"].get("Status") for pid, p in packets.items()}
    pattern = "|".join(sorted(STATUSES, key=len, reverse=True))
    claims: list[tuple[str, str]] = []

    for line in text.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            row_ids = [c for c in cells if STRICT_ID.match(c)]
            row_statuses = [c for c in cells if c in STATUSES]
            if len(row_ids) == 1 and len(row_statuses) == 1:
                claims.append((row_ids[0], row_statuses[0]))

    heading_id = None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("### "):
            found = ANY_ID.findall(line)
            heading_id = found[0] if len(found) == 1 else None
        if "**Register status:**" in line:
            bullet = line
            j = i + 1
            while j < len(lines) and lines[j].startswith("  "):
                bullet += " " + lines[j].strip()
                j += 1
            pairs = re.findall(rf"(PRIV-\d{{3}}) ({pattern})", bullet)
            if pairs:
                claims.extend(pairs)
            elif heading_id:
                value = bullet.split("**Register status:**", 1)[1].strip()
                claims.append((heading_id, value))
            else:
                errors.append(f"JJ packet line {i + 1}: Register status without a decision ID")

    for pid in sorted(set(ANY_ID.findall(text))):
        if pid not in packets:
            errors.append(f"JJ packet: {pid} does not exist in the register")
    for pid, claimed in claims:
        if pid in statuses and claimed != statuses[pid]:
            errors.append(f"JJ packet {pid}: status '{claimed}' != register '{statuses[pid]}'")
    listed = {pid for pid, _ in claims}
    for pid, status in statuses.items():
        if status == "Ready for JJ Review" and pid not in listed:
            errors.append(f"JJ packet: {pid} is Ready for JJ Review but not listed")


def validate(register_text: str, jj_text: str) -> list[str]:
    errors: list[str] = []
    packets = check_register(register_text, errors)
    check_jj_packet(jj_text, packets, errors)
    return errors


# --- self-test ---------------------------------------------------------------

_SECTIONS_TEXT = "\n\n".join(f"{s} x" for s in SECTIONS)


def _packet(pid: str, title: str, **overrides: str) -> str:
    values = {
        "Status": "Pending Analysis",
        "Decision owner": "JJ",
        "Technical owner": "Technical Lead",
        "Legal/privacy review": "Required",
        "JJ decision": "Pending",
        "Decision evidence": "—",
        "Legal/privacy evidence": "—",
        "Decision date": "—",
        "Decision version": "—",
        "Implementation impact": "Not currently blocking",
        "Implementation status": "Not started",
        "Related decisions": "—",
        "First recorded": "M1-01",
    }
    values.update(overrides)
    table = "\n".join(f"| {k} | {v} |" for k, v in values.items())
    return (
        f"### {pid} — {title}\n\n| Field | Value |\n| --- | --- |\n{table}\n\n{_SECTIONS_TEXT}\n\n"
    )


def _register(packets: list[tuple[str, str, dict[str, str]]]) -> str:
    summary, trace, bodies = [], [], []
    for pid, title, over in packets:
        bodies.append(_packet(pid, title, **over))
        status = over.get("Status", "Pending Analysis")
        jj = over.get("JJ decision", "Pending")
        legal = over.get("Legal/privacy review", "Required")
        impact = "; ".join(
            split_values(over.get("Implementation impact", "Not currently blocking"))
        )
        summary.append(f"| {pid} | {title} | {status} | {jj} | {legal} | {impact} |")
        trace.append(f"| {pid} | m | w | {over.get('Implementation status', 'Not started')} | e |")
    return (
        "## Decision Register\n\n"
        "| ID | Decision | Status | JJ Decision | Legal Review | Implementation Impact |\n"
        "|---|---|---|---|---|---|\n" + "\n".join(summary) + "\n\n---\n\n"
        "## Decision-to-Implementation Traceability\n\n"
        "| ID | A | W | Status | E |\n|---|---|---|---|---|\n"
        + "\n".join(trace)
        + "\n\n---\n\n## Decision Packets\n\n"
        + "".join(bodies)
        + "---\n"
    )


def self_test() -> int:
    good = [
        ("PRIV-001", "One", {}),
        ("PRIV-002", "Two", {"Status": "Ready for JJ Review"}),
    ]
    good_jj = "### PRIV-002 — Two\n\n- **Register status:** Ready for JJ Review\n"
    approved = {
        "Status": "Approved",
        "JJ decision": "Approved",
        "Decision evidence": "Linear comment 2026-10-09",
        "Decision date": "2026-10-09",
        "Decision version": "v1",
        "Legal/privacy review": "Confirmed",
        "Legal/privacy evidence": "Reviewer memo 2026-10-09",
        "Implementation status": "Implemented",
    }

    def with_block(text: str) -> str:
        return text.replace("**History.** x", "**Decision v1.** x\n\n**History.** x")

    cases: list[tuple[str, str, str, str | None]] = [
        ("valid register passes", _register(good), good_jj, None),
        (
            "valid approved decision passes",
            with_block(_register([good[0], ("PRIV-002", "Two", approved)])),
            "",
            None,
        ),
        ("duplicate ID", _register(good + [("PRIV-002", "Two", {})]), good_jj, "duplicate"),
        ("gap in IDs", _register([good[0], ("PRIV-003", "Three", {})]), "", "contiguous"),
        (
            "invalid status",
            _register([("PRIV-001", "One", {"Status": "Done"})]),
            "",
            "invalid Status",
        ),
        (
            "approved without evidence",
            _register([("PRIV-001", "One", {"Status": "Approved", "JJ decision": "Approved"})]),
            "",
            "without Decision evidence",
        ),
        (
            "approved without legal confirmation",
            with_block(
                _register([("PRIV-001", "One", {**approved, "Legal/privacy review": "Required"})])
            ),
            "",
            "Approved while legal/privacy review",
        ),
        (
            "legal confirmed without evidence",
            _register([("PRIV-001", "One", {"Legal/privacy review": "Confirmed"})]),
            "",
            "without evidence",
        ),
        (
            "implemented without approval",
            _register([("PRIV-001", "One", {"Implementation status": "Implemented"})]),
            "",
            "needs an Approved decision",
        ),
        (
            "summary drift",
            _register(good).replace(
                "| PRIV-002 | Two | Ready for JJ Review", "| PRIV-002 | Two | Approved"
            ),
            good_jj,
            "summary PRIV-002: Status",
        ),
        (
            "missing field",
            _register(good).replace("| Technical owner | Technical Lead |\n", "", 1),
            good_jj,
            "missing field 'Technical owner'",
        ),
        (
            "JJ packet drift",
            _register(good),
            good_jj.replace("Ready for JJ Review", "Approved"),
            "JJ packet PRIV-002",
        ),
        ("JJ packet omits ready item", _register(good), "", "not listed"),
        ("JJ packet unknown ID", _register(good), good_jj + "PRIV-099\n", "does not exist"),
    ]
    failures = 0
    for name, register, jj, expected in cases:
        errors = validate(register, jj)
        ok = not errors if expected is None else any(expected in e for e in errors)
        print(f"{'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": {errors}"))
        failures += not ok
    if failures:
        print(f"self-test FAILED ({failures} case(s))")
        return 1
    print(f"self-test passed ({len(cases)} cases)")
    return 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["--self-test"]:
        return self_test()
    if argv[1:]:
        print(__doc__)
        return 2
    errors = validate(REGISTER.read_text(encoding="utf-8"), JJ_PACKET.read_text(encoding="utf-8"))
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        print(f"Privacy decision register check FAILED ({len(errors)} error(s))")
        return 1
    count = len(PACKET_HEADING.findall(REGISTER.read_text(encoding="utf-8")))
    print(f"Privacy decision register check PASSED ({count} decisions)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
