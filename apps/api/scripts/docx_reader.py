"""Reading a Word (.docx) template safely, for the offline template converter (M2-04C).

Offline tooling only: the API never reads Word files (only ``app/`` is in its
image). The reader takes the main document's text and structure (paragraphs,
runs with their highlighting, headings, list items, tables) and nothing else.
It refuses, with a fixed code and a structural location (never wording):

- anything that isn't a plain, bounded ZIP: more than 200 parts, a part
  larger than 5 MiB or 20 MiB in all, a suspicious compression ratio, an
  absolute or ``..`` part name, two parts with the same name, an encrypted
  or otherwise unreadable part;
- active or external content: macros (``vbaProject.bin``, macro-enabled
  content types), embedded or ActiveX objects, relationships to external
  targets;
- XML with a document type declaration or entities (no DTD is ever parsed);
- content the converter can't place with certainty: tracked changes, field
  codes, text boxes, unknown body elements, nesting deeper than 32 levels.

Things a person must look at (text in headers or footers, footnotes or
endnotes, comments, images, symbol characters) are reported as flags, never
silently dropped.

Uses the standard library only (``zipfile``, ``xml.etree``); nothing is
written and nothing is executed.
"""

import hashlib
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from xml.etree import ElementTree

MAX_FILE_BYTES: Final = 10 * 1024 * 1024
MAX_PARTS: Final = 200
MAX_PART_BYTES: Final = 5 * 1024 * 1024
MAX_TOTAL_BYTES: Final = 20 * 1024 * 1024
MAX_RATIO: Final = 200
MAX_DEPTH: Final = 32

W: Final = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DOCUMENT_PART: Final = "word/document.xml"
_DTD: Final = re.compile(rb"<!DOCTYPE|<!ENTITY", re.IGNORECASE)
_EXTERNAL: Final = re.compile(rb"TargetMode\s*=\s*[\"']External[\"']", re.IGNORECASE)
_MACRO_TYPES: Final = re.compile(rb"macroEnabled|vbaProject|vbaData", re.IGNORECASE)
_ACTIVE_PARTS: Final = re.compile(
    r"(^|/)(vbaProject\.bin|vbaData\.xml)$|^word/(embeddings|activeX)/", re.IGNORECASE
)
# Elements whose content isn't plain flowing text the converter can place.
# Inline containers whose runs are part of the paragraph's text.
_CONTAINERS: Final = (f"{W}hyperlink", f"{W}smartTag", f"{W}sdt", f"{W}sdtContent", f"{W}customXml")
_REFUSED: Final[dict[str, str]] = {
    f"{W}ins": "tracked_changes",
    f"{W}del": "tracked_changes",
    f"{W}moveFrom": "tracked_changes",
    f"{W}moveTo": "tracked_changes",
    f"{W}fldChar": "field_codes",
    f"{W}instrText": "field_codes",
    f"{W}fldSimple": "field_codes",
    f"{W}txbxContent": "text_boxes",
    f"{W}object": "embedded_objects",
}


class DocxRefused(ValueError):
    """The document is refused. ``code`` is fixed; ``location`` is structural only."""

    def __init__(self, code: str, location: str = "") -> None:
        self.code = code
        self.location = location
        suffix = f" at {location}" if location else ""
        super().__init__(f"document refused: {code}{suffix}")


@dataclass(frozen=True, slots=True)
class Char:
    """One character of a paragraph and whether it was highlighted (a placeholder mark)."""

    char: str
    highlighted: bool


@dataclass(frozen=True, slots=True)
class Paragraph:
    # Position among the document's paragraphs (body and table cells), in order.
    index: int
    chars: tuple[Char, ...]
    heading: bool
    list_item: bool
    # (table, row, cell) for a paragraph inside a table; None in the body.
    cell: tuple[int, int, int] | None = None

    @property
    def text(self) -> str:
        return "".join(c.char for c in self.chars)


@dataclass(frozen=True, slots=True)
class Table:
    index: int
    # rows of cells of paragraphs
    rows: tuple[tuple[tuple[Paragraph, ...], ...], ...]


@dataclass(slots=True)
class Document:
    sha256: str
    # The body in order: paragraphs and tables.
    body: list[Paragraph | Table]
    # Things a person must review (codes only).
    flags: list[str] = field(default_factory=list)

    def paragraphs(self) -> list[Paragraph]:
        out: list[Paragraph] = []
        for item in self.body:
            if isinstance(item, Paragraph):
                out.append(item)
            else:
                out += [p for row in item.rows for cell in row for p in cell]
        return out


def _parse(data: bytes, name: str) -> ElementTree.Element:
    if _DTD.search(data):
        raise DocxRefused("dtd_or_entities", name)
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise DocxRefused("invalid_xml", name) from error


def _check_archive(archive: zipfile.ZipFile) -> dict[str, bytes]:
    infos = archive.infolist()
    if len(infos) > MAX_PARTS:
        raise DocxRefused("too_many_parts")
    names = [info.filename for info in infos]
    if len(set(names)) != len(names):
        # Which of two same-named parts a reader takes is ambiguous: refuse.
        raise DocxRefused("duplicate_part")
    total = 0
    parts: dict[str, bytes] = {}
    for info in infos:
        name = info.filename
        if name.startswith(("/", "\\")) or "\\" in name or ".." in name.split("/") or ":" in name:
            raise DocxRefused("unsafe_part_name")
        if info.file_size > MAX_PART_BYTES:
            raise DocxRefused("part_too_large")
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise DocxRefused("too_large")
        if info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
            raise DocxRefused("suspicious_compression")
        if _ACTIVE_PARTS.search(name):
            raise DocxRefused("active_content")
        if info.is_dir():
            continue
        if info.flag_bits & 0x1:
            raise DocxRefused("encrypted_part")
        try:
            with archive.open(info) as handle:
                data = handle.read(MAX_PART_BYTES + 1)
        except (
            RuntimeError,
            NotImplementedError,
            zipfile.BadZipFile,
            zlib.error,
            OSError,
        ) as error:
            raise DocxRefused("unreadable_part") from error
        if len(data) > MAX_PART_BYTES:
            raise DocxRefused("part_too_large")
        parts[name] = data
    return parts


def _highlighted(run: ElementTree.Element) -> bool:
    props = run.find(f"{W}rPr")
    if props is None:
        return False
    mark = props.find(f"{W}highlight")
    if mark is not None and mark.get(f"{W}val", "none") != "none":
        return True
    shade = props.find(f"{W}shd")
    fill = None if shade is None else shade.get(f"{W}fill")
    return fill is not None and fill.lower() not in ("auto", "ffffff", "")


def _run_chars(run: ElementTree.Element, where: str, flags: list[str]) -> list[Char]:
    marked = _highlighted(run)
    chars: list[Char] = []
    for child in run:
        refused = next(
            (
                code
                for tag, code in _REFUSED.items()
                if child.tag == tag or child.find(f".//{tag}") is not None
            ),
            None,
        )
        if refused is not None:
            raise DocxRefused(refused, where)
        if child.tag == f"{W}t":
            chars += [Char(c, marked) for c in child.text or ""]
        elif child.tag == f"{W}tab":
            chars.append(Char("\t", marked))
        elif child.tag in (f"{W}br", f"{W}cr"):
            chars.append(Char("\n", marked))
        elif child.tag == f"{W}noBreakHyphen":
            chars.append(Char("-", marked))
        elif child.tag == f"{W}softHyphen":
            continue
        elif child.tag == f"{W}sym":
            flags.append("symbol_characters")
        elif child.tag in (f"{W}drawing", f"{W}pict"):
            flags.append("images")
    return chars


def _paragraph_chars(paragraph: ElementTree.Element, where: str, flags: list[str]) -> list[Char]:
    chars: list[Char] = []

    def walk(element: ElementTree.Element, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise DocxRefused("nesting_too_deep", where)
        for child in element:
            refused = _REFUSED.get(child.tag)
            if refused is not None:
                raise DocxRefused(refused, where)
            if child.tag == f"{W}r":
                chars.extend(_run_chars(child, where, flags))
            elif child.tag in _CONTAINERS:
                walk(child, depth + 1)
            # Properties, bookmarks, proofing marks and comment anchors carry no text.

    walk(paragraph, 0)
    return chars


def _style(paragraph: ElementTree.Element) -> tuple[bool, bool]:
    props = paragraph.find(f"{W}pPr")
    if props is None:
        return False, False
    style = props.find(f"{W}pStyle")
    name = "" if style is None else style.get(f"{W}val", "")
    heading = name.lower().startswith(("heading", "title"))
    return heading, props.find(f"{W}numPr") is not None


def read_docx(path: Path) -> Document:
    """The document's text and structure, or ``DocxRefused``. Never writes or runs anything."""
    try:
        content = path.read_bytes()
    except OSError as error:
        raise DocxRefused("unreadable") from error
    if len(content) > MAX_FILE_BYTES:
        raise DocxRefused("too_large")
    sha256 = hashlib.sha256(content).hexdigest()
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as error:
        raise DocxRefused("not_docx") from error
    with archive:
        parts = _check_archive(archive)
    if DOCUMENT_PART not in parts or "[Content_Types].xml" not in parts:
        raise DocxRefused("not_docx")
    if _MACRO_TYPES.search(parts["[Content_Types].xml"]):
        raise DocxRefused("active_content", "[Content_Types].xml")
    flags: list[str] = []
    for name, data in parts.items():
        if name.endswith(".rels") and _EXTERNAL.search(data):
            raise DocxRefused("external_relationship", name)
        if name.endswith((".xml", ".rels")) and _DTD.search(data):
            raise DocxRefused("dtd_or_entities", name)
        if re.fullmatch(r"word/(header|footer)\d*\.xml", name):
            root = _parse(data, name)
            if "".join(t.text or "" for t in root.iter(f"{W}t")).strip():
                flags.append("header_or_footer_text")
        if name in ("word/comments.xml", "word/commentsExtended.xml"):
            flags.append("comments")
        if name in ("word/footnotes.xml", "word/endnotes.xml"):
            root = _parse(data, name)
            if "".join(t.text or "" for t in root.iter(f"{W}t")).strip():
                flags.append("footnotes_or_endnotes")
        if name.startswith("word/media/"):
            flags.append("images")

    root = _parse(parts[DOCUMENT_PART], DOCUMENT_PART)
    body = root.find(f"{W}body")
    if body is None:
        raise DocxRefused("not_docx", DOCUMENT_PART)
    items: list[Paragraph | Table] = []
    counter = {"paragraph": 0, "table": 0}

    def paragraph(element: ElementTree.Element, cell: tuple[int, int, int] | None) -> Paragraph:
        index = counter["paragraph"]
        counter["paragraph"] += 1
        heading, list_item = _style(element)
        chars = _paragraph_chars(element, f"paragraph {index}", flags)
        return Paragraph(index, tuple(chars), heading, list_item, cell)

    def visit(element: ElementTree.Element, depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            raise DocxRefused("nesting_too_deep", "body")
        for child in element:
            if child.tag == f"{W}p":
                items.append(paragraph(child, None))
            elif child.tag == f"{W}tbl":
                t = counter["table"]
                counter["table"] += 1
                rows = []
                for r, row in enumerate(child.findall(f"{W}tr")):
                    cells = []
                    for c, cell in enumerate(row.findall(f"{W}tc")):
                        for nested in cell:
                            if nested.tag == f"{W}tbl":
                                raise DocxRefused("nested_tables", f"table {t}")
                        cells.append(tuple(paragraph(p, (t, r, c)) for p in cell.findall(f"{W}p")))
                    rows.append(tuple(cells))
                items.append(Table(t, tuple(rows)))
            elif child.tag in (f"{W}sdt", f"{W}sdtContent", f"{W}customXml"):
                visit(child, depth + 1)
            elif child.tag in (
                f"{W}sectPr",
                f"{W}bookmarkStart",
                f"{W}bookmarkEnd",
                f"{W}proofErr",
            ):
                continue
            elif child.tag in _REFUSED:
                raise DocxRefused(_REFUSED[child.tag], "body")
            else:
                raise DocxRefused("unknown_body_element", "body")

    visit(body)
    return Document(sha256, items, sorted(set(flags)))
