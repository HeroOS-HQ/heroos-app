"""Reading an Excel (.xlsx) workbook safely, for the offline knowledge compiler (M2-NEW-04).

Offline tooling only, like ``scripts.docx_reader`` (whose archive checks it
reuses): the API never reads workbooks. The reader takes each worksheet's
cell values and nothing else, and refuses with a fixed code and a structural
location (never content):

- anything that isn't a plain, bounded ZIP (the same limits as the Word
  reader: part count and sizes, compression ratio, unsafe or duplicate part
  names, encrypted or unreadable parts);
- active or external content: macros, embedded or ActiveX objects, external
  links or relationships to external targets;
- XML with a document type declaration or entities;
- a sheet that isn't a worksheet (a chart sheet or dialog sheet) or a cell
  reference it can't place.

A formula is never evaluated: its cached value is read when the file has one,
and a formula without a cached value is reported (``Cell.formula``) so a
person can see the value is missing rather than empty.

Uses the standard library only (``zipfile``, ``xml.etree``); nothing is
written and nothing is executed.
"""

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from xml.etree import ElementTree

from scripts.docx_reader import MAX_FILE_BYTES, _check_archive, _parse

S: Final = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R: Final = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG: Final = "{http://schemas.openxmlformats.org/package/2006/relationships}"
WORKSHEET_TYPE: Final = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
)
_EXTERNAL: Final = re.compile(rb"TargetMode\s*=\s*[\"']External[\"']", re.IGNORECASE)
_MACRO_TYPES: Final = re.compile(rb"macroEnabled|vbaProject|vbaData", re.IGNORECASE)
_ACTIVE: Final = re.compile(
    r"(^|/)(vbaProject\.bin|vbaData\.xml)$|^xl/(embeddings|activeX|externalLinks)/", re.IGNORECASE
)
_CELL_REF: Final = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")
MAX_ROWS: Final = 5000
MAX_COLUMNS: Final = 64


class XlsxRefused(ValueError):
    """The workbook is refused. ``code`` is fixed; ``location`` is structural only."""

    def __init__(self, code: str, location: str = "") -> None:
        self.code = code
        self.location = location
        suffix = f" at {location}" if location else ""
        super().__init__(f"workbook refused: {code}{suffix}")


@dataclass(frozen=True, slots=True)
class Cell:
    ref: str
    column: str
    row: int
    value: str
    # The cell holds a formula (never evaluated). Its value is the cached one, or "".
    formula: bool = False


@dataclass(frozen=True, slots=True)
class Sheet:
    # Position among the workbook's sheets, in workbook order.
    index: int
    name: str
    cells: tuple[Cell, ...]

    def rows(self) -> dict[int, dict[str, str]]:
        """Row number -> column letter -> value, for the non-empty cells."""
        out: dict[int, dict[str, str]] = {}
        for cell in self.cells:
            if cell.value != "":
                out.setdefault(cell.row, {})[cell.column] = cell.value
        return out

    def uncached_formulas(self) -> tuple[str, ...]:
        return tuple(c.ref for c in self.cells if c.formula and c.value == "")


@dataclass(frozen=True, slots=True)
class Workbook:
    sha256: str
    sheets: tuple[Sheet, ...]
    # docProps/core.xml (creator, dates), as recorded inside the file.
    properties: dict[str, str]

    def sheet(self, name: str) -> Sheet | None:
        return next((s for s in self.sheets if s.name == name), None)


def _column_index(column: str) -> int:
    index = 0
    for char in column:
        index = index * 26 + (ord(char) - 64)
    return index


def _text(element: ElementTree.Element) -> str:
    return "".join(t.text or "" for t in element.iter(f"{S}t"))


def core_properties(parts: dict[str, bytes]) -> dict[str, str]:
    """The document's own core properties (``docProps/core.xml``), by local name."""
    data = parts.get("docProps/core.xml")
    if data is None:
        return {}
    root = _parse(data, "docProps/core.xml")
    properties: dict[str, str] = {}
    for child in root:
        name = child.tag.rsplit("}", 1)[-1]
        if child.text and child.text.strip():
            properties[name] = child.text.strip()
    return properties


def _sheet_cells(root: ElementTree.Element, name: str, strings: list[str]) -> tuple[Cell, ...]:
    data = root.find(f"{S}sheetData")
    cells: list[Cell] = []
    if data is None:
        return ()
    rows = data.findall(f"{S}row")
    if len(rows) > MAX_ROWS:
        raise XlsxRefused("too_many_rows", name)
    for row in rows:
        for cell in row.findall(f"{S}c"):
            ref = cell.get("r", "")
            match = _CELL_REF.fullmatch(ref)
            if match is None:
                raise XlsxRefused("invalid_cell_reference", name)
            column, number = match.group(1), int(match.group(2))
            if _column_index(column) > MAX_COLUMNS:
                raise XlsxRefused("too_many_columns", name)
            kind = cell.get("t")
            value_element = cell.find(f"{S}v")
            raw = "" if value_element is None or value_element.text is None else value_element.text
            if kind == "s":
                try:
                    value = strings[int(raw)]
                except (ValueError, IndexError) as error:
                    raise XlsxRefused("invalid_shared_string", f"{name}!{ref}") from error
            elif kind == "inlineStr":
                inline = cell.find(f"{S}is")
                value = "" if inline is None else _text(inline)
            elif kind == "b":
                value = {"1": "TRUE", "0": "FALSE"}.get(raw, raw)
            else:
                value = raw
            formula = cell.find(f"{S}f") is not None
            cells.append(Cell(ref, column, number, value, formula))
    return tuple(cells)


def read_xlsx(path: Path) -> Workbook:
    """Every worksheet's cell values, or ``XlsxRefused``. Never writes, evaluates or runs code."""
    try:
        content = path.read_bytes()
    except OSError as error:
        raise XlsxRefused("unreadable") from error
    if len(content) > MAX_FILE_BYTES:
        raise XlsxRefused("too_large")
    sha256 = hashlib.sha256(content).hexdigest()
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as error:
        raise XlsxRefused("not_xlsx") from error
    try:
        with archive:
            parts = _check_archive(archive)
    except ValueError as error:
        # The Word reader's refusal codes are the same archive checks.
        raise XlsxRefused(getattr(error, "code", "unreadable_part")) from error
    for required in ("[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"):
        if required not in parts:
            raise XlsxRefused("not_xlsx", required)
    if _MACRO_TYPES.search(parts["[Content_Types].xml"]):
        raise XlsxRefused("active_content", "[Content_Types].xml")
    for name, data in parts.items():
        if _ACTIVE.search(name):
            raise XlsxRefused("active_content", name)
        if name.endswith(".rels") and _EXTERNAL.search(data):
            raise XlsxRefused("external_relationship", name)
    try:
        strings: list[str] = []
        if "xl/sharedStrings.xml" in parts:
            shared = _parse(parts["xl/sharedStrings.xml"], "xl/sharedStrings.xml")
            strings = [_text(item) for item in shared.findall(f"{S}si")]
        workbook = _parse(parts["xl/workbook.xml"], "xl/workbook.xml")
        relationships = _parse(parts["xl/_rels/workbook.xml.rels"], "xl/_rels/workbook.xml.rels")
        properties = core_properties(parts)
    except ValueError as error:
        location = str(getattr(error, "location", ""))
        raise XlsxRefused(getattr(error, "code", "invalid_xml"), location) from error
    targets = {
        rel.get("Id"): (rel.get("Type"), rel.get("Target", ""))
        for rel in relationships.findall(f"{PKG}Relationship")
    }
    container = workbook.find(f"{S}sheets")
    sheets: list[Sheet] = []
    for index, entry in enumerate([] if container is None else list(container)):
        name = entry.get("name", "")
        kind, target = targets.get(entry.get(f"{R}id"), (None, ""))
        if kind != WORKSHEET_TYPE:
            raise XlsxRefused("not_a_worksheet", f"sheet {index}")
        part = target.lstrip("/")
        part = part if part.startswith("xl/") else f"xl/{part}"
        if part not in parts:
            raise XlsxRefused("missing_sheet_part", f"sheet {index}")
        try:
            root = _parse(parts[part], part)
        except ValueError as error:
            raise XlsxRefused(getattr(error, "code", "invalid_xml"), part) from error
        sheets.append(Sheet(index, name, _sheet_cells(root, f"sheet {index}", strings)))
    if len({s.name for s in sheets}) != len(sheets):
        raise XlsxRefused("duplicate_sheet_name")
    return Workbook(sha256, tuple(sheets), properties)
