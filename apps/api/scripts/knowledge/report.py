"""The human-readable validation report (the JSON report holds the same facts).

The report names sources, ids, counts, codes and the compiler's own short
findings. It is private (it names the library's identifiers) and is written
next to the bundle, never into the repository.
"""

from collections.abc import Mapping
from typing import Any


def _table(rows: list[tuple[str, str]], header: tuple[str, str]) -> list[str]:
    out = [f"| {header[0]} | {header[1]} |", "| --- | --- |"]
    out += [f"| {a} | {b} |" for a, b in rows]
    return out


def _counts(title: str, counts: Mapping[str, Any]) -> list[str]:
    lines = [f"### {title}", ""]
    for key in (
        "total", "active_confirmed", "active_needs_legal_review", "not_enforced_confirmed",
        "not_enforced_needs_legal_review", "invalid_rows",
    ):  # fmt: skip
        lines.append(f"- {key}: {counts.get(key)}")
    for key in (
        "by_workflow", "by_jurisdiction", "by_type", "by_enforcement_status",
        "by_citation_status", "by_action_policy", "raw_action_values",
    ):  # fmt: skip
        values = counts.get(key, {})
        lines.append(f"- {key}: " + ", ".join(f"{k}={v}" for k, v in values.items()))
    return [*lines, ""]


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = ["# Knowledge compiler validation report", ""]
    lines += [
        f"- compiler: {report['compiler']}",
        f"- source_package_digest: `{report['source_package_digest']}`",
        f"- runtime_bundle_digest: `{report.get('runtime_bundle_digest')}`",
        f"- bundle file SHA-256 (pin): `{report.get('bundle_sha256')}`",
        f"- publishable: **{report['publishable']}**",
        "- findings: " + ", ".join(f"{k}={v}" for k, v in report["finding_counts"].items()),
        "",
        "## Source package",
        "",
    ]
    package = report["source_package"]
    lines += [
        f"- directory: {package['directory_name']}",
        f"- files found: {len(package['files_found'])}",
    ]
    lines += [f"- files missing: {package['files_missing'] or 'none'}", ""]
    lines += _table(
        [
            (name, f"`{sha}` ({package['roles'].get(name, 'unmapped')})")
            for name, sha in package["checksums"].items()
        ],
        ("file", "SHA-256 (role)"),
    )
    lines.append("")
    if "conditions" in report:
        lines += ["## Conditions", ""]
        lines += _counts("Whole workbook", report["conditions"]["all"])
        lines += _counts(
            "Published runtime slice (disciplinary + global)", report["conditions"]["runtime_slice"]
        )
        lines += [
            "Outside the runtime slice (audited, not published): "
            + ", ".join(report["conditions"]["outside_runtime_slice"]),
            "",
            f"Duplicates: {report['conditions']['duplicates'] or 'none'}; malformed actions: "
            f"{report['conditions']['malformed_actions'] or 'none'}",
            "",
        ]
    if "documents" in report:
        lines += ["## Documents (workbook Documents sheet vs actual files)", ""]
        lines += _table(
            [
                (r["doc_id"], f"{r.get('resolution', 'no file')} -> actual {r.get('actual', '-')}"
                 + (f"; status note: {r['status_note']}" if r.get("status_note") else ""))
                for r in report["documents"]["workbook_rows"]
            ],
            ("workbook id", "resolution"),
        )  # fmt: skip
        lines.append("")
    if "playbook" in report:
        p = report["playbook"]
        lines += [
            "## Playbook",
            "",
            f"- paragraphs: {p['paragraphs']}; units: {p['units']}; "
            f"excluded spans: {p['excluded_spans']}",
            f"- pathways: {', '.join(p['pathways'])}",
            f"- stages: {', '.join(p['stages'])}",
            f"- unassigned paragraphs: {p['unassigned_paragraphs'] or 'none'}",
            "",
        ]
    if "implementation_rules" in report:
        r = report["implementation_rules"]
        lines += [
            "## Implementation Rules",
            "",
            f"- rules: {r['rules']}; guards: {r['guards']}",
            f"- operational guards: {', '.join(r['operational_guards'])}",
            f"- superseded: {', '.join(r['superseded']) or 'none'}",
            f"- deferred capabilities: {', '.join(r['deferred_capabilities']) or 'none'}",
            f"- audit only: {', '.join(r['audit_only']) or 'none'}",
            "- explicit supersessions:",
        ]
        for item in r["explicit_supersessions"]:
            targets = ", ".join(f"{t['kind']} {t['id']}" for t in item["supersedes"])
            lines.append(f"  - {item['guard']} (rule {item['rule']}) supersedes {targets}")
        lines.append("")
    if "jurisdiction" in report:
        j = report["jurisdiction"]
        lines += ["## Jurisdiction coverage", ""]
        for scope in ("shared", "global", "uae_federal", "difc"):
            c = j[scope]
            lines.append(
                f"- {scope}: units {c['units']}, active conditions {c['conditions_active']}, "
                f"operational guards {c['guards_operational']}"
            )
        for code in ("uae_federal", "difc"):
            lines.append(
                f"- options in {code}: "
                + ", ".join(f"{k}={v}" for k, v in j["options"][code].items())
            )
            lines.append(
                f"- documents in {code}: "
                + ", ".join(f"{k}={v}" for k, v in j["documents"][code].items())
            )
        lines.append(f"- recorded gaps: {j['gaps']}")
        lines.append("")
    if report.get("reference_data") is not None:
        lines += ["## Reference data", ""]
        lines += [
            f"- {r['id']}: runtime={r['runtime']} (status {r['status']})"
            for r in report["reference_data"]
        ]
        lines.append("")
    if report.get("blueprint_dependencies") is not None:
        lines += ["## Blueprint dependency mapping (workbook field -> CompanyBlueprintContext)", ""]
        for item in report["blueprint_dependencies"]:
            lines.append(
                f"- {item['workbook_field']}: {item['treatment']}"
                + (f" ({item['blueprint']})" if item.get("blueprint") else "")
            )
        lines.append("")
    if report.get("workbook_sheets") is not None:
        lines += ["## Workbook sheets", ""]
        lines += [
            f"- {s['sheet']}: {s['role']} ({s['rows']} rows)" for s in report["workbook_sheets"]
        ]
        lines.append("")
    lines += ["## Quarantine", ""]
    lines += [
        f"- {q['kind']} {q['id']}: {q['reason']} ({q['finding']})" for q in report["quarantine"]
    ] or ["- none"]
    lines += ["", "## Findings", ""]
    for finding in report["findings"]:
        subject = finding["subject"]
        lines.append(
            f"- **{finding['severity']}** {finding['code']} {subject['kind']} {subject['id']}: "
            f"{finding['detail']}"
        )
    return "\n".join(lines) + "\n"
