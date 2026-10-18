"""The offline template converter (M2-04C, phase C3), on synthetic Word documents only.

Every document here is built in memory by the tests (fictional wording; no
real template is read). Proves that:

- the reader takes only text and structure, and refuses anything that isn't a
  plain bounded document: macros, embedded or ActiveX objects, external
  relationships, DTDs and entities, unsafe or oversized parts, compression
  bombs, tracked changes, field codes, text boxes;
- the scan reports every gap and what a person must decide, writes its
  wording-bearing report only outside a git repository and prints counts only;
- a conversion maps exactly what the approved mapping says: an un-highlighted
  or partly highlighted gap is never mapped by its text alone, highlighted
  text outside brackets must be confirmed, wording changes need a recorded
  approval and can't touch a gap, and anything unsettled stops the conversion;
- every conversion is verified: the working copy turned back into text equals
  the source exactly (except approved changes and counted layout
  normalizations), and any later edit to a stored working copy is caught;
- the working copy is valid template-bundle content, and assembled copies form
  a private bundle the API's loader accepts with the synthetic rules.
"""

import copy
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pytest

from app.documents.bundle import check_against_rules, load_template_bundle
from app.documents.render import render
from app.workflows.progression.bundle import load_bundle
from scripts import template_import
from scripts.docx_reader import DocxRefused, Paragraph, Table, read_docx
from scripts.template_import import ConversionError, build_outputs, parse_mapping, scan, verify
from tests.fixtures import SYNTHETIC_BUNDLE, synthetic_bundle_pin

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" '
    'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "{extra}</Types>"
)


def r(text: str, highlight: bool = False) -> str:
    props = '<w:rPr><w:highlight w:val="yellow"/></w:rPr>' if highlight else ""
    return f'<w:r>{props}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def hl(text: str) -> str:
    return r(text, highlight=True)


def p(*runs: str, style: str | None = None, numbered: bool = False) -> str:
    props = ""
    if style or numbered:
        inner = (f'<w:pStyle w:val="{style}"/>' if style else "") + (
            '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>' if numbered else ""
        )
        props = f"<w:pPr>{inner}</w:pPr>"
    return f"<w:p>{props}{''.join(runs)}</w:p>"


def table(rows: list[list[str]]) -> str:
    cells = "".join(
        "<w:tr>" + "".join(f"<w:tc>{cell}</w:tc>" for cell in row) + "</w:tr>" for row in rows
    )
    return f"<w:tbl>{cells}</w:tbl>"


def make_docx(
    path: Path,
    body: str,
    *,
    parts: dict[str, bytes] | None = None,
    types_extra: str = "",
    document_rels: str = "",
) -> Path:
    document = (
        f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W_NS}" '
        f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<w:body>{body}<w:sectPr/></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES.format(extra=types_extra))
        archive.writestr(
            "_rels/.rels",
            f'<?xml version="1.0"?><Relationships xmlns="{REL_NS}">'
            f'<Relationship Id="rId1" Type="{OFFICE_DOC}" Target="word/document.xml"/>'
            "</Relationships>",
        )
        archive.writestr("word/document.xml", document)
        archive.writestr(
            "word/_rels/document.xml.rels",
            f'<?xml version="1.0"?><Relationships xmlns="{REL_NS}">{document_rels}</Relationships>',
        )
        for name, data in (parts or {}).items():
            archive.writestr(name, data)
    return path


# A fictional letter exercising every kind of content the converter handles.
LETTER = "".join(
    [
        p(r("User Instructions: use this synthetic test letter for testing only.")),  # 0
        p(r("[SYNTHETIC] Test letter"), style="Heading1"),  # 1
        p(hl("[Insert Date]")),  # 2
        p(r("Dear "), hl("[Employee Name]"), r(",")),  # 3
        p(
            r("[If a reminder was sent:] We refer to the test reminder of "),
            hl("[insert date]"),
            r("."),
        ),  # 4
        p(r("[If this is the first note:] This is the first test note.")),  # 5
        p(r("Points to improve:")),  # 6
        p(hl("[Insert expectation]"), numbered=True),  # 7
        p(hl("[Insert expectation]"), numbered=True),  # 8
        p(r("This sentence appears twice. This sentence appears twice.")),  # 9
        p(r("Signed: [Name of signatory]")),  # 10
        p(),  # 11 (empty: layout)
        p(r("Reference [sic] kept as written.")),  # 12
        table(
            [
                [p(r("Meeting date")), p(hl("[Meeting Date]"))],  # 13, 14
                [p(r("Attendees")), p(hl("[Names]"))],  # 15, 16
            ]
        ),
    ]
)
FIELD_SPECS = [
    {"key": "document_date", "label": "Date of the letter", "kind": "date"},
    {"key": "recipient_name", "label": "Recipient's name", "kind": "text", "max": 120},
    {"key": "reminder_date", "label": "Date of the reminder", "kind": "date"},
    {"key": "expectations", "label": "Expectations", "kind": "list", "max": 200, "items": 10},
    {"key": "signatory_name", "label": "Signatory", "kind": "text", "max": 120},
    {"key": "meeting_date", "label": "Meeting date", "kind": "date"},
    {"key": "attendees", "label": "Attendees", "kind": "text", "max": 200},
]


def mapping(source_sha256: str, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema": "heroos.template-mapping/1",
        "source_sha256": source_sha256,
        "template": {
            "key": "synthetic.converted_letter",
            "code": "TEST-09",
            "title": "Synthetic converted letter",
            "kind": "letter",
            "version": 1,
            "review": "employer",
            "jurisdictions": {"uae_federal": {"stages": ["test_check_in"]}},
        },
        "instructions": {"first": 0, "last": 0},
        "fields": {
            "[Insert Date]": "document_date",
            "[Employee Name]": "recipient_name",
            "[insert date]": "reminder_date",
            "[Insert expectation]": "expectations",
            "[Meeting Date]": "meeting_date",
            "[Names]": "attendees",
        },
        "occurrences": [
            {"paragraph": 1, "gap": "[SYNTHETIC]", "literal": True},
            {"paragraph": 10, "gap": "[Name of signatory]", "field": "signatory_name"},
            {"paragraph": 12, "gap": "[sic]", "literal": True},
        ],
        "conditionals": [
            {
                "paragraph": 4,
                "prefix": "[If a reminder was sent:] ",
                "choice": "prior",
                "options": ["reminder"],
            },
            {
                "paragraph": 5,
                "prefix": "[If this is the first note:] ",
                "choice": "prior",
                "options": ["first"],
            },
        ],
        "repeats": [{"first": 7, "last": 8, "field": "expectations"}],
        "patches": [
            {
                "paragraph": 9,
                "before": " This sentence appears twice.",
                "after": "",
                "reference": "A3/TEST-09/1",
                "approved_by": "[SYNTHETIC] Template owner",
            }
        ],
        "field_specs": FIELD_SPECS,
        "choices": [
            {
                "key": "prior",
                "label": "Earlier action",
                "multiple": False,
                "options": [
                    {"value": "reminder", "label": "A reminder was sent"},
                    {"value": "first", "label": "This is the first note"},
                ],
            }
        ],
    }
    data.update(overrides)
    return data


@pytest.fixture
def letter(tmp_path: Path) -> Path:
    return make_docx(tmp_path / "letter.docx", LETTER)


def converted(letter: Path, **overrides: Any) -> dict[str, Any]:
    document = read_docx(letter)
    return build_outputs(document, parse_mapping(mapping(document.sha256, **overrides)))


# --- reading ----------------------------------------------------------------------------


def test_the_reader_takes_text_structure_and_highlighting(letter: Path) -> None:
    document = read_docx(letter)
    assert document.sha256 == hashlib.sha256(letter.read_bytes()).hexdigest()
    paragraphs = document.paragraphs()
    assert len(paragraphs) == 17
    assert paragraphs[1].heading and paragraphs[7].list_item
    assert paragraphs[3].text == "Dear [Employee Name],"
    assert [c.highlighted for c in paragraphs[3].chars][5:20] == [True] * 15
    assert not paragraphs[10].chars[-1].highlighted
    assert isinstance(document.body[-1], Table) and isinstance(document.body[0], Paragraph)
    assert document.flags == []


def _hostile(tmp_path: Path, kind: str) -> Path:
    path = tmp_path / f"{kind}.docx"
    body = p(r("[SYNTHETIC] Text"))
    if kind == "macros":
        return make_docx(path, body, parts={"word/vbaProject.bin": b"\0" * 10})
    if kind == "macro_type":
        return make_docx(
            path,
            body,
            types_extra='<Default Extension="bin" '
            'ContentType="application/vnd.ms-office.vbaProject"/>',
        )
    if kind == "embedded":
        return make_docx(path, body, parts={"word/embeddings/oleObject1.bin": b"\0"})
    if kind == "activex":
        return make_docx(path, body, parts={"word/activeX/activeX1.xml": b"<x/>"})
    if kind == "external":
        return make_docx(
            path,
            body,
            document_rels='<Relationship Id="rId9" Type="x" Target="https://example.invalid/x" '
            'TargetMode="External"/>',
        )
    if kind == "dtd":
        return make_docx(
            path, body, parts={"word/extra.xml": b'<!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>'}
        )
    if kind == "tracked":
        return make_docx(path, f"<w:p><w:ins>{r('added')}</w:ins></w:p>")
    if kind == "fields":
        return make_docx(path, '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r></w:p>')
    if kind == "textbox":
        return make_docx(path, "<w:p><w:r><w:txbxContent/></w:r></w:p>")
    if kind == "unknown_element":
        return make_docx(path, "<w:altChunk/>")
    if kind == "traversal":
        return make_docx(path, body, parts={"../evil.xml": b"<x/>"})
    if kind == "bomb":
        return make_docx(path, body, parts={"word/padding.xml": b" " * (4 * 1024 * 1024)})
    if kind == "too_many":
        return make_docx(path, body, parts={f"word/x{i}.xml": b"<x/>" for i in range(201)})
    if kind == "not_zip":
        path.write_bytes(b"not a zip")
        return path
    raise AssertionError(kind)


@pytest.mark.parametrize(
    ("kind", "code"),
    [
        ("macros", "active_content"),
        ("macro_type", "active_content"),
        ("embedded", "active_content"),
        ("activex", "active_content"),
        ("external", "external_relationship"),
        ("dtd", "dtd_or_entities"),
        ("tracked", "tracked_changes"),
        ("fields", "field_codes"),
        ("textbox", "text_boxes"),
        ("unknown_element", "unknown_body_element"),
        ("traversal", "unsafe_part_name"),
        ("bomb", "suspicious_compression"),
        ("too_many", "too_many_parts"),
        ("not_zip", "not_docx"),
    ],
)
def test_the_reader_refuses_active_external_or_unplaceable_content(
    tmp_path: Path, kind: str, code: str
) -> None:
    with pytest.raises(DocxRefused) as refused:
        read_docx(_hostile(tmp_path, kind))
    assert refused.value.code == code


def test_headers_comments_and_images_are_flagged_for_review(tmp_path: Path) -> None:
    header = (
        f'<w:hdr xmlns:w="{W_NS}"><w:p><w:r><w:t>[SYNTHETIC] Letterhead</w:t></w:r></w:p></w:hdr>'
    )
    path = make_docx(
        tmp_path / "flags.docx",
        p(r("[SYNTHETIC] Body")),
        parts={
            "word/header1.xml": header.encode(),
            "word/comments.xml": b"<x/>",
            "word/media/image1.png": b"\x89PNG",
        },
    )
    assert read_docx(path).flags == ["comments", "header_or_footer_text", "images"]


# --- scan ---------------------------------------------------------------------------------


def test_the_scan_reports_every_gap_and_what_needs_a_decision(letter: Path) -> None:
    result = scan(read_docx(letter))
    assert result["summary"] == {
        "paragraphs": 17,
        "tables": 1,
        "gaps": 12,
        "gaps_fully_highlighted": 7,
        "gaps_partly_highlighted": 0,
        "gaps_not_highlighted": 5,
        "conditional_hints": 2,
        "instruction_hints": 0,
    }
    assert result["needs_review"] == ["gap_conditional", "gap_none_highlight"]


def test_the_scan_notes_unbalanced_brackets_and_stray_highlights(tmp_path: Path) -> None:
    path = make_docx(
        tmp_path / "odd.docx",
        p(r("Open [bracket and "), hl("highlighted words"), r(" and "), r("[par"), hl("tly]")),
    )
    result = scan(read_docx(path))
    assert result["paragraphs"][0]["notes"] == [
        "unbalanced_brackets",
        "highlighted_text_outside_brackets",
    ]
    assert result["paragraphs"][0]["gaps"][0]["marking"] == "partial"


def test_the_scan_writes_wording_only_outside_a_git_repository(
    letter: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert template_import.main(["scan", str(letter), "--out", str(repo / "out")]) == 1
    assert "output_inside_git_repository" in capsys.readouterr().err
    assert not (repo / "out").exists()

    out = tmp_path / "private"
    assert template_import.main(["scan", str(letter), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert '"gaps": 12' in printed and "Dear" not in printed and "Employee Name" not in printed
    (report,) = out.iterdir()
    assert oct(report.stat().st_mode)[-3:] == "600"
    assert "Dear [Employee Name]," in report.read_text()


# --- convert ------------------------------------------------------------------------------


def test_a_letter_converts_into_a_verified_working_copy(letter: Path) -> None:
    outputs = converted(letter)
    report = outputs["report"]
    assert report["verification"] == "PASS"
    assert (report["gaps"], report["literal_gaps"], report["confirmed_unhighlighted_gaps"]) == (
        10,
        2,
        1,
    )
    assert (report["approved_patches"], report["layout_normalizations"]) == (1, 1)
    assert report["empty_paragraphs_skipped"] == 1
    template = outputs["engine"]["template"]
    assert template["source_sha256"] == read_docx(letter).sha256
    assert template["instructions"] == [
        {
            "type": "paragraph",
            "content": [
                {"text": "User Instructions: use this synthetic test letter for testing only."}
            ],
        }
    ]
    body = template["body"]
    assert body[0] == {"type": "heading", "content": [{"text": "[SYNTHETIC] Test letter"}]}
    assert body[3]["when"] == {"choice": "prior", "in": ["reminder"]}
    assert body[3]["content"] == [
        {"text": "We refer to the test reminder of "},
        {"field": "reminder_date"},
        {"text": "."},
    ]
    repeat = next(b for b in body if b.get("repeat"))
    assert repeat == {
        "type": "item",
        "content": [{"field": "expectations"}],
        "repeat": "expectations",
    }
    assert {"text": "This sentence appears twice."} in [
        s for b in body for s in b.get("content", [])
    ]
    assert {"text": "Reference [sic] kept as written."} in [
        s for b in body for s in b.get("content", [])
    ]
    assert body[-1]["rows"][0] == [[{"text": "Meeting date"}], [{"field": "meeting_date"}]]


def test_the_working_copy_fills_like_any_template(letter: Path, tmp_path: Path) -> None:
    from app.documents.bundle import parse_template_bundle

    outputs = converted(letter)
    bundle = template_import.assemble(
        {
            "bundle": "synthetic-converted",
            "version": "synthetic.1",
            "approval": "provisional",
            "workflow": "disciplinary",
            "rule_bundle": {"bundle": "synthetic-progression", "versions": ["synthetic.1"]},
        },
        [outputs["engine"]],
    )
    parsed = parse_template_bundle(json.dumps(bundle).encode(), file_sha256="0" * 64)
    template = parsed.templates[0]
    rendered = render(
        template,
        parsed.fields,
        {"recipient_name": "[SYNTHETIC] Sam", "expectations": ("One", "Two")},
        {"prior": frozenset({"first"})},
    )
    texts = [s.text for b in rendered.blocks for s in b.segments if s.text]
    assert "[SYNTHETIC] Sam" in texts and "This is the first test note." in texts
    assert "We refer to the test reminder of " not in texts
    assert [b.segments[0].text for b in rendered.blocks if b.type == "item"] == ["One", "Two"]


def _unconfirm_signatory(m: dict[str, Any]) -> None:
    # An un-highlighted gap is never mapped by its text, even if the text is known.
    m["occurrences"] = [o for o in m["occurrences"] if o["paragraph"] != 10]
    m["fields"]["[Name of signatory]"] = "signatory_name"


OVERLAPPING_PATCH = {
    "paragraph": 3,
    "before": "Dear [Employee",
    "after": "Hi",
    "reference": "x",
    "approved_by": "x",
}
UNKNOWN_CONDITIONAL = {"paragraph": 99, "prefix": "", "choice": "prior", "options": ["first"]}


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (_unconfirm_signatory, "unconfirmed_gap"),
        (lambda m: m["fields"].pop("[Meeting Date]"), "unmapped_gap"),
        (lambda m: m["patches"][0].update(approved_by=""), "patch_not_approved"),
        (
            lambda m: m["patches"][0].update(before="Nothing like this"),
            "patch_not_found_exactly_once",
        ),
        (lambda m: m["patches"].append(OVERLAPPING_PATCH), "patch_overlaps_gap"),
        (lambda m: m.update(source_sha256="0" * 64), "source_mismatch"),
        (
            lambda m: m["conditionals"][0].update(prefix="[If else:] "),
            "conditional_prefix_not_found",
        ),
        (lambda m: m["repeats"][0].update(first=6), "repeat_paragraphs_differ"),
        (lambda m: m.update(field_specs=FIELD_SPECS[1:]), "field_without_spec"),
        (lambda m: m.update(schema="heroos.template-mapping/2"), "unsupported_mapping_schema"),
        (lambda m: m["conditionals"].append(UNKNOWN_CONDITIONAL), "unknown_paragraph"),
    ],
)
def test_anything_the_mapping_does_not_settle_stops_the_conversion(
    letter: Path, change: Any, code: str
) -> None:
    document = read_docx(letter)
    data = mapping(document.sha256)
    change(data)
    with pytest.raises(ConversionError) as refused:
        build_outputs(document, parse_mapping(data))
    assert refused.value.code == code


def test_highlighted_text_outside_brackets_must_be_confirmed_literal(tmp_path: Path) -> None:
    path = make_docx(tmp_path / "marked.docx", p(r("Keep "), hl("this"), r(" as is.")))
    document = read_docx(path)
    data = mapping(
        document.sha256,
        instructions=None,
        fields={},
        occurrences=[],
        conditionals=[],
        repeats=[],
        patches=[],
        choices=[],
        field_specs=[],
    )
    with pytest.raises(ConversionError) as refused:
        build_outputs(document, parse_mapping(data))
    assert refused.value.code == "highlighted_text_outside_brackets"
    # Confirmed literal, it stays wording (a template with no field is still valid content).
    data["literal_highlights"] = [0]
    with pytest.raises(ConversionError) as invalid:
        build_outputs(document, parse_mapping(data))
    # The bundle schema needs at least one field: the API's own parser decides.
    assert invalid.value.code == "invalid_working_copy:invalid_list"


def test_flags_must_be_acknowledged_and_invisible_characters_are_refused(tmp_path: Path) -> None:
    header = (
        f'<w:hdr xmlns:w="{W_NS}"><w:p><w:r><w:t>[SYNTHETIC] Letterhead</w:t></w:r></w:p></w:hdr>'
    )
    path = make_docx(tmp_path / "h.docx", LETTER, parts={"word/header1.xml": header.encode()})
    document = read_docx(path)
    with pytest.raises(ConversionError) as refused:
        build_outputs(document, parse_mapping(mapping(document.sha256)))
    assert (refused.value.code, refused.value.location) == (
        "unreviewed_flags",
        "header_or_footer_text",
    )
    acknowledged = mapping(document.sha256, acknowledged_flags=["header_or_footer_text"])
    assert build_outputs(document, parse_mapping(acknowledged))["report"]["verification"] == "PASS"

    hidden = make_docx(
        tmp_path / "zw.docx", LETTER.replace("Points to improve:", "Points​ to improve:")
    )
    document = read_docx(hidden)
    with pytest.raises(ConversionError) as refused:
        build_outputs(document, parse_mapping(mapping(document.sha256)))
    assert refused.value.code == "unprintable_character"


# --- verify -------------------------------------------------------------------------------


def test_any_later_edit_to_a_stored_working_copy_is_caught(letter: Path, tmp_path: Path) -> None:
    document = read_docx(letter)
    spec = parse_mapping(mapping(document.sha256))
    outputs = build_outputs(document, spec)
    engine, source_map = outputs["engine"], outputs["source_map"]
    assert verify(document, spec, engine, source_map) == []

    edited = copy.deepcopy(engine)
    edited["template"]["body"][2]["content"][0]["text"] = "Dear Sir or Madam "
    assert verify(document, spec, edited, source_map) == ["paragraph 3: text differs"]

    # A field turned into wording (or wording into a field) no longer fits its source.
    restructured = copy.deepcopy(engine)
    restructured["template"]["body"][1]["content"] = [{"text": "18 October 2026"}]
    assert verify(document, spec, restructured, source_map) == ["paragraph 2: text differs"]

    dropped = copy.deepcopy(engine)
    del dropped["template"]["body"][4]
    assert verify(document, spec, dropped, source_map) == ["body: block count differs"]

    swapped = copy.deepcopy(engine)
    body = swapped["template"]["body"]
    body[0], body[1] = body[1], body[0]
    assert verify(document, spec, swapped, source_map)

    instructions = copy.deepcopy(engine)
    instructions["template"]["instructions"][0]["content"][0]["text"] = "Anything goes."
    assert "paragraph 0: instructions differ" in verify(document, spec, instructions, source_map)


def test_the_cli_converts_and_verifies_privately(
    letter: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = read_docx(letter)
    mapping_path = tmp_path / "TEST-09.private-mapping.json"
    mapping_path.write_text(json.dumps(mapping(document.sha256)))
    out = tmp_path / "private"
    assert template_import.main(["convert", str(letter), str(mapping_path), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert '"verification": "PASS"' in printed and "Dear" not in printed
    names = sorted(path.name for path in out.iterdir())
    key = "synthetic.converted_letter"
    assert names == [
        f"{key}.conversion.json",
        f"{key}.engine.json",
        f"{key}.review.md",
        f"{key}.source-map.json",
    ]
    assert all(oct(path.stat().st_mode)[-3:] == "600" for path in out.iterdir())
    review = (out / f"{key}.review.md").read_text()
    assert (
        "Verification: **PASS**" in review
        and "| 9 |  This sentence appears twice. | (removed) | A3/TEST-09/1 |" in review
    )
    assert "- Working copy: Dear ⟦Recipient's name⟧," in review

    engine_path, source_path = out / f"{key}.engine.json", out / f"{key}.source-map.json"
    args = ["verify", str(letter), str(mapping_path), str(engine_path), str(source_path)]
    assert template_import.main(args) == 0
    assert "verification: PASS" in capsys.readouterr().out
    engine = json.loads(engine_path.read_text())
    engine["template"]["body"][2]["content"][0]["text"] = "Hi "
    engine_path.write_text(json.dumps(engine))
    assert template_import.main(args) == 1
    assert "verification: FAIL" in capsys.readouterr().out


# --- assemble -----------------------------------------------------------------------------

META = {
    "bundle": "synthetic-converted",
    "version": "synthetic.1",
    "approval": "provisional",
    "workflow": "disciplinary",
    "rule_bundle": {"bundle": "synthetic-progression", "versions": ["synthetic.1"]},
}


def test_working_copies_assemble_into_a_bundle_the_api_accepts(
    letter: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = read_docx(letter)
    out = tmp_path / "private"
    mapping_path = tmp_path / "m.json"
    mapping_path.write_text(json.dumps(mapping(document.sha256)))
    assert template_import.main(["convert", str(letter), str(mapping_path), "--out", str(out)]) == 0
    second = make_docx(
        tmp_path / "second.docx", p(r("Second test letter for ")) + p(hl("[Employee Name]"))
    )
    second_doc = read_docx(second)
    second_mapping = {
        "schema": "heroos.template-mapping/1",
        "source_sha256": second_doc.sha256,
        "template": {
            **mapping("x")["template"],
            "key": "synthetic.second_letter",
            "code": "TEST-10",
        },
        "fields": {"[Employee Name]": "recipient_name"},
        "field_specs": [FIELD_SPECS[1]],
    }
    second_path = tmp_path / "m2.json"
    second_path.write_text(json.dumps(second_mapping))
    assert template_import.main(["convert", str(second), str(second_path), "--out", str(out)]) == 0
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(META))
    engines = [
        str(out / "synthetic.converted_letter.engine.json"),
        str(out / "synthetic.second_letter.engine.json"),
    ]
    capsys.readouterr()

    target = tmp_path / "bundles" / "converted.private-templates.json"
    args = ["assemble", str(meta), *engines, "--out", str(target), "--rules", str(SYNTHETIC_BUNDLE)]
    assert template_import.main(args) == 0
    assert "templates:   TEST-09, TEST-10" in capsys.readouterr().out
    bundle = load_template_bundle(
        target, hashlib.sha256(target.read_bytes()).hexdigest(), production=False
    )
    check_against_rules(
        bundle, load_bundle(SYNTHETIC_BUNDLE, synthetic_bundle_pin(), production=False)
    )
    assert bundle.provenance == "private" and all(t.source_sha256 for t in bundle.templates)

    # The output name keeps it ignored by git, and it is never written inside a repository.
    assert (
        template_import.main(["assemble", str(meta), *engines, "--out", str(tmp_path / "b.json")])
        == 1
    )
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    inside = repo / "x.private-templates.json"
    assert template_import.main(["assemble", str(meta), *engines, "--out", str(inside)]) == 1
    assert not inside.exists()


def test_conflicting_field_definitions_are_refused() -> None:
    engine = {"template": {}, "fields": [FIELD_SPECS[1]]}
    other = {"template": {}, "fields": [{**FIELD_SPECS[1], "max": 50}]}
    with pytest.raises(ConversionError) as refused:
        template_import.assemble(META, [engine, other])
    assert refused.value.code == "conflicting_field"


# --- audit hardening ------------------------------------------------------------------------


def _patch_headers(
    path: Path, part: str, *, method: int | None = None, encrypted: bool = False
) -> None:
    """Rewrite a part's ZIP headers in place (local header and central directory)."""
    data = bytearray(path.read_bytes())
    name = part.encode()
    # (signature, flags offset, method offset, name offset)
    for signature, flags_at, method_at, name_at in (
        (b"PK\x03\x04", 6, 8, 30),
        (b"PK\x01\x02", 8, 10, 46),
    ):
        start = 0
        while (at := data.find(signature, start)) >= 0:
            if data[at + name_at : at + name_at + len(name)] == name:
                if method is not None:
                    data[at + method_at : at + method_at + 2] = method.to_bytes(2, "little")
                if encrypted:
                    data[at + flags_at] |= 0x1
            start = at + 4
    path.write_bytes(bytes(data))


def test_two_parts_with_the_same_name_are_refused(tmp_path: Path) -> None:
    path = make_docx(tmp_path / "dup.docx", p(r("[SYNTHETIC] Text")))
    with zipfile.ZipFile(path, "a") as archive, pytest.warns(UserWarning):
        archive.writestr("word/document.xml", "<x/>")
    with pytest.raises(DocxRefused) as refused:
        read_docx(path)
    assert refused.value.code == "duplicate_part"


@pytest.mark.parametrize(
    ("patch", "code"),
    [({"encrypted": True}, "encrypted_part"), ({"method": 99}, "unreadable_part")],
)
def test_encrypted_or_unreadable_parts_are_refused_not_crashed_on(
    tmp_path: Path, patch: dict[str, Any], code: str
) -> None:
    path = make_docx(
        tmp_path / "odd.docx", p(r("[SYNTHETIC] Text")), parts={"word/extra.xml": b"<x/>"}
    )
    _patch_headers(path, "word/extra.xml", **patch)
    with pytest.raises(DocxRefused) as refused:
        read_docx(path)
    assert refused.value.code == code


def test_footnote_or_endnote_text_is_flagged_but_empty_separators_are_not(tmp_path: Path) -> None:
    def notes(text: str) -> bytes:
        return f'<w:footnotes xmlns:w="{W_NS}"><w:footnote><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:footnote></w:footnotes>'.encode()  # noqa: E501

    with_text = make_docx(
        tmp_path / "n1.docx",
        p(r("[SYNTHETIC] Body")),
        parts={"word/footnotes.xml": notes("[SYNTHETIC] Note")},
    )
    empty = make_docx(
        tmp_path / "n2.docx", p(r("[SYNTHETIC] Body")), parts={"word/footnotes.xml": notes(" ")}
    )
    assert read_docx(with_text).flags == ["footnotes_or_endnotes"]
    assert read_docx(empty).flags == []


def test_pathologically_deep_nesting_is_refused(tmp_path: Path) -> None:
    deep = "<w:hyperlink>" * 40 + r("[SYNTHETIC] Deep") + "</w:hyperlink>" * 40
    path = make_docx(tmp_path / "deep.docx", f"<w:p>{deep}</w:p>")
    with pytest.raises(DocxRefused) as refused:
        read_docx(path)
    assert refused.value.code == "nesting_too_deep"


def test_nonstandard_brackets_are_noted_and_must_be_confirmed_literal(tmp_path: Path) -> None:
    path = make_docx(
        tmp_path / "fw.docx", p(r("Dear ［Employee Name］,")) + p(hl("[Employee Name]"))
    )
    document = read_docx(path)
    assert scan(document)["paragraphs"][0]["notes"] == ["nonstandard_brackets"]
    data = {
        "schema": "heroos.template-mapping/1",
        "source_sha256": document.sha256,
        "template": mapping("x")["template"],
        "fields": {"[Employee Name]": "recipient_name"},
        "field_specs": [FIELD_SPECS[1]],
    }
    with pytest.raises(ConversionError) as refused:
        build_outputs(document, parse_mapping(data))
    assert refused.value.code == "nonstandard_brackets"
    data["literal_highlights"] = [0]
    assert build_outputs(document, parse_mapping(data))["report"]["verification"] == "PASS"
