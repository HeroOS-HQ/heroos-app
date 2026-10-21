"""A fictional source package and compile mapping, generated at test time (M2-NEW-04).

Nothing here is HeroOS content: the "Example Conduct Guide", its rules,
conditions and templates are invented, with fictional article numbers (900+),
so the compiler and the runtime can be tested in this public repository. The
package reproduces the real package's structure and its known problems, so
every check runs against something concrete:

- two template codes reversed in the guide and the workbook (EX02/EX03),
  covered by an owner decision that the actual files win;
- a workbook mapping copied from one document onto an unrelated one (EX05);
- a stale workbook note about a template (EX06);
- a rule explicitly superseded by another, which also overrides guide text
  and a Condition's guidance;
- compound actions, a "blocking" action, a not-enforced row, active rows still
  under legal review, a row of another workflow, Federal- and DIFC-labelled
  passages, a nested table, a deferred capability and an audit-only rule.

Word and Excel files are never tracked in this repository; these are built
in a temporary directory by ``write_sources``.
"""

import hashlib
import json
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final
from xml.sax.saxutils import escape

PLAYBOOK: Final = "EX-PB - Example Conduct Guide.docx"
RULES: Final = "EX-IR - Example Implementation Rules.docx"
WORKBOOK: Final = "EX-CL - Example Conditions.xlsx"
TEMPLATES: Final = {
    "EX01": ("EX01 - Example Reminder.docx", "shared"),
    "EX02": ("EX02 - Example Warning.docx", "shared"),
    "EX03": ("EX03 - Example Meeting.docx", "shared"),
    "EX04": ("EX04 - Example Suspension Notice.docx", "uae_federal"),
    "EX05": ("EX05 - Example Delay Notice.docx", "shared"),
    "EX06": ("EX06 - Example Charges.docx", "shared"),
    "EX07": ("EX07 - Example Outcome Notice.docx", "shared"),
}

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_CONTENT_TYPES_DOCX = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.document.main+xml"/></Types>'
)


def _entry(archive: zipfile.ZipFile, name: str, data: str | bytes) -> None:
    """A part with a fixed timestamp, so the same content is always the same bytes."""
    archive.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), data)


def _paragraph(text: str, style: str | None = None) -> str:
    props = "" if style is None else f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
    return f'<w:p>{props}<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def _table(cells: list[str], nested: list[str] | None = None) -> str:
    inner = ""
    if nested is not None:
        inner = (
            "<w:tbl><w:tr><w:tc>"
            + "".join(_paragraph(t) for t in nested)
            + "</w:tc></w:tr></w:tbl>"
        )
    body = "".join(_paragraph(t) for t in cells)
    return f"<w:tbl><w:tr><w:tc>{body}{inner}<w:p/></w:tc></w:tr></w:tbl>"


def write_docx(path: Path, blocks: list[str]) -> None:
    body = "".join(blocks)
    document = (
        f'<?xml version="1.0" encoding="UTF-8"?><w:document {_W}>'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        _entry(archive, "[Content_Types].xml", _CONTENT_TYPES_DOCX)
        _entry(archive, "word/document.xml", document)


def _cell(ref: str, value: str) -> str:
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'


def _column(index: int) -> str:
    return chr(ord("A") + index)


def write_xlsx(path: Path, sheets: dict[str, list[list[str]]]) -> None:
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    entries, rels, parts = [], [], {}
    for index, (name, rows) in enumerate(sheets.items(), start=1):
        entries.append(f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>')
        rels.append(
            f'<Relationship Id="rId{index}" Type="{rel}/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
        )
        xml_rows = "".join(
            f'<row r="{r}">'
            + "".join(_cell(f"{_column(c)}{r}", v) for c, v in enumerate(row) if v != "")
            + "</row>"
            for r, row in enumerate(rows, start=1)
        )
        parts[f"xl/worksheets/sheet{index}.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{main}"><sheetData>{xml_rows}'
            "</sheetData></worksheet>"
        )
    with zipfile.ZipFile(path, "w") as archive:
        _entry(
            archive,
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types"><Default Extension="xml" '
            'ContentType="application/xml"/></Types>',
        )
        _entry(
            archive,
            "xl/workbook.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{main}" '
            f'xmlns:r="{rel}"><sheets>' + "".join(entries) + "</sheets></workbook>",
        )
        _entry(
            archive,
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.'
            'openxmlformats.org/package/2006/relationships">' + "".join(rels) + "</Relationships>",
        )
        for name, data in parts.items():
            _entry(archive, name, data)


# --- the fictional sources ---------------------------------------------------------------

PLAYBOOK_BLOCKS: Final = [
    _paragraph("Example Conduct Guide"),
    _paragraph("Step 1: Decide the level"),
    _paragraph("Decide whether the concern is minor or serious before acting."),
    _paragraph("⚖️ UAE Legal Position: Example deadline"),
    _paragraph(
        "Under the UAE Federal Labour Law (fictional Article 901), notify the employee promptly."
    ),
    _paragraph("DIFC: The Federal example deadline does not apply to DIFC employers."),
    _paragraph("Path A: Minor concerns"),
    _paragraph("Stage 1 - Reminder"),
    _paragraph("Use a reminder first and listen to the employee."),
    _paragraph("👉 Doc EX01 – Example Reminder"),
    _paragraph("Stage 2 - Warning"),
    _paragraph(
        "Hold a meeting and document it as per Doc 02, then use Doc 03 to issue the warning."
    ),
    _paragraph("👉 Doc EX02 – Example Meeting"),
    _paragraph("👉 Doc EX03 – Example Warning"),
    _paragraph("Alternatives to ending employment:"),
    _paragraph("Example unpaid suspension (up to 900 days)"),
    _paragraph("Example salary deduction (up to 900 days)"),
    _paragraph("These are alternatives, not a fixed sequence."),
    _paragraph("Pay deductions – expert referral"),
    _paragraph("HeroOS does not calculate deductions and refers them to a human expert."),
    _paragraph("Penalty Option – Example unpaid suspension"),
    _paragraph(
        "Under Article 902 of the UAE Federal Labour Law (fictional), unpaid suspension is capped."
    ),
    _paragraph("👉 Doc EX04 – Example Suspension Notice"),
    _paragraph("DIFC Example Suspension"),
    _paragraph(
        "Unlike UAE Federal Labour Law, DIFC Employment Law has no fictional cap; "
        "refer it for review."
    ),
    _paragraph("Penalty Option – Example delay"),
    _paragraph("Delay an increase only if one is scheduled."),
    _paragraph("👉 Doc EX05 – Example Delay Notice"),
    _paragraph("Path B: Serious concerns"),
    _paragraph(
        "Serious concerns open an investigation first; classification never authorises dismissal."
    ),
    _table(
        ["Stage 1 - Charges"],
        nested=["Describe the allegations neutrally.", "👉 Doc EX06 – Example Charges"],
    ),
    _paragraph("Stage 2 - Outcome"),
    _paragraph("The employee must sign this document."),
    _paragraph(
        "The employer decides the outcome after the investigation; "
        "a signature confirms receipt only."
    ),
    _paragraph("👉 Doc EX07 – Example Outcome Notice"),
    _paragraph("Example only. Not legal advice."),
]

RULE_BLOCKS: Final = [
    _paragraph("Example Implementation Rules", "Title"),
    _paragraph("1. Jurisdiction Isolation", "Heading1"),
    _paragraph("Never apply UAE Federal law to a DIFC case or DIFC law to a UAE Federal case."),
    _paragraph("2. Old Deduction Rule", "Heading1"),
    _paragraph("Superseded by Rule 3. HeroOS once explained example deductions."),
    _paragraph("3. Deduction Expert Referral", "Heading1"),
    _paragraph("HeroOS must not calculate deductions; refer them to a human expert."),
    _paragraph(
        "This Rule 3 overrides any older rule, guide wording or condition about deductions."
    ),
    _paragraph("4. Investigation First", "Heading1"),
    _paragraph("Serious classification triggers an investigation, not dismissal."),
    _paragraph("5. Employer Decides", "Heading1"),
    _paragraph("The employer makes the final decision."),
    _paragraph("6. Approved Content", "Heading1"),
    _paragraph("Use only approved content; no open-web research."),
    _paragraph("7. Contextual Questions", "Heading1"),
    _paragraph("Ask only material questions and reuse known facts."),
    _paragraph("8. Suspension Distinction", "Heading1"),
    _paragraph("Investigative suspension is not a penalty."),
    _paragraph("DIFC: unpaid disciplinary suspension always needs a human expert's review."),
    _paragraph("9. DIFC Dismissal Review", "Heading1"),
    _paragraph("In DIFC, dismissal without notice needs documented expert clearance first."),
    _paragraph("10. Uploads Later", "Heading1"),
    _paragraph("Uploads and deletion promises are deferred until real controls exist."),
    _paragraph("11. Draft Note", "Heading1"),
    _paragraph("This is a working draft."),
]

CONDITION_HEADER: Final = [
    "id",
    "jurisdiction",
    "type",
    "trigger",
    "title",
    "guidance",
    "action",
    "source",
    "last_reviewed",
    "citation_status",
    "enforcement_status",
    "enforcement_note",
    "shared_across",
    "blueprint_or_workflow_field",
    "notes",
]


def _condition(
    cid: str,
    scope: str,
    kind: str,
    action: str,
    citation: str,
    enforcement: str,
    shared: str,
    field: str,
    guidance: str,
    note: str = "",
) -> list[str]:
    return [
        cid,
        scope,
        kind,
        f"fictional trigger for {cid}",
        f"Example condition {cid}",
        guidance,
        action,
        "fictional source",
        "2026-10",
        citation,
        enforcement,
        note,
        shared,
        field,
        "",
    ]


CONDITIONS: Final = [
    _condition(
        "EX-ROUTING-1",
        "GLOBAL",
        "precondition",
        "blocking",
        "confirmed",
        "active",
        "ALL playbooks (global)",
        "operating_jurisdictions (Blueprint)",
        "Confirm the jurisdiction before anything jurisdiction-specific.",
    ),
    _condition(
        "EX-FED-POLICY",
        "UAE-FED",
        "step_caution",
        "warn",
        "needs_legal_review",
        "active",
        "Disciplinary only",
        "employee_aware_of_relevant_policy (workflow)",
        "Check the expected standard was explained.",
    ),
    _condition(
        "EX-FED-CAP",
        "UAE-FED",
        "step_caution",
        "warn (first pass); block if the employer insists on proceeding above the cap",
        "confirmed",
        "active",
        "Disciplinary only (UAE-FED)",
        "proposed_suspension_days (workflow)",
        "Say a fictional cap applies; if the employer insists, HeroOS cannot confirm it.",
    ),
    _condition(
        "EX-FED-ESCALATE",
        "UAE-FED",
        "blocking",
        "escalate",
        "needs_legal_review",
        "active",
        "Disciplinary only",
        "dismissal_without_notice_considered (workflow)",
        "Escalate before any dismissal without notice is considered.",
    ),
    _condition(
        "EX-FED-OLD-DEDUCTION",
        "UAE-FED",
        "step_caution",
        "warn",
        "confirmed",
        "not_enforced",
        "Disciplinary only",
        "deduction_requested (workflow)",
        "Check the fictional deduction limit.",
        note="Superseded by the expert referral; document numbers use the earlier numbering.",
    ),
    _condition(
        "EX-FED-PAY-CAUTION",
        "UAE-FED",
        "step_caution",
        "warn",
        "confirmed",
        "active",
        "Disciplinary only",
        "none - fixed caution",
        "Reduced pay is allowed, and a deduction remains available afterwards as a penalty.",
    ),
    _condition(
        "EX-FED-WARNING-LABEL",
        "UAE-FED",
        "step_caution",
        "warn",
        "confirmed",
        "active",
        "Disciplinary only",
        "none - a drafting instruction",
        "Use EX03 again for the second warning; only the email subject changes.",
    ),
    _condition(
        "EX-DIFC-SUSPENSION",
        "DIFC",
        "blocking",
        "escalate",
        "needs_legal_review",
        "active",
        "Disciplinary only",
        "case_employee_jurisdiction, proposed_penalty (workflow)",
        "DIFC Employment Law has no fictional cap; refer unpaid suspension for review.",
    ),
    _condition(
        "EX-SHARED-DEDUCTION",
        "SHARED",
        "blocking",
        "escalate",
        "needs_legal_review",
        "active",
        "Disciplinary; likely Offboarding",
        "deduction_requested (workflow)",
        "HeroOS refers every deduction to a human expert. UAE Federal: fictional Article 904 "
        "sets limits. DIFC: the Federal limits do not apply.",
    ),
    _condition(
        "EX-DIFC-DEADLINE",
        "DIFC",
        "step_caution",
        "warn; escalate if timing is in doubt",
        "needs_legal_review",
        "active",
        "Disciplinary only",
        "policy_timeframe (workflow)",
        "Follow the company policy's timeframes in DIFC.",
    ),
    _condition(
        "EX-PROB-ONLY",
        "UAE-FED",
        "step_caution",
        "warn",
        "confirmed",
        "active",
        "Probation only",
        "probation_length (workflow)",
        "A probation-only example.",
    ),
]

DOCUMENT_ROWS: Final = [
    ["doc_id", "title", "path", "stage", "status", "related_conditions", "notes"],
    ["EX01", "Example Reminder", "Minor", "Stage 1", "active", "EX-FED-POLICY", ""],
    # Reversed, as in the real workbook: the actual files win (owner decision).
    ["EX02", "Example Meeting", "Minor", "Stage 2", "active", "", ""],
    ["EX03", "Example Warning", "Minor", "Stage 2", "active", "EX-FED-WARNING-LABEL", ""],
    [
        "EX04",
        "Example Suspension Notice",
        "Minor",
        "Option",
        "active",
        "EX-FED-CAP, EX-DIFC-SUSPENSION",
        "",
    ],
    # Copied from EX04: unrelated to a delay notice.
    [
        "EX05",
        "Example Delay Notice",
        "Minor",
        "Option",
        "active",
        "EX-FED-CAP, EX-DIFC-SUSPENSION",
        "",
    ],
    [
        "EX06",
        "Example Charges",
        "Serious",
        "Stage 1",
        "active - citation fix pending",
        "",
        "KNOWN BUG: still cites fictional Article 905.",
    ],
    ["EX07", "Example Outcome Notice", "Serious", "Stage 2", "active", "", ""],
    ["EX99-OLD", "Retired example", "Minor", "n/a", "retired", "", ""],
]


def _template(title: str, instructions: list[str], body: str = "[Body]") -> list[str]:
    return [
        _paragraph(title),
        *(_paragraph(i) for i in instructions),
        _paragraph("Date: [Insert]"),
        _paragraph(body),
    ]


TEMPLATE_BLOCKS: Final = {
    "EX01": _template("Example Reminder", ["User Instructions: Use for a minor first concern."]),
    "EX02": _template("Example Warning", ["User Instructions: Use after the meeting."]),
    "EX03": _template("Example Meeting", ["User Instructions: Invite the employee to explain."]),
    "EX04": _template(
        "Example Suspension Notice",
        [
            "User Instructions: UAE Federal: Under fictional Article 902 of the UAE Federal Labour "
            "Law, use only after the investigation.",
            "DIFC: Do not generate this for DIFC; refer it for expert review.",
        ],
        "Not exceeding the fictional cap under UAE Federal Labour Law.",
    ),
    "EX05": _template(
        "Example Delay Notice",
        [
            "User Instructions: UAE Federal: fictional Article 906 sets the postponement rules.",
            "DIFC: refer a disciplinary delay for expert review.",
        ],
    ),
    "EX06": _template("Example Charges", ["Instruction: Describe the allegations neutrally."]),
    "EX07": _template(
        "Example Outcome Notice",
        ["User Instructions: The employer selects and approves the outcome."],
    ),
}


def workbook_sheets(conditions: list[list[str]] | None = None) -> dict[str, list[list[str]]]:
    return {
        "Conditions Library": [CONDITION_HEADER, *(conditions or CONDITIONS)],
        "Legend": [["Field", "What it means"], ["action", "warn, block, or escalate"]],
        "Reference Data": [
            [
                "id",
                "jurisdiction",
                "title",
                "content",
                "source",
                "last_reviewed",
                "status",
                "used_by_conditions",
                "notes",
            ],
            [
                "EX-FED-LIST",
                "UAE-FED",
                "Example grounds",
                "1. First example ground. 2. Second example ground.",
                "fictional",
                "2026-10",
                "needs_legal_review",
                "EX-FED-ESCALATE",
                "",
            ],
            [
                "EX-OLD-LIMITS",
                "UAE-FED",
                "Old example limits",
                "fictional limits",
                "fictional",
                "2026-10",
                "reference_only",
                "none",
                "",
            ],
        ],
        "Structural Findings": [["date_raised", "finding"], ["2026-10", "An example finding."]],
        "Documents": DOCUMENT_ROWS,
        "Blueprint Fields": [
            ["field", "type", "captured_at", "used_by_conditions", "description"],
            ["headcount", "number", "setup", "none", "Employees"],
            ["operating_jurisdictions", "text", "setup", "EX-ROUTING-1", "Jurisdictions"],
        ],
        "Test Company Example": [["field", "value", "expected effect"], ["headcount", "5", "-"]],
        "Disciplinary Coverage": [["Example coverage check"]],
    }


def write_sources(directory: Path, *, conditions: list[list[str]] | None = None) -> Path:
    """The fictional package in ``directory`` (created). Returns the directory."""
    directory.mkdir(parents=True, exist_ok=True)
    write_docx(directory / PLAYBOOK, PLAYBOOK_BLOCKS)
    write_docx(directory / RULES, RULE_BLOCKS)
    write_xlsx(directory / WORKBOOK, workbook_sheets(conditions))
    for doc, (name, _) in TEMPLATES.items():
        write_docx(directory / name, TEMPLATE_BLOCKS[doc])
    return directory


# --- the fictional mapping -------------------------------------------------------------

FED, DIFC, LS, SM = "uae_federal", "difc", "less_serious", "serious"


def _unit(uid: str, start: str, end: str | None, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": uid,
        "from": start,
        "to": end,
        "title": f"Example unit {uid}",
        "scope": "shared",
        "kind": "methodology",
        "pathway": None,
        "stage": None,
        "topics": [],
        "required_facts": [],
        "guards": [],
        "conditions": [],
        "documents": [],
        "options": [],
        "without_jurisdiction": False,
        "scope_rules": [],
        "regions": [],
        "withhold": [],
        "conflicts": [],
        "limitations": [],
    }
    base.update(extra)
    return base


def _guard(gid: str, rule: str, kind: str, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": gid,
        "rule": rule,
        "kind": kind,
        "scope": "shared",
        "status": "operational",
        "workflow": "all",
        "topics": [],
        "options": [],
        "required": [],
        "prohibited": [],
        "escalation": "none",
        "supersedes": [],
        "select": [],
        "scope_rules": [],
        "regions": [],
    }
    base.update(extra)
    return base


def _dj(
    status: str,
    gates: Sequence[str] = (),
    conditions: Sequence[str] = (),
    guards: Sequence[str] = (),
    limitations: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "status": status,
        "gates": list(gates),
        "conditions": list(conditions),
        "guards": list(guards),
        "limitations": list(limitations),
    }


def _oj(
    availability: str,
    reason: str,
    documents: Sequence[str] = (),
    conditions: Sequence[str] = (),
    guards: Sequence[str] = (),
    facts: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "availability": availability,
        "reason": reason,
        "documents": list(documents),
        "conditions": list(conditions),
        "guards": list(guards),
        "required_facts": list(facts),
    }


def _option(
    oid: str,
    kind: str,
    pathway: str | None,
    penalty: bool,
    investigation: bool,
    response: bool,
    fed: dict[str, Any],
    difc: dict[str, Any],
    units: list[str],
) -> dict[str, Any]:
    return {
        "id": oid,
        "kind": kind,
        "workflow": "disciplinary",
        "pathway": pathway,
        "title": f"Example {kind}",
        "is_penalty": penalty,
        "requires_completed_investigation": investigation,
        "requires_employee_response": response,
        "jurisdictions": {FED: fed, DIFC: difc},
        "units": units,
    }


def mapping(source_dir: Path | None = None) -> dict[str, Any]:
    """The fictional compile mapping. With ``source_dir``, sources are pinned to their bytes."""

    def pin(name: str) -> str | None:
        return (
            None
            if source_dir is None
            else hashlib.sha256((source_dir / name).read_bytes()).hexdigest()
        )

    sources = [
        {
            "source_id": "guide",
            "source_type": "playbook",
            "filename": PLAYBOOK,
            "title": "Example guide",
            "source_version": "1",
            "workflow": "disciplinary",
            "jurisdiction_scope": "shared",
            "runtime_role": "operational",
            "reviewed_sha256": pin(PLAYBOOK),
        },
        {
            "source_id": "rules",
            "source_type": "implementation_rules",
            "filename": RULES,
            "title": "Example rules",
            "source_version": "1",
            "workflow": "all",
            "jurisdiction_scope": "shared",
            "runtime_role": "operational",
            "reviewed_sha256": pin(RULES),
        },
        {
            "source_id": "conditions",
            "source_type": "conditions_workbook",
            "filename": WORKBOOK,
            "title": "Example conditions",
            "source_version": "1",
            "workflow": "all",
            "jurisdiction_scope": "shared",
            "runtime_role": "operational",
            "reviewed_sha256": pin(WORKBOOK),
        },
    ] + [
        {
            "source_id": doc,
            "source_type": "template",
            "document_id": doc,
            "filename": name,
            "title": name[7:-5],
            "source_version": "1",
            "workflow": "disciplinary",
            "jurisdiction_scope": scope,
            "runtime_role": "operational",
            "reviewed_sha256": pin(name),
        }
        for doc, (name, scope) in TEMPLATES.items()
    ]
    facts = [
        {
            "key": "employment_jurisdiction",
            "label": "Jurisdiction",
            "blueprint": "jurisdiction.employment_jurisdiction",
            "case_fact": "jurisdiction.case_confirmation",
            "needs_confirmation": True,
            "sensitive": False,
        },
        {
            "key": "headcount",
            "label": "Headcount",
            "blueprint": "employee_count",
            "case_fact": None,
            "needs_confirmation": False,
            "sensitive": False,
        },
        {
            "key": "employee_aware_of_relevant_policy",
            "label": "Standard explained",
            "blueprint": None,
            "case_fact": "context.policy_awareness",
            "needs_confirmation": False,
            "sensitive": False,
        },
        {
            "key": "dismissal_without_notice_considered",
            "label": "Dismissal considered",
            "blueprint": None,
            "case_fact": "screening.dismissal_without_notice",
            "needs_confirmation": False,
            "sensitive": True,
        },
    ] + [
        {
            "key": key,
            "label": key.replace("_", " "),
            "blueprint": None,
            "case_fact": None,
            "needs_confirmation": False,
            "sensitive": False,
        }
        for key in (
            "proposed_suspension_days",
            "deduction_requested",
            "proposed_penalty",
            "policy_timeframe",
            "misconduct_level",
            "investigation_completed",
            "employer_decision",
            "suspension_type",
            "expert_clearance_documented",
            "given_opportunity_to_explain",
        )
    ]
    aliases: dict[str, str | None] = {f["key"]: f["key"] for f in facts}
    aliases.update(
        {
            "operating_jurisdictions": "employment_jurisdiction",
            "case_employee_jurisdiction": "employment_jurisdiction",
            "probation_length": None,
        }
    )
    topic_options = {
        "salary_deduction": ["opt-deduction"],
        "dismissal_without_notice": ["opt-dismissal"],
        "disciplinary_suspension": ["opt-suspension"],
        "investigative_suspension": ["opt-investigative"],
        "delay_increase_or_promotion": ["opt-delay"],
        "formal_warning": ["opt-warning"],
    }
    topics = [
        {
            "key": key,
            "title": f"Example topic {key}",
            "workflow": "disciplinary",
            "pathways": [],
            "options": topic_options.get(key, []),
        }
        for key in (
            "misconduct_level",
            "deadlines",
            "workplace_reminder",
            "formal_warning",
            "disciplinary_suspension",
            "investigative_suspension",
            "salary_deduction",
            "delay_increase_or_promotion",
            "dismissal_without_notice",
            "serious_investigation",
            "penalty_notice",
        )
    ]
    units = [
        _unit(
            "orientation",
            "Step 1: Decide the level",
            "⚖️ UAE Legal Position: Example deadline",
            kind="orientation",
            topics=["misconduct_level"],
            required_facts=["misconduct_level"],
            without_jurisdiction=True,
            guards=["rule-4"],
        ),
        _unit(
            "fed-deadline",
            "⚖️ UAE Legal Position: Example deadline",
            "DIFC:",
            scope=FED,
            kind="legal_reference",
            topics=["deadlines"],
        ),
        _unit(
            "difc-deadline",
            "DIFC:",
            "Path A: Minor concerns",
            scope=DIFC,
            kind="legal_reference",
            topics=["deadlines"],
            conditions=["EX-DIFC-DEADLINE"],
            required_facts=["policy_timeframe"],
        ),
        _unit("minor-overview", "Path A: Minor concerns", "Stage 1 - Reminder", pathway=LS),
        _unit(
            "stage-reminder",
            "Stage 1 - Reminder",
            "Stage 2 - Warning",
            pathway=LS,
            stage="reminder",
            topics=["workplace_reminder"],
            conditions=["EX-FED-POLICY"],
            documents=["EX01"],
            options=["opt-reminder", "opt-none"],
        ),
        _unit(
            "stage-warning",
            "Stage 2 - Warning",
            "Pay deductions – expert referral",
            pathway=LS,
            stage="formal_warning",
            topics=["formal_warning"],
            conditions=["EX-FED-WARNING-LABEL"],
            documents=["EX03", "EX02"],
            options=["opt-warning", "opt-suspension", "opt-delay", "opt-deduction", "opt-none"],
            required_facts=["given_opportunity_to_explain"],
            guards=["rule-5"],
            scope_rules=[
                {
                    "match": "Example unpaid suspension (up to 900 days)",
                    "scope": FED,
                    "level": "paragraph",
                }
            ],
            withhold=[
                {
                    "match": "Example salary deduction",
                    "guard": "rule-3",
                    "reason": "superseded:rule-3:deduction_option",
                }
            ],
        ),
        _unit(
            "deduction",
            "Pay deductions – expert referral",
            "Penalty Option – Example unpaid suspension",
            topics=["salary_deduction"],
            conditions=["EX-SHARED-DEDUCTION"],
            options=["opt-deduction"],
            guards=["rule-3"],
            required_facts=["deduction_requested"],
        ),
        _unit(
            "fed-suspension",
            "Penalty Option – Example unpaid suspension",
            "DIFC Example Suspension",
            scope=FED,
            pathway=LS,
            stage="penalty_options",
            topics=["disciplinary_suspension"],
            conditions=["EX-FED-CAP"],
            documents=["EX04"],
            options=["opt-suspension"],
            required_facts=["proposed_suspension_days", "investigation_completed"],
            guards=["rule-8"],
        ),
        _unit(
            "difc-suspension",
            "DIFC Example Suspension",
            "Penalty Option – Example delay",
            scope=DIFC,
            pathway=LS,
            stage="penalty_options",
            topics=["disciplinary_suspension"],
            conditions=["EX-DIFC-SUSPENSION"],
            documents=["EX04"],
            options=["opt-suspension"],
            guards=["rule-8-difc"],
        ),
        _unit(
            "delay",
            "Penalty Option – Example delay",
            "Path B: Serious concerns",
            pathway=LS,
            stage="penalty_options",
            topics=["delay_increase_or_promotion"],
            documents=["EX05"],
            options=["opt-delay"],
        ),
        _unit(
            "serious-overview",
            "Path B: Serious concerns",
            "Stage 1 - Charges",
            pathway=SM,
            topics=["serious_investigation"],
            options=["opt-dismissal", "opt-outcome"],
            guards=["rule-4"],
        ),
        _unit(
            "stage-charges",
            "Stage 1 - Charges",
            "Stage 2 - Outcome",
            pathway=SM,
            stage="written_notification",
            topics=["serious_investigation", "investigative_suspension"],
            documents=["EX06"],
            options=["opt-investigative"],
            guards=["rule-8"],
        ),
        _unit(
            "stage-outcome",
            "Stage 2 - Outcome",
            "Example only. Not legal advice.",
            pathway=SM,
            stage="penalty_notice",
            topics=["penalty_notice", "dismissal_without_notice"],
            conditions=["EX-FED-ESCALATE"],
            documents=["EX07"],
            options=["opt-outcome", "opt-dismissal", "opt-none"],
            required_facts=["investigation_completed", "employer_decision"],
            guards=["rule-4", "rule-5"],
            conflicts=[
                {
                    "match": "The employee must sign this document.",
                    "code": "SOURCE_CONFLICT",
                    "severity": "REVIEW_REQUIRED",
                    "detail": "contradicts the receipt-only rule",
                }
            ],
        ),
        _unit(
            "disclaimer",
            "Example only. Not legal advice.",
            None,
            kind="orientation",
            topics=["misconduct_level"],
            without_jurisdiction=True,
        ),
    ]
    guards = [
        _guard(
            "rule-1",
            "1",
            "jurisdiction_isolation",
            required=["suppress_other_jurisdiction_law"],
            prohibited=["apply_other_jurisdiction_law"],
        ),
        _guard(
            "rule-2", "2", "expert_review_mandatory", status="superseded", workflow="disciplinary"
        ),
        _guard(
            "rule-3",
            "3",
            "expert_review_mandatory",
            workflow="disciplinary",
            topics=["salary_deduction"],
            options=["opt-deduction"],
            required=["refer_to_specialist_review"],
            prohibited=["calculate_deduction", "recommend_deduction_amount", "instruct_payroll"],
            escalation="human_expert_review",
            supersedes=[
                {"kind": "guard", "id": "rule-2"},
                {"kind": "condition", "id": "EX-FED-OLD-DEDUCTION"},
                {"kind": "condition", "id": "EX-FED-PAY-CAUTION"},
            ],
        ),
        _guard(
            "rule-4",
            "4",
            "investigation_first",
            workflow="disciplinary",
            topics=["serious_investigation", "dismissal_without_notice"],
            options=["opt-dismissal"],
            required=["guide_investigation_first"],
            prohibited=["dismiss_on_classification", "treat_stage_completion_as_lawful_dismissal"],
        ),
        _guard(
            "rule-5",
            "5",
            "employer_decision_authority",
            required=["employer_makes_final_decision"],
            prohibited=["select_or_approve_employment_decision"],
        ),
        _guard(
            "rule-6",
            "6",
            "approved_content_only",
            required=["use_approved_sources_only"],
            prohibited=["use_open_web_or_general_model_knowledge"],
        ),
        _guard(
            "rule-7",
            "7",
            "contextual_collection",
            required=["ask_only_material_questions"],
            prohibited=["rigid_questionnaire"],
        ),
        _guard(
            "rule-8",
            "8",
            "suspension_distinction",
            workflow="disciplinary",
            topics=["investigative_suspension", "disciplinary_suspension"],
            required=["distinguish_suspension_types"],
            prohibited=["conflate_suspension_types"],
            select=[{"from": "Investigative suspension is not a penalty.", "to": "DIFC:"}],
        ),
        _guard(
            "rule-8-difc",
            "8",
            "expert_review_mandatory",
            scope=DIFC,
            workflow="disciplinary",
            topics=["disciplinary_suspension"],
            options=["opt-suspension"],
            required=["refer_to_specialist_review"],
            prohibited=["recommend_unpaid_suspension", "generate_unpaid_suspension_notice"],
            escalation="human_expert_review",
            select=[{"from": "DIFC:", "to": None}],
        ),
        _guard(
            "rule-9",
            "9",
            "expert_review_mandatory",
            scope=DIFC,
            workflow="disciplinary",
            topics=["dismissal_without_notice"],
            options=["opt-dismissal"],
            required=["require_expert_clearance"],
            prohibited=["generate_dismissal_without_notice_letter_before_clearance"],
            escalation="human_expert_review",
        ),
        _guard(
            "rule-10",
            "10",
            "deferred_capability",
            status="deferred",
            prohibited=["offer_document_upload", "promise_document_deletion"],
        ),
        _guard("rule-11", "11", "status_note", status="audit_only"),
    ]
    documents = {
        "EX01": {
            "kind": "letter",
            "pathway": LS,
            "stages": ["reminder"],
            "options": ["opt-reminder"],
            "body_scope": "shared",
            "requires_employer_decision": True,
            "requires_completed_investigation": False,
            "requires_employee_response": True,
            "jurisdictions": {
                FED: _dj("eligible_with_gates", ["employer_decision"]),
                DIFC: _dj("eligible_with_gates", ["employer_decision"]),
            },
        },
        "EX02": {
            "kind": "letter",
            "pathway": LS,
            "stages": ["formal_warning"],
            "options": ["opt-warning"],
            "body_scope": "shared",
            "requires_employer_decision": True,
            "requires_completed_investigation": False,
            "requires_employee_response": True,
            "jurisdictions": {
                FED: _dj("eligible_with_gates", ["given_opportunity_to_explain"]),
                DIFC: _dj("eligible_with_gates", ["given_opportunity_to_explain"]),
            },
        },
        "EX03": {
            "kind": "letter",
            "pathway": LS,
            "stages": ["formal_warning"],
            "options": [],
            "body_scope": "shared",
            "requires_employer_decision": False,
            "requires_completed_investigation": False,
            "requires_employee_response": False,
            "jurisdictions": {FED: _dj("eligible_with_gates"), DIFC: _dj("eligible_with_gates")},
        },
        "EX04": {
            "kind": "notice",
            "pathway": LS,
            "stages": ["penalty_options"],
            "options": ["opt-suspension"],
            "body_scope": FED,
            "instruction_scope": FED,
            "requires_employer_decision": True,
            "requires_completed_investigation": True,
            "requires_employee_response": True,
            "prohibited_when": ["jurisdiction:difc", "suspension_type:investigative"],
            "jurisdictions": {
                FED: _dj(
                    "eligible_with_gates",
                    ["investigation_completed", "employer_decision"],
                    ["EX-FED-CAP"],
                ),
                DIFC: _dj("expert_review_required", [], ["EX-DIFC-SUSPENSION"], ["rule-8-difc"]),
            },
        },
        "EX05": {
            "kind": "letter",
            "pathway": LS,
            "stages": ["penalty_options"],
            "options": ["opt-delay"],
            "body_scope": "shared",
            "requires_employer_decision": True,
            "requires_completed_investigation": True,
            "requires_employee_response": True,
            "jurisdictions": {
                FED: _dj("eligible_with_gates", ["employer_decision"]),
                DIFC: _dj("expert_review_required"),
            },
        },
        "EX06": {
            "kind": "email",
            "pathway": SM,
            "stages": ["written_notification"],
            "options": ["opt-investigative"],
            "body_scope": "shared",
            "requires_employer_decision": True,
            "requires_completed_investigation": False,
            "requires_employee_response": False,
            "jurisdictions": {
                FED: _dj("eligible_with_gates", ["misconduct_level"]),
                DIFC: _dj("not_available"),
            },
        },
        "EX07": {
            "kind": "notice",
            "pathway": SM,
            "stages": ["penalty_notice"],
            "options": ["opt-outcome"],
            "body_scope": "shared",
            "requires_employer_decision": True,
            "requires_completed_investigation": True,
            "requires_employee_response": True,
            "prohibited_when": ["outcome:dismissal_without_notice_before_expert_clearance"],
            "jurisdictions": {
                FED: _dj("eligible_with_gates", ["investigation_completed", "employer_decision"]),
                DIFC: _dj("review_required", [], [], ["rule-9"]),
            },
        },
    }
    options = [
        _option(
            "opt-none",
            "no_action",
            None,
            False,
            False,
            False,
            _oj("supported", "employer_may_decide"),
            _oj("supported", "employer_may_decide"),
            ["stage-outcome"],
        ),
        _option(
            "opt-reminder",
            "workplace_reminder",
            LS,
            False,
            False,
            True,
            _oj("supported", "minor", ["EX01"]),
            _oj("supported", "minor", ["EX01"]),
            ["stage-reminder"],
        ),
        _option(
            "opt-warning",
            "written_warning",
            LS,
            True,
            False,
            True,
            _oj("supported", "after_meeting", ["EX02"]),
            _oj("supported", "after_meeting", ["EX02"]),
            ["stage-warning"],
        ),
        _option(
            "opt-suspension",
            "disciplinary_suspension_unpaid",
            LS,
            True,
            True,
            True,
            _oj(
                "supported",
                "fictional_cap",
                ["EX04"],
                ["EX-FED-CAP"],
                ["rule-8"],
                ["proposed_suspension_days"],
            ),
            _oj(
                "review_required",
                "difc_expert_review",
                [],
                ["EX-DIFC-SUSPENSION"],
                ["rule-8-difc"],
                ["proposed_penalty"],
            ),
            ["fed-suspension", "difc-suspension"],
        ),
        _option(
            "opt-delay",
            "delay_increase_or_promotion",
            LS,
            True,
            True,
            True,
            _oj("supported", "scheduled_increase", ["EX05"]),
            _oj("review_required", "difc_expert_review"),
            ["delay"],
        ),
        _option(
            "opt-deduction",
            "salary_deduction",
            None,
            True,
            False,
            True,
            _oj(
                "review_required",
                "expert_referral",
                [],
                ["EX-SHARED-DEDUCTION"],
                ["rule-3"],
                ["deduction_requested"],
            ),
            _oj(
                "review_required",
                "expert_referral",
                [],
                ["EX-SHARED-DEDUCTION"],
                ["rule-3"],
                ["deduction_requested"],
            ),
            ["deduction"],
        ),
        _option(
            "opt-investigative",
            "investigative_suspension",
            SM,
            False,
            False,
            False,
            _oj("supported", "temporary_measure", ["EX06"], [], ["rule-8"], ["suspension_type"]),
            _oj("review_required", "no_difc_source", [], [], ["rule-8"], ["suspension_type"]),
            ["stage-charges"],
        ),
        _option(
            "opt-outcome",
            "disciplinary_penalty_notice",
            SM,
            True,
            True,
            True,
            _oj(
                "supported",
                "employer_selected",
                ["EX07"],
                [],
                ["rule-5"],
                ["investigation_completed", "employer_decision"],
            ),
            _oj("review_required", "difc_penalties_not_in_sources", [], [], ["rule-5"]),
            ["stage-outcome"],
        ),
        _option(
            "opt-dismissal",
            "dismissal_without_notice",
            SM,
            True,
            True,
            True,
            _oj(
                "review_required",
                "escalate_first",
                [],
                ["EX-FED-ESCALATE"],
                ["rule-4"],
                [
                    "investigation_completed",
                    "dismissal_without_notice_considered",
                    "employer_decision",
                ],
            ),
            _oj(
                "review_required",
                "expert_clearance",
                [],
                [],
                ["rule-9", "rule-4"],
                ["investigation_completed", "expert_clearance_documented", "employer_decision"],
            ),
            ["serious-overview", "stage-outcome"],
        ),
    ]
    conditions = {
        "EX-ROUTING-1": {"topics": [], "stages": []},
        "EX-FED-POLICY": {"topics": ["workplace_reminder"], "stages": ["reminder"]},
        "EX-FED-CAP": {"topics": ["disciplinary_suspension"], "stages": ["penalty_options"]},
        "EX-FED-ESCALATE": {"topics": ["dismissal_without_notice"], "stages": ["penalty_notice"]},
        "EX-FED-OLD-DEDUCTION": {"topics": ["salary_deduction"], "stages": []},
        "EX-FED-PAY-CAUTION": {
            "topics": ["investigative_suspension"],
            "stages": ["written_notification"],
            "guidance_withheld": {
                "guard": "rule-3",
                "reason": "superseded:rule-3:deduction_statement",
            },
        },
        "EX-FED-WARNING-LABEL": {"topics": ["formal_warning"], "stages": ["formal_warning"]},
        "EX-DIFC-SUSPENSION": {
            "topics": ["disciplinary_suspension"],
            "stages": ["penalty_options"],
        },
        "EX-SHARED-DEDUCTION": {"topics": ["salary_deduction"], "stages": []},
        "EX-DIFC-DEADLINE": {"topics": ["deadlines"], "stages": []},
    }
    return {
        "schema": "heroos.knowledge-mapping/1",
        "bundle": "example-knowledge",
        "version": "example.1",
        "provenance": "synthetic",
        "approval": "development",
        "notice": {
            "title": "Synthetic knowledge",
            "body": "Fictional content for tests: not HeroOS methodology or legal guidance.",
        },
        "sources": sources,
        "roles": {"playbook": "guide", "rules": "rules", "workbook": "conditions"},
        "owner_decisions": [
            {
                "id": "OD-1",
                "kind": "document_identity",
                "detail": "Actual files win for EX02/EX03.",
                "swapped_codes": {"EX02": "EX03", "EX03": "EX02"},
                "expected_identity": {"EX02": "Example Warning", "EX03": "Example Meeting"},
            },
        ],
        "workbook": {
            "sheets": {
                "Conditions Library": "operational",
                "Legend": "validation",
                "Reference Data": "operational",
                "Structural Findings": "audit_only",
                "Documents": "validation",
                "Blueprint Fields": "validation",
                "Test Company Example": "test_only",
                "Disciplinary Coverage": "audit_only",
            },
            "conditions_sheet": "Conditions Library",
            "reference_sheet": "Reference Data",
            "documents_sheet": "Documents",
            "blueprint_sheet": "Blueprint Fields",
            "legend_sheet": "Legend",
            "workflow_prefixes": {
                "ALL playbooks": "global",
                "Disciplinary": "disciplinary",
                "Probation": "probation",
            },
            "runtime_workflows": ["disciplinary", "global"],
            "single_word_facts": ["headcount"],
            "stale_markers": ["earlier numbering"],
            "reference_data": {
                "EX-FED-LIST": {"runtime": True, "split": "numbered"},
                "EX-OLD-LIMITS": {
                    "runtime": False,
                    "code": "SUPERSEDED",
                    "reason": "expert reference only",
                },
            },
        },
        "workflow": {
            "key": "disciplinary",
            "title": "Example discipline",
            "pathways": [
                {
                    "key": LS,
                    "title": "Minor",
                    "stages": [
                        {"key": "reminder", "title": "Reminder", "kind": "process"},
                        {"key": "formal_warning", "title": "Warning", "kind": "process"},
                        {"key": "penalty_options", "title": "Alternatives", "kind": "outcome"},
                    ],
                },
                {
                    "key": SM,
                    "title": "Serious",
                    "stages": [
                        {
                            "key": "written_notification",
                            "title": "Charges",
                            "kind": "investigation",
                        },
                        {"key": "penalty_notice", "title": "Outcome", "kind": "outcome"},
                    ],
                },
            ],
            "limitations": {FED: [], DIFC: ["difc_coverage_partial"]},
        },
        "topics": topics,
        "facts": facts,
        "fact_aliases": aliases,
        "conditions": conditions,
        "units": units,
        "playbook_excluded": [
            {
                "id": "cover",
                "from": "Example Conduct Guide",
                "to": "Step 1: Decide the level",
                "role": "decorative",
                "reason": "cover",
            }
        ],
        "playbook_references": [
            {"paragraph": "11:Doc 02", "means": "EX03", "decision": "OD-1", "basis": "the meeting"},
            {"paragraph": "11:Doc 03", "means": "EX02", "decision": "OD-1", "basis": "the warning"},
        ],
        "rule_references": [],
        "guards": guards,
        "documents": documents,
        "document_checks": [
            {
                "id": "ex06-article",
                "document": "EX06",
                "text": "Article 905",
                "claim": "workbook: EX06 still cites fictional Article 905",
                "if_absent": {
                    "code": "STALE_METADATA",
                    "severity": "WARNING",
                    "meaning": "already fixed",
                },
                "if_present": {
                    "code": "REVIEW_REQUIRED",
                    "severity": "REVIEW_REQUIRED",
                    "meaning": "still present",
                },
            },
        ],
        "options": options,
        "engine_links": [
            {"engine": "intake", "rule": "case_jurisdiction", "condition": "EX-ROUTING-1"},
            {"engine": "intake", "rule": "policy_awareness", "condition": "EX-FED-POLICY"},
        ],
        "blueprint_fields": {
            "headcount": {"treatment": "blueprint", "blueprint": "employee_count"},
            "operating_jurisdictions": {
                "treatment": "blueprint",
                "blueprint": "jurisdiction.employment_jurisdiction",
            },
        },
        "document_code": "EX\\d{2}(?:-OLD)?",
        "template_letter_starts": ["Date:", "Subject:"],
    }


def write_mapping(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    return path
