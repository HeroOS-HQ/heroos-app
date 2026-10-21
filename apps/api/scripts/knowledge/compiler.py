"""Compiling a source package into a knowledge bundle and a validation report.

``compile_package(source_dir, mapping_path)`` runs the whole pipeline and
returns the bundle (``None`` when any finding is ``FATAL``) and the report.
It never writes: ``__main__`` does, outside the repository and the sources.

Normalization the compiler is allowed to make, each one recorded as a
finding:

- **Document identity** comes from the actual template files. A reference
  in another source that names the wrong code for a document is a
  ``SOURCE_MISMATCH``. Where an owner decision covers that code, the runtime
  text uses the actual code (the source keeps its own; ``raw`` keeps it for
  audit); otherwise the referencing unit needs review.
- **Explicit supersession**: text a rule explicitly overrides is withheld
  from the runtime and kept for traceability. A mapping may only withhold
  text for a guard whose rule actually says it overrides or supersedes.
- **Jurisdiction scoping**: text is split where the jurisdiction changes,
  never reworded (``scripts.knowledge.text``).
- **Quarantine**: a route whose sources conflict or whose mapping is broken
  stays in the bundle for traceability and is withheld from automatic use.
"""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from app.knowledge.bundle import (
    SCHEMA,
    KnowledgeBundleError,
    canonical_json,
    parse_knowledge_bundle,
    runtime_bundle_digest,
    source_package_digest,
)
from scripts.docx_reader import DocxRefused
from scripts.knowledge import playbook as pb
from scripts.knowledge import workbook as wb
from scripts.knowledge.findings import Findings, Ref
from scripts.knowledge.sources import (
    SourceFile,
    inventory,
    manifest_entry,
    match_sources,
    normalize,
    sha256_text,
)
from scripts.knowledge.templates import Template, read_template, same_document, significant
from scripts.knowledge.text import segment
from scripts.xlsx_reader import XlsxRefused, read_xlsx

COMPILER_VERSION: Final = "knowledge-compiler/1"
MAPPING_SCHEMA: Final = "heroos.knowledge-mapping/1"
MAPPING_KEYS: Final = (
    "schema", "bundle", "version", "provenance", "approval", "notice", "sources", "roles",
    "owner_decisions", "workbook", "workflow", "topics", "facts", "fact_aliases", "conditions",
    "units", "playbook_excluded", "playbook_references", "rule_references", "guards",
    "documents", "document_checks", "options", "engine_links", "blueprint_fields",
    "document_code", "template_letter_starts",
)  # fmt: skip


class MappingError(ValueError):
    """The compile mapping itself is malformed (a fixed message, never source content)."""


@dataclass(slots=True)
class CompileResult:
    bundle: dict[str, Any] | None
    bundle_bytes: bytes | None
    report: dict[str, Any]
    findings: Findings


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise MappingError(f"duplicate key in mapping: {key}")
        data[key] = value
    return data


def load_mapping(path: Path) -> dict[str, Any]:
    mapping = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates)
    if not isinstance(mapping, dict) or mapping.get("schema") != MAPPING_SCHEMA:
        raise MappingError("not a knowledge mapping (schema)")
    missing = [k for k in MAPPING_KEYS if k not in mapping]
    unknown = [k for k in mapping if k not in MAPPING_KEYS]
    if missing or unknown:
        raise MappingError(f"mapping keys: missing {missing}, unknown {unknown}")
    return mapping


def bundle_bytes(bundle: Mapping[str, object]) -> bytes:
    """The bundle file: canonical JSON, indented for review, one trailing newline."""
    text = json.dumps(bundle, sort_keys=True, indent=1, ensure_ascii=False)
    return f"{text}\n".encode()


class Compilation:
    """One run. Holds the sources, the mapping and every finding."""

    def __init__(self, source_dir: Path, mapping: dict[str, Any]) -> None:
        self.source_dir = source_dir
        self.mapping = mapping
        self.findings = Findings()
        self.files: dict[str, SourceFile] = {}
        self.templates: dict[str, Template] = {}
        self.references: dict[str, list[dict[str, str]]] = {}
        self.quarantine: list[dict[str, str]] = []
        decisions = mapping["owner_decisions"]
        self.swaps: dict[str, str] = {}
        self.decision_for_swap = ""
        for decision in decisions:
            if decision.get("kind") == "document_identity":
                self.swaps.update(decision["swapped_codes"])
                self.decision_for_swap = decision["id"]
        self.guard_overrides: set[str] = set()
        # The library's document-code pattern is private: it comes from the mapping.
        code = mapping["document_code"]
        self.doc_code = re.compile(rf"\b({code})\b")
        self.doc_pointer = pb.doc_pointer(code)
        self.code_in_parens = pb.code_in_parens(code)
        self.mapping_sha256 = ""
        self.workbook_document_conditions: dict[str, list[str]] = {}
        self.rule_overrides: set[str] = set()
        self.guard_rules: dict[str, str] = {}

    # --- helpers ------------------------------------------------------------------------

    def source_ref(self, source_id: str, location: str, text: str) -> Ref:
        return Ref(source_id, location, sha256_text(text))

    def file_ref(self, source_id: str) -> Ref:
        file = self.files[source_id]
        return Ref(source_id, "file", file.sha256)

    def add_reference(self, document_id: str, reference: dict[str, str]) -> None:
        refs = self.references.setdefault(document_id, [])
        if reference not in refs:
            refs.append(reference)

    def quarantine_route(self, kind: str, item: str, reason: str, finding: str) -> None:
        entry = {"kind": kind, "id": item, "reason": reason, "finding": finding}
        if entry not in self.quarantine:
            self.quarantine.append(entry)

    def identify(self, title: str) -> str | None:
        """The actual document a title names, if exactly one (the same words first)."""
        words = significant(title)
        equal = [
            d for d, t in self.templates.items()
            if words in (significant(t.title), significant(t.filename_title))
        ]  # fmt: skip
        if len(equal) == 1:
            return equal[0]
        hits = [d for d, t in self.templates.items() if same_document(title, t.title)]
        hits = hits or [
            d for d, t in self.templates.items() if same_document(title, t.filename_title)
        ]
        return hits[0] if len(hits) == 1 else None

    def normalize_codes(self, text: str, source_id: str, location: str, subject: str) -> str:
        """Workbook-numbered document codes in runtime text, mapped to the actual files."""

        def replace(match: Any) -> str:
            code = match.group(1)
            actual = self.swaps.get(code)
            if actual is None:
                return str(code)
            self.findings.add(
                "SOURCE_MISMATCH", "WARNING", "condition", subject, f"code-{code}",
                f"{code} here follows the reversed numbering; normalized to {actual} "
                f"(owner decision {self.decision_for_swap})",
                (self.source_ref(source_id, location, text),),
            )  # fmt: skip
            self.add_reference(actual, {
                "source_id": source_id, "location": location, "cited_id": code,
                "cited_title": "", "resolution": "source_mismatch_resolved",
            })  # fmt: skip
            return actual

        return self.doc_code.sub(replace, text)

    # --- the pipeline ---------------------------------------------------------------------

    def run(self) -> CompileResult:
        mapping = self.mapping
        files = inventory(self.source_dir)
        self.files = match_sources(mapping["sources"], files, self.findings)
        manifest = [
            manifest_entry(entry, self.files[entry["source_id"]])
            for entry in sorted(mapping["sources"], key=lambda e: e["source_id"])
            if entry["source_id"] in self.files
        ]
        report: dict[str, Any] = {
            "compiler": COMPILER_VERSION,
            "source_package": {
                "directory_name": self.source_dir.name,
                "files_found": [f.relative for f in files],
                "files_expected": sorted(e["filename"] for e in mapping["sources"]),
                "files_missing": sorted(
                    e["filename"] for e in mapping["sources"] if e["source_id"] not in self.files
                ),
                "checksums": {f.relative: f.sha256 for f in files},
                "roles": {e["filename"]: e["runtime_role"] for e in mapping["sources"]},
            },
        }
        if self.findings.fatal():
            return self.finish(report, manifest, None)
        try:
            runtime = self.compile_runtime(report)
        except (DocxRefused, XlsxRefused) as error:
            self.findings.add(
                "INVALID_ROW", "FATAL", "source", error.location or "source", error.code,
                f"a source file was refused by the reader: {error.code}",
            )  # fmt: skip
            runtime = None
        return self.finish(report, manifest, runtime)

    def compile_runtime(self, report: dict[str, Any]) -> dict[str, Any] | None:
        mapping = self.mapping
        roles = mapping["roles"]
        for entry in mapping["sources"]:
            if entry["source_type"] == "template" and entry["source_id"] in self.files:
                self.read_template(entry)
        self.check_owner_decisions()
        workbook = read_xlsx(self.files[roles["workbook"]].path)
        playbook = pb.read_paragraphs(self.files[roles["playbook"]].path, nested_tables=True)
        rules_doc = pb.read_paragraphs(self.files[roles["rules"]].path, nested_tables=False)
        rules = {r.number: r for r in pb.read_rules(rules_doc)}

        conditions, slice_ids = self.compile_conditions(workbook, report)
        self.check_documents_sheet(workbook, report, set(c["id"] for c in conditions))
        self.run_document_checks()
        guards = self.compile_guards(rules, report)
        units = self.compile_units(playbook, report, {g["id"] for g in mapping["guards"]})
        self.check_rule_references(rules)
        documents = self.compile_documents(set(slice_ids))
        reference = self.compile_reference_data(workbook, set(slice_ids), report)
        self.check_blueprint_fields(workbook, report)
        self.report_audit_sheets(workbook, report)
        facts = self.compile_facts(conditions)
        options = [
            self.compile_option(item, units, guards, conditions) for item in mapping["options"]
        ]
        runtime = {
            "workflows": [mapping["workflow"]],
            "jurisdictions": ["uae_federal", "difc"],
            "topics": mapping["topics"],
            "facts": facts,
            "units": units,
            "conditions": conditions,
            "guards": guards,
            "documents": documents,
            "options": options,
            "reference_data": reference,
            "quarantine": sorted(self.quarantine, key=lambda q: (q["kind"], q["id"])),
            "engine_links": mapping["engine_links"],
        }
        report["implementation_rules"] = {
            "rules": len(rules),
            "guards": len(guards),
            "operational_guards": sorted(g["id"] for g in guards if g["status"] == "operational"),
            "superseded": sorted(g["id"] for g in guards if g["status"] == "superseded"),
            "deferred_capabilities": sorted(g["id"] for g in guards if g["status"] == "deferred"),
            "audit_only": sorted(g["id"] for g in guards if g["status"] == "audit_only"),
            "explicit_supersessions": [
                {"guard": g["id"], "rule": g["rule"], "supersedes": g["supersedes"]}
                for g in guards
                if g["supersedes"]
            ],
        }
        report["jurisdiction"] = self.jurisdiction_coverage(runtime)
        return runtime

    # --- owner decisions ------------------------------------------------------------------

    def check_owner_decisions(self) -> None:
        """An owner's identity decision must hold for the actual files, every run."""
        for decision in self.mapping["owner_decisions"]:
            for doc_id, title in decision.get("expected_identity", {}).items():
                template = self.templates.get(doc_id)
                holds = template is not None and same_document(title, template.title)
                self.findings.add(
                    "OWNER_DECISION", "INFO" if holds else "FATAL", "document", doc_id,
                    decision["id"],
                    f"owner decision {decision['id']}: {doc_id} is '{title}' - "
                    + ("verified against the actual file" if holds
                       else "the actual file disagrees"),
                    () if template is None else (self.file_ref(doc_id),),
                )  # fmt: skip

    # --- templates ------------------------------------------------------------------------

    def read_template(self, entry: Mapping[str, Any]) -> None:
        source_id = entry["source_id"]
        template = read_template(
            self.files[source_id].path,
            self.mapping["document_code"],
            tuple(self.mapping["template_letter_starts"]),
        )
        if template.document_id != entry["document_id"] or template.document_id != source_id:
            self.findings.add(
                "SOURCE_MISMATCH", "FATAL", "document", source_id, "filename-code",
                "template filename code does not match the mapping", (self.file_ref(source_id),),
            )  # fmt: skip
        if not same_document(template.filename_title, template.title):
            self.findings.add(
                "SOURCE_MISMATCH", "FATAL", "document", source_id, "file-title",
                "template filename title and body title name different documents",
                (self.file_ref(source_id),),
            )  # fmt: skip
        if template.flags:
            self.findings.add(
                "REVIEW_REQUIRED", "INFO", "document", source_id, "reader-flags",
                f"reader flags: {', '.join(template.flags)}", (self.file_ref(source_id),),
            )  # fmt: skip
        self.templates[source_id] = template

    # --- conditions -----------------------------------------------------------------------

    def compile_conditions(
        self, workbook: Any, report: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        mapping = self.mapping
        settings = mapping["workbook"]
        source_id = mapping["roles"]["workbook"]
        rows = wb.read_conditions(
            workbook,
            source_id,
            settings["conditions_sheet"],
            settings["workflow_prefixes"],
            frozenset(settings["single_word_facts"]),
            self.findings,
        )
        runtime_workflows = set(settings["runtime_workflows"])
        in_slice = [r for r in rows if r.workflow in runtime_workflows]
        report["conditions"] = {
            "all": wb.condition_counts(rows),
            "runtime_slice": wb.condition_counts(in_slice),
            "outside_runtime_slice": sorted(
                f"{r.id} ({r.workflow})" for r in rows if r.workflow not in runtime_workflows
            ),
            "duplicates": sorted(
                f.subject_id for f in self.findings.items if f.code == "DUPLICATE_ID"
            ),
            "malformed_actions": sorted(
                f.subject_id
                for f in self.findings.items
                if f.code == "MALFORMED_ACTION" and f.severity != "INFO"
            ),  # fmt: skip
        }
        for row in rows:
            if row.workflow not in runtime_workflows:
                self.findings.add(
                    "COVERAGE", "INFO", "condition", row.id, "outside-runtime-slice",
                    f"workflow {row.workflow}: audited, not published (sources for that "
                    "workflow are not in this package)",
                    (row.ref,),
                )  # fmt: skip
        overrides: dict[str, Any] = mapping["conditions"]
        unknown = set(overrides) - {r.id for r in in_slice}
        if unknown:
            raise MappingError(f"mapping names Conditions outside the slice: {sorted(unknown)}")
        aliases: dict[str, str | None] = mapping["fact_aliases"]
        out: list[dict[str, Any]] = []
        for row in in_slice:
            if not row.valid:
                continue
            cells = row.row.cells
            override = overrides.get(row.id, {})
            if not override:
                self.findings.add(
                    "COVERAGE", "WARNING", "condition", row.id, "unmapped",
                    "no topics or stages mapped: reachable only by id or as a global rule",
                    (row.ref,),
                )  # fmt: skip
            facts: list[str] = []
            for token in row.tokens:
                if token not in aliases:
                    self.findings.add(
                        "UNMAPPED_FACT", "WARNING", "condition", row.id, f"token-{token}",
                        f"field token {token!r} is not in the fact catalog", (row.ref,),
                    )  # fmt: skip
                elif aliases[token] is not None and aliases[token] not in facts:
                    facts.append(str(aliases[token]))
            facts += [f for f in override.get("facts", []) if f not in facts]
            location = f"sheet {settings['conditions_sheet']} row {row.row.number}"
            guidance = self.normalize_codes(cells["guidance"], source_id, location, row.id)
            trigger = self.normalize_codes(cells["trigger"], source_id, location, row.id)
            withheld = override.get("guidance_withheld")
            guidance_status = "available"
            limitations = list(override.get("limitations", []))
            if withheld is not None:
                self.require_override(withheld["guard"], f"condition {row.id}")
                guidance_status = "withheld"
                limitations.append(withheld["reason"])
                self.findings.add(
                    "SUPERSEDED", "INFO", "condition", row.id, "guidance",
                    f"guidance withheld: {withheld['reason']} (explicit supersession)", (row.ref,),
                )  # fmt: skip
            note = cells.get("enforcement_note", "")
            if any(marker in note for marker in settings["stale_markers"]):
                self.findings.add(
                    "STALE_METADATA", "WARNING", "condition", row.id, "document-numbering",
                    "row text uses the earlier document numbering (its own note says so)",
                    (row.ref,),
                )  # fmt: skip
            if row.citation_status == "needs_legal_review" and row.enforcement_status == "active":
                self.findings.add(
                    "REVIEW_REQUIRED", "REVIEW_REQUIRED", "condition", row.id, "legal-review",
                    "active with needs_legal_review: configured action kept, legal basis "
                    "not presented as confirmed",
                    (row.ref,),
                )  # fmt: skip
            assert row.scope is not None and row.action_policy is not None
            out.append(
                {
                    "id": row.id,
                    "workflow": row.workflow,
                    "scope": row.scope,
                    "type": row.type,
                    "title": cells["title"].strip(),
                    "segments": segment([guidance], row.scope, override.get("scope_rules", [])),
                    "guidance_status": guidance_status,
                    "trigger": trigger.strip(),
                    "enforcement_status": row.enforcement_status,
                    "citation_status": row.citation_status,
                    "action_policy": row.action_policy,
                    "required_facts": facts,
                    "topics": override.get("topics", []),
                    "stages": override.get("stages", []),
                    "shared_across": cells.get("shared_across", "").strip(),
                    "limitations": limitations,
                    "source_ref": row.ref.data(),
                    "raw": {k: cells.get(k, "") for k in wb.CONDITION_COLUMNS},
                }
            )
        return out, [r.id for r in in_slice]

    def require_override(self, guard_id: str, where: str) -> None:
        """Text may be withheld only under a rule that explicitly overrides or supersedes."""
        guard = next((g for g in self.mapping["guards"] if g["id"] == guard_id), None)
        if guard is None:
            raise MappingError(f"{where}: withheld under unknown guard {guard_id}")
        self.guard_overrides.add(guard_id)

    # --- the Documents sheet ------------------------------------------------------------

    def check_documents_sheet(
        self, workbook: Any, report: dict[str, Any], condition_ids: set[str]
    ) -> None:
        settings = self.mapping["workbook"]
        source_id = self.mapping["roles"]["workbook"]
        sheet = workbook.sheet(settings["documents_sheet"])
        if sheet is None:
            self.findings.add(
                "MISSING_SOURCE", "FATAL", "sheet", settings["documents_sheet"], "present",
                "documents sheet missing",
            )  # fmt: skip
            return
        _, rows = wb.sheet_rows(sheet)
        all_ids = self.condition_ids(workbook)
        mappings: dict[str, list[str]] = {}
        sheet_report: list[dict[str, Any]] = []
        for row in rows:
            doc_id = row.cells.get("doc_id", "").strip()
            title = row.cells.get("title", "").strip()
            ref = wb.row_ref(source_id, settings["documents_sheet"], row)
            related = wb.split_ids(row.cells.get("related_conditions", ""))
            status = row.cells.get("status", "").strip()
            entry: dict[str, Any] = {"doc_id": doc_id, "title": title, "status": status}
            unknown = [c for c in related if c not in all_ids]
            if unknown:
                self.findings.add(
                    "BROKEN_MAPPING", "WARNING", "document", doc_id, "unknown-conditions",
                    f"related conditions not in the library: {', '.join(unknown)}", (ref,),
                )  # fmt: skip
            if doc_id in self.templates:
                actual = self.templates[doc_id].title
                if same_document(title, actual):
                    resolution = (
                        "consistent" if normalize(title) == normalize(actual) else "title_variant"
                    )
                    target = doc_id
                else:
                    target = self.identify(title) or ""
                    covered = self.swaps.get(doc_id) == target
                    resolution = "source_mismatch_resolved" if covered else "source_mismatch"
                    self.findings.add(
                        "SOURCE_MISMATCH",
                        "WARNING" if covered else "REVIEW_REQUIRED",
                        "document", doc_id, "workbook-title",
                        f"workbook names {doc_id} '{title}', but the actual {doc_id} file is "
                        f"'{actual}'"
                        + (f"; the title is actual {target}" if target else "")
                        + (f" (owner decision {self.decision_for_swap}: actual files win)"
                           if covered else ""),
                        (ref, self.file_ref(doc_id)),
                    )  # fmt: skip
                if target:
                    self.add_reference(target, {
                        "source_id": source_id,
                        "location": f"sheet {settings['documents_sheet']} row {row.number}",
                        "cited_id": doc_id, "cited_title": title, "resolution": resolution,
                    })  # fmt: skip
                    mappings[target] = [c for c in related if c in condition_ids]
                entry["actual"] = target
                entry["resolution"] = resolution
            else:
                self.findings.add(
                    "COVERAGE", "INFO", "document", doc_id or f"row-{row.number}", "no-file",
                    f"listed in the workbook (status: {status}) with no template file in the "
                    "package: not in the catalog",
                    (ref,),
                )  # fmt: skip
            if doc_id in self.templates and status != "active":
                entry["status_note"] = status
            sheet_report.append(entry)
        # The same non-empty set of related Conditions on two documents: one is a copy.
        by_set: dict[tuple[str, ...], list[str]] = {}
        for doc, related in mappings.items():
            if related:
                by_set.setdefault(tuple(sorted(related)), []).append(doc)
        for related_set, docs in by_set.items():
            if len(docs) < 2:
                continue
            for doc in docs:
                title_words = {w for w in normalize(self.templates[doc].title).lower().split()}
                overlap = any(
                    word.lower() in title_words
                    for cid in related_set
                    for word in cid.split("-")
                    if len(word) > 3
                )
                if not overlap:
                    finding = self.findings.add(
                        "BROKEN_MAPPING", "QUARANTINED", "document", doc, "related-conditions",
                        f"related conditions copied from {', '.join(d for d in docs if d != doc)}"
                        f" ({', '.join(related_set)}) and unrelated to this document; not used",
                        (self.file_ref(doc),),
                    )  # fmt: skip
                    self.quarantine_route(
                        "document", doc, "broken_mapping:related_conditions", finding.id
                    )
                    mappings[doc] = []
        self.workbook_document_conditions = mappings
        report["documents"] = {"workbook_rows": sheet_report}

    def condition_ids(self, workbook: Any) -> set[str]:
        """Every Condition id in the library, inside the runtime slice or not."""
        sheet = workbook.sheet(self.mapping["workbook"]["conditions_sheet"])
        rows = [] if sheet is None else wb.sheet_rows(sheet)[1]
        return {r.cells.get("id", "").strip() for r in rows if r.cells.get("id", "").strip()}

    def run_document_checks(self) -> None:
        for check in self.mapping["document_checks"]:
            doc = check["document"]
            template = self.templates.get(doc)
            if template is None:
                raise MappingError(f"document check names unknown document {doc}")
            present = normalize(check["text"]).lower() in normalize(template.text).lower()
            outcome = check["if_present"] if present else check["if_absent"]
            self.findings.add(
                outcome["code"], outcome["severity"], "document", doc, check["id"],
                f"{check['claim']} - the actual file "
                f"{'contains' if present else 'does not contain'} "
                f"the text: {outcome['meaning']}",
                (self.file_ref(doc),),
            )  # fmt: skip

    # --- Playbook units -----------------------------------------------------------------

    def compile_units(
        self, paragraphs: pb.Paragraphs, report: dict[str, Any], guard_ids: set[str]
    ) -> list[dict[str, Any]]:
        mapping = self.mapping
        source_id = mapping["roles"]["playbook"]
        covered: list[int | None] = [None] * len(paragraphs.texts)
        out: list[dict[str, Any]] = []

        def claim(first: int, last: int, owner: str) -> None:
            for index in range(first, last):
                if covered[index] is not None:
                    raise MappingError(f"paragraph {index} claimed twice ({owner})")
                covered[index] = 1

        for excluded in mapping["playbook_excluded"]:
            found = pb.span(paragraphs, excluded["from"], excluded.get("to"))
            if isinstance(found, str):
                self.findings.add(
                    "COVERAGE", "FATAL", "playbook", excluded["id"], found,
                    "excluded span anchor no longer matches the Playbook",
                )  # fmt: skip
                continue
            claim(*found, excluded["id"])
            span_ref = Ref(
                source_id,
                f"paragraphs {found[0]}-{found[1] - 1}",
                pb.span_sha256(paragraphs, *found),
            )
            self.findings.add(
                "COVERAGE", "INFO", "playbook", excluded["id"], "excluded",
                f"{excluded['role']}: {excluded['reason']}", (span_ref,),
            )  # fmt: skip
            extra = excluded.get("finding")
            if extra is not None:
                self.findings.add(
                    extra["code"], extra["severity"], "playbook", excluded["id"], extra["check"],
                    extra["detail"], (span_ref,),
                )  # fmt: skip
        references: dict[str, dict[str, Any]] = {
            r["paragraph"]: r for r in mapping["playbook_references"]
        }
        for unit in mapping["units"]:
            found = pb.span(paragraphs, unit["from"], unit.get("to"))
            if isinstance(found, str):
                self.findings.add(
                    "COVERAGE", "FATAL", "unit", unit["id"], found,
                    "unit anchor no longer matches the Playbook",
                )  # fmt: skip
                continue
            first, last = found
            claim(first, last, unit["id"])
            ref = Ref(
                source_id, f"paragraphs {first}-{last - 1}", pb.span_sha256(paragraphs, first, last)
            )
            status = unit.get("status", "operational")
            texts: list[str] = []
            for index in range(first, last):
                text = paragraphs.texts[index]
                withheld = next(
                    (
                        w
                        for w in unit.get("withhold", [])
                        if normalize(text).startswith(normalize(w["match"]))
                    ),
                    None,
                )
                conflict = next(
                    (
                        c
                        for c in unit.get("conflicts", [])
                        if normalize(text).startswith(normalize(c["match"]))
                    ),
                    None,
                )
                if conflict is not None:
                    # Sources disagree and nothing explicitly settles it: kept out, reported.
                    self.findings.add(
                        conflict["code"], conflict["severity"], "unit", unit["id"],
                        f"conflict-{index}",
                        f"paragraph {index} withheld: {conflict['detail']}",
                        (Ref(source_id, f"paragraph {index}", sha256_text(text)),),
                    )  # fmt: skip
                    continue
                if withheld is not None:
                    self.require_override(withheld["guard"], f"unit {unit['id']}")
                    self.findings.add(
                        "SUPERSEDED", "INFO", "unit", unit["id"], f"withheld-{index}",
                        f"paragraph {index} withheld: {withheld['reason']} (explicit supersession)",
                        (Ref(source_id, f"paragraph {index}", sha256_text(text)),),
                    )  # fmt: skip
                    continue
                text, status = self.normalize_pointers(text, index, unit, references, status)
                texts.append(text)
            for g in unit.get("guards", []):
                if g not in guard_ids:
                    raise MappingError(f"unit {unit['id']} names unknown guard {g}")
            out.append(
                {
                    "id": unit["id"],
                    "workflow": mapping["workflow"]["key"],
                    "pathway": unit.get("pathway"),
                    "stage": unit.get("stage"),
                    "topics": unit.get("topics", []),
                    "scope": unit["scope"],
                    "kind": unit["kind"],
                    "title": unit["title"],
                    "segments": segment(
                        texts, unit["scope"], unit.get("scope_rules", []), unit.get("regions", [])
                    ),
                    "required_facts": unit.get("required_facts", []),
                    "guards": unit.get("guards", []),
                    "conditions": unit.get("conditions", []),
                    "documents": unit.get("documents", []),
                    "options": unit.get("options", []),
                    "without_jurisdiction": unit.get("without_jurisdiction", False),
                    "status": status,
                    "limitations": unit.get("limitations", []),
                    "source_ref": ref.data(),
                }
            )
        unassigned = [i for i, c in enumerate(covered) if c is None]
        for index in unassigned:
            self.findings.add(
                "COVERAGE", "WARNING", "playbook", f"paragraph-{index}", "unassigned",
                "Playbook paragraph in no unit and no excluded span",
                (Ref(source_id, f"paragraph {index}", sha256_text(paragraphs.texts[index])),),
            )  # fmt: skip
        report["playbook"] = {
            "paragraphs": len(paragraphs.texts),
            "units": len(out),
            "excluded_spans": len(mapping["playbook_excluded"]),
            "unassigned_paragraphs": unassigned,
            "pathways": sorted({u["pathway"] or "general" for u in out}),
            "stages": [s["key"] for p in mapping["workflow"]["pathways"] for s in p["stages"]],
            "reader_flags": list(paragraphs.flags),
        }
        return out

    def normalize_pointers(
        self, text: str, index: int, unit: Mapping[str, Any],
        references: Mapping[str, Mapping[str, Any]], status: str,
    ) -> tuple[str, str]:  # fmt: skip
        """Document pointers in a Playbook paragraph, checked against the actual files."""
        source_id = self.mapping["roles"]["playbook"]
        location = f"paragraph {index}"
        ref = Ref(source_id, location, sha256_text(text))
        for match in self.doc_pointer.finditer(text):
            code = match.group(1)
            title, target = match.group(2).strip(), None
            for candidate in pb.title_candidates(match.group(2)):
                found = self.identify(candidate)
                if found is not None:
                    title, target = candidate, found
                    break
            if target == code:
                resolution = (
                    "consistent"
                    if normalize(title) == normalize(self.templates[code].title)
                    else "title_variant"
                )
                self.add_reference(code, {
                    "source_id": source_id, "location": location, "cited_id": code,
                    "cited_title": title, "resolution": resolution,
                })  # fmt: skip
                continue
            covered = target is not None and self.swaps.get(code) == target
            self.findings.add(
                "SOURCE_MISMATCH", "WARNING" if covered else "REVIEW_REQUIRED", "unit",
                str(unit["id"]), f"pointer-{index}-{code}",
                f"Playbook points to {code} for '{title}', which is actual {target or 'no file'}"
                + (f"; normalized under owner decision {self.decision_for_swap}"
                   if covered else ""),
                (ref,),
            )  # fmt: skip
            if target is not None:
                self.add_reference(target, {
                    "source_id": source_id, "location": location, "cited_id": code,
                    "cited_title": title,
                    "resolution": "source_mismatch_resolved" if covered else "source_mismatch",
                })  # fmt: skip
            if covered and target is not None:
                text = text.replace(match.group(0), match.group(0).replace(code, target, 1), 1)
            else:
                status = "review_required"
        bare = [m.group(0) for m in pb.BARE_DOC.finditer(text)] + [
            m.group(0) for m in self.code_in_parens.finditer(text)
        ]
        for cited in bare:
            meaning = references.get(f"{index}:{cited}")
            if meaning is None:
                self.findings.add(
                    "SOURCE_MISMATCH", "REVIEW_REQUIRED", "unit", str(unit["id"]),
                    f"bare-{index}-{cited}", f"untitled document reference '{cited}' unresolved",
                    (ref,),
                )  # fmt: skip
                status = "review_required"
                continue
            actual = meaning["means"]
            code_cited = cited.replace("Doc ", "").strip("()")
            resolution = "consistent" if code_cited == actual else "source_mismatch_resolved"
            if resolution != "consistent":
                self.findings.add(
                    "SOURCE_MISMATCH", "WARNING", "unit", str(unit["id"]),
                    f"bare-{index}-{code_cited}",
                    f"'{cited}' means actual {actual} ({meaning['basis']}); normalized under owner "
                    f"decision {meaning['decision']}",
                    (ref,),
                )  # fmt: skip
                text = text.replace(cited, cited.replace(code_cited, actual), 1)
            self.add_reference(actual, {
                "source_id": source_id, "location": location, "cited_id": code_cited,
                "cited_title": "", "resolution": resolution,
            })  # fmt: skip
        return text, status

    # --- Implementation Rules --------------------------------------------------------------

    def compile_guards(
        self, rules: Mapping[str, pb.Rule], report: dict[str, Any]
    ) -> list[dict[str, Any]]:
        source_id = self.mapping["roles"]["rules"]
        out: list[dict[str, Any]] = []
        mapped_rules: set[str] = set()
        for guard in self.mapping["guards"]:
            rule = rules.get(str(guard["rule"]))
            if rule is None:
                self.findings.add(
                    "COVERAGE", "FATAL", "guard", guard["id"], "rule-missing",
                    f"rule {guard['rule']} is not in the Implementation Rules",
                )  # fmt: skip
                continue
            mapped_rules.add(rule.number)
            selected = pb.select(rule.paragraphs, guard.get("select", []))
            if isinstance(selected, str):
                self.findings.add(
                    "COVERAGE", "FATAL", "guard", guard["id"], selected,
                    "guard paragraph range no longer matches its rule",
                )  # fmt: skip
                continue
            ref = Ref(source_id, f"rule {rule.number}", rule.sha256)
            out.append(
                {
                    "id": guard["id"],
                    "rule": rule.number,
                    "title": guard.get("title") or rule.title,
                    "kind": guard["kind"],
                    "workflow": guard["workflow"],
                    "scope": guard["scope"],
                    "topics": guard.get("topics", []),
                    "options": guard.get("options", []),
                    "required": guard.get("required", []),
                    "prohibited": guard.get("prohibited", []),
                    "escalation": guard.get("escalation", "none"),
                    "supersedes": guard.get("supersedes", []),
                    "status": guard["status"],
                    "segments": segment(
                        selected,
                        guard["scope"],
                        guard.get("scope_rules", []),
                        guard.get("regions", []),
                    ),
                    "source_ref": ref.data(),
                }
            )
            if guard["status"] == "deferred":
                self.findings.add(
                    "DEFERRED_CAPABILITY", "INFO", "guard", guard["id"], "deferred",
                    f"rule {rule.number}: capability deferred, not active in this runtime", (ref,),
                )  # fmt: skip
        for number in sorted(set(rules) - mapped_rules, key=int):
            self.findings.add(
                "COVERAGE", "FATAL", "rule", number, "unmapped",
                "Implementation Rule not classified by any guard (operational, superseded, "
                "deferred or audit-only)",
            )  # fmt: skip
        # Explicit supersession, as the rules state it.
        by_rule: dict[str, list[dict[str, Any]]] = {}
        for guard in out:
            by_rule.setdefault(guard["rule"], []).append(guard)
        for rule in rules.values():
            for successor in rule.superseded_by:
                old = by_rule.get(rule.number, [])
                new = by_rule.get(successor, [])
                listed = any(
                    {"kind": "guard", "id": g["id"]} in n["supersedes"] for g in old for n in new
                )
                if not old or any(g["status"] != "superseded" for g in old) or not listed:
                    self.findings.add(
                        "SOURCE_CONFLICT", "FATAL", "rule", rule.number, "supersession",
                        f"rule {rule.number} states it is superseded by rule {successor}; the "
                        "mapping must mark it superseded and list it under the successor",
                    )  # fmt: skip
                else:
                    self.findings.add(
                        "SUPERSEDED", "INFO", "rule", rule.number, "explicit",
                        f"rule {rule.number} explicitly superseded by rule {successor}",
                        (Ref(source_id, f"rule {rule.number}", rule.sha256),),
                    )  # fmt: skip
        for guard in out:
            if guard["status"] == "superseded" and not any(
                {"kind": "guard", "id": guard["id"]} in g["supersedes"] for g in out
            ):
                self.findings.add(
                    "SOURCE_CONFLICT", "FATAL", "guard", guard["id"], "superseded-by-nothing",
                    "guard marked superseded but no guard supersedes it",
                )  # fmt: skip
        self.rule_overrides = {r.number for r in rules.values() if r.overrides} | {
            s for r in rules.values() for s in r.superseded_by
        }
        self.guard_rules = {g["id"]: g["rule"] for g in out}
        return out

    def check_rule_references(self, rules: Mapping[str, pb.Rule]) -> None:
        for guard_id in sorted(self.guard_overrides):
            number = self.guard_rules.get(guard_id)
            if number is None or number not in self.rule_overrides:
                self.findings.add(
                    "SOURCE_CONFLICT", "FATAL", "guard", guard_id, "implicit-supersession",
                    "text withheld under a rule that does not explicitly override or supersede "
                    "it: no implicit precedence",
                )  # fmt: skip
        source_id = self.mapping["roles"]["rules"]
        for reference in self.mapping["rule_references"]:
            rule = rules.get(str(reference["rule"]))
            if rule is None or reference["cited"] not in "\n".join(rule.paragraphs):
                raise MappingError(f"rule reference not found: {reference['id']}")
            ref = Ref(source_id, f"rule {rule.number}", rule.sha256)
            finding = self.findings.add(
                reference["code"], reference["severity"], "document", reference["document"],
                reference["id"], reference["detail"], (ref, self.file_ref(reference["document"])),
            )  # fmt: skip
            self.add_reference(reference["document"], {
                "source_id": source_id, "location": f"rule {rule.number}",
                "cited_id": reference["cited"], "cited_title": "",
                "resolution": reference["resolution"],
            })  # fmt: skip
            quarantine = reference.get("quarantine")
            if quarantine is not None:
                self.quarantine_route(
                    quarantine["kind"], quarantine["id"], quarantine["reason"], finding.id
                )

    # --- documents ------------------------------------------------------------------------

    def compile_documents(self, slice_ids: set[str]) -> list[dict[str, Any]]:
        mapping = self.mapping["documents"]
        missing = sorted(set(self.templates) - set(mapping))
        if missing:
            for doc in missing:
                self.findings.add(
                    "COVERAGE", "FATAL", "document", doc, "unmapped",
                    "template file not described by the mapping",
                )  # fmt: skip
        out: list[dict[str, Any]] = []
        for doc_id in sorted(mapping):
            spec = mapping[doc_id]
            template = self.templates.get(doc_id)
            if template is None:
                raise MappingError(f"mapping describes a document with no file: {doc_id}")
            workbook = self.workbook_document_conditions.get(doc_id, [])
            related = spec.get("related_conditions", workbook)
            unknown = [c for c in related if c not in slice_ids]
            if unknown:
                raise MappingError(f"{doc_id}: related conditions outside the slice: {unknown}")
            status = spec.get("status", "operational")
            if ("document", doc_id) in {(q["kind"], q["id"]) for q in self.quarantine}:
                status = "quarantined"
            out.append(
                {
                    "id": doc_id,
                    "title": template.title,
                    "kind": spec["kind"],
                    "workflow": self.mapping["workflow"]["key"],
                    "pathway": spec.get("pathway"),
                    "stages": spec.get("stages", []),
                    "options": spec.get("options", []),
                    "body_scope": spec["body_scope"],
                    "jurisdictions": spec["jurisdictions"],
                    "requires_employer_decision": spec["requires_employer_decision"],
                    "requires_completed_investigation": spec["requires_completed_investigation"],
                    "requires_employee_response": spec["requires_employee_response"],
                    "prohibited_when": spec.get("prohibited_when", []),
                    "related_conditions": related,
                    "segments": segment(
                        list(template.instructions),
                        spec.get("instruction_scope", "shared"),
                        spec.get("scope_rules", []),
                    ),
                    "references": sorted(
                        self.references.get(doc_id, []),
                        key=lambda r: (r["source_id"], r["location"], r["cited_id"]),
                    ),
                    "status": status,
                    "source_ref": self.file_ref(doc_id).data(),
                }
            )
        return out

    # --- reference data, Blueprint fields, audit sheets ---------------------------------

    def compile_reference_data(
        self, workbook: Any, slice_ids: set[str], report: dict[str, Any]
    ) -> list[dict[str, Any]]:
        settings = self.mapping["workbook"]
        source_id = self.mapping["roles"]["workbook"]
        sheet = workbook.sheet(settings["reference_sheet"])
        _, rows = wb.sheet_rows(sheet) if sheet is not None else ({}, [])
        out = []
        summary = []
        policy = settings["reference_data"]
        for row in rows:
            dataset = row.cells.get("id", "").strip()
            ref = wb.row_ref(source_id, settings["reference_sheet"], row)
            rule = policy.get(dataset)
            used = wb.split_ids(row.cells.get("used_by_conditions", ""))
            summary.append(
                {
                    "id": dataset,
                    "runtime": bool(rule and rule["runtime"]),
                    "status": row.cells.get("status", ""),
                }
            )
            if rule is None:
                self.findings.add(
                    "COVERAGE", "WARNING", "reference_data", dataset, "unmapped",
                    "reference dataset not classified by the mapping: not published", (ref,),
                )  # fmt: skip
                continue
            if not rule["runtime"]:
                self.findings.add(
                    rule.get("code", "COVERAGE"), "INFO", "reference_data", dataset, "not-runtime",
                    rule["reason"], (ref,),
                )  # fmt: skip
                continue
            scope = wb.JURISDICTION_CODES.get(row.cells.get("jurisdiction", "").strip())
            used_in_slice = [c for c in used if c in slice_ids]
            if scope is None or not used_in_slice:
                self.findings.add(
                    "INVALID_ROW", "FATAL", "reference_data", dataset, "runtime",
                    "runtime reference data needs a jurisdiction and an active runtime user",
                    (ref,),
                )  # fmt: skip
                continue
            content = row.cells.get("content", "")
            items = wb.split_numbered(content) if rule.get("split") == "numbered" else [content]
            citation = row.cells.get("status", "").strip()
            out.append(
                {
                    "id": dataset,
                    "scope": scope,
                    "title": row.cells.get("title", "").strip(),
                    "items": items,
                    "citation_status": citation
                    if citation in wb.CITATION
                    else "needs_legal_review",
                    "used_by": used_in_slice,
                    "source_ref": ref.data(),
                }
            )
        report["reference_data"] = summary
        return out

    def check_blueprint_fields(self, workbook: Any, report: dict[str, Any]) -> None:
        settings = self.mapping["workbook"]
        source_id = self.mapping["roles"]["workbook"]
        sheet = workbook.sheet(settings["blueprint_sheet"])
        _, rows = wb.sheet_rows(sheet) if sheet is not None else ({}, [])
        known = self.mapping["blueprint_fields"]
        out = []
        for row in rows:
            name = row.cells.get("field", "").strip()
            treatment = known.get(name)
            if treatment is None:
                self.findings.add(
                    "UNMAPPED_FACT", "WARNING", "blueprint_field", name, "unmapped",
                    "workbook Blueprint field has no treatment in the mapping",
                    (wb.row_ref(source_id, settings["blueprint_sheet"], row),),
                )  # fmt: skip
                continue
            out.append({"workbook_field": name, **treatment})
        report["blueprint_dependencies"] = out

    def report_audit_sheets(self, workbook: Any, report: dict[str, Any]) -> None:
        roles = self.mapping["workbook"]["sheets"]
        out = []
        for sheet in workbook.sheets:
            role = roles.get(sheet.name)
            if role is None:
                self.findings.add(
                    "UNEXPECTED_SOURCE", "WARNING", "sheet", sheet.name, "unmapped",
                    "workbook sheet has no role in the mapping: not used",
                )  # fmt: skip
            uncached = sheet.uncached_formulas()
            if uncached:
                self.findings.add(
                    "STALE_METADATA", "INFO", "sheet", sheet.name, "uncached-formulas",
                    f"{len(uncached)} formula cells have no cached value (never evaluated)",
                )  # fmt: skip
            out.append({"sheet": sheet.name, "role": role, "rows": len(sheet.rows())})
        missing = sorted(set(roles) - {s.name for s in workbook.sheets})
        for name in missing:
            self.findings.add(
                "MISSING_SOURCE", "FATAL" if roles[name] == "operational" else "WARNING",
                "sheet", name, "present", "expected workbook sheet is missing",
            )  # fmt: skip
        report["workbook_sheets"] = out

    # --- facts and options ----------------------------------------------------------------

    def compile_facts(self, conditions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = self.mapping["facts"]
        keys = {f["key"] for f in facts}
        used = {k for c in conditions for k in c["required_facts"]}
        used |= {k for u in self.mapping["units"] for k in u.get("required_facts", [])}
        for doc in self.mapping["documents"].values():
            used |= {k for j in doc["jurisdictions"].values() for k in j["gates"]}
        for option in self.mapping["options"]:
            used |= {k for j in option["jurisdictions"].values() for k in j["required_facts"]}
        unknown = sorted(used - keys)
        if unknown:
            raise MappingError(f"facts used but not in the catalog: {unknown}")
        return facts

    def compile_option(
        self, option: Mapping[str, Any], units: Sequence[Mapping[str, Any]],
        guards: Sequence[Mapping[str, Any]], conditions: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:  # fmt: skip
        """An option, with the source references of everything it rests on."""
        for code, entry in option["jurisdictions"].items():
            if entry["availability"] == "review_required":
                self.findings.add(
                    "REVIEW_REQUIRED", "INFO", "option", option["id"], f"{code}-review",
                    f"{option['kind']} in {code}: {entry['reason']}",
                )  # fmt: skip
        wanted_guards = {g for e in option["jurisdictions"].values() for g in e["guards"]}
        wanted_conditions = {c for e in option["jurisdictions"].values() for c in e["conditions"]}
        refs: list[dict[str, str]] = []
        for item in (
            [u for u in units if u["id"] in option["units"]]
            + [g for g in guards if g["id"] in wanted_guards]
            + [c for c in conditions if c["id"] in wanted_conditions]
        ):
            if item["source_ref"] not in refs:
                refs.append(item["source_ref"])
        if not refs:
            raise MappingError(f"option {option['id']} rests on no source")
        return {**option, "decided_by": "employer", "source_refs": refs}

    def jurisdiction_coverage(self, runtime: Mapping[str, Any]) -> dict[str, Any]:
        def count(items: Sequence[Mapping[str, Any]], scope: str) -> int:
            return sum(1 for i in items if i["scope"] == scope)

        coverage: dict[str, Any] = {}
        for scope in ("shared", "global", "uae_federal", "difc"):
            coverage[scope] = {
                "units": count(runtime["units"], scope),
                "conditions_active": sum(
                    1
                    for c in runtime["conditions"]
                    if c["scope"] == scope and c["enforcement_status"] == "active"
                ),  # fmt: skip
                "guards_operational": sum(
                    1
                    for g in runtime["guards"]
                    if g["scope"] == scope and g["status"] == "operational"
                ),
            }
        coverage["options"] = {
            code: {o["kind"]: o["jurisdictions"][code]["availability"] for o in runtime["options"]}
            for code in ("uae_federal", "difc")
        }
        # As a query sees it: a quarantined document is quarantined everywhere.
        coverage["documents"] = {
            code: {
                d["id"]: "quarantined"
                if d["status"] == "quarantined"
                else d["jurisdictions"][code]["status"]
                for d in runtime["documents"]
            }
            for code in ("uae_federal", "difc")
        }
        coverage["gaps"] = runtime["workflows"][0]["limitations"]
        return coverage

    # --- assembly -------------------------------------------------------------------------

    def finish(
        self, report: dict[str, Any], manifest: list[dict[str, object]],
        runtime: dict[str, Any] | None,
    ) -> CompileResult:  # fmt: skip
        mapping = self.mapping
        source_digest = source_package_digest(manifest) if manifest else None
        report["source_package_digest"] = source_digest
        bundle: dict[str, Any] | None = None
        data: bytes | None = None
        if runtime is not None and not self.findings.fatal():
            findings = [f.data() for f in self.findings.sorted()]
            counts: dict[str, Any] = {
                "findings": self.findings.counts(),
                "conditions": report["conditions"]["runtime_slice"],
            }
            bundle = {
                "schema": SCHEMA,
                "bundle": mapping["bundle"],
                "version": mapping["version"],
                "provenance": mapping["provenance"],
                "approval": mapping["approval"],
                "notice": mapping["notice"],
                "compiler": COMPILER_VERSION,
                "source_package_digest": source_digest,
                "runtime_bundle_digest": runtime_bundle_digest(runtime),
                "manifest": manifest,
                "compiler_inputs": [{"name": "mapping", "sha256": self.mapping_sha256}],
                "runtime": runtime,
                "validation": {"findings": findings, "counts": counts},
            }
            data = bundle_bytes(bundle)
            try:
                parse_knowledge_bundle(data, file_sha256="0" * 64)
            except KnowledgeBundleError as error:
                self.findings.add(
                    "INVALID_ROW", "FATAL", "bundle", error.code, error.location or "bundle",
                    f"the API's loader refuses the compiled bundle: {error.code} "
                    f"at {error.location}",
                )  # fmt: skip
                bundle, data = None, None
        report["runtime_bundle_digest"] = (
            None if bundle is None else bundle["runtime_bundle_digest"]
        )
        report["publishable"] = bundle is not None
        report["quarantine"] = sorted(self.quarantine, key=lambda q: (q["kind"], q["id"]))
        report["findings"] = [f.data() for f in self.findings.sorted()]
        report["finding_counts"] = self.findings.counts()
        report["bundle_sha256"] = None
        if data is not None:
            report["bundle_sha256"] = hashlib.sha256(data).hexdigest()
        return CompileResult(bundle, data, report, self.findings)


def compile_package(source_dir: Path, mapping_path: Path) -> CompileResult:
    """Compile ``source_dir`` with the mapping at ``mapping_path``. Reads only."""
    mapping = load_mapping(mapping_path)
    compilation = Compilation(source_dir, mapping)
    compilation.mapping_sha256 = hashlib.sha256(mapping_path.read_bytes()).hexdigest()
    return compilation.run()


def report_json(report: Mapping[str, Any]) -> bytes:
    return canonical_json(report)
