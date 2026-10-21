"""The offline readers: XLSX cell values, and nested tables in DOCX (M2-NEW-04)."""

import zipfile
from pathlib import Path

import pytest

from scripts.docx_reader import DocxRefused, read_docx
from scripts.xlsx_reader import XlsxRefused, read_xlsx
from tests.fixtures.knowledge import synthetic


def test_a_workbook_reads_every_sheet_in_order_with_inline_strings(tmp_path: Path) -> None:
    path = tmp_path / "book.xlsx"
    synthetic.write_xlsx(path, {"First": [["a", "b"], ["1", ""]], "Second": [["x"]]})
    workbook = read_xlsx(path)
    assert [s.name for s in workbook.sheets] == ["First", "Second"]
    assert workbook.sheet("First") is not None
    assert workbook.sheets[0].rows() == {1: {"A": "a", "B": "b"}, 2: {"A": "1"}}


def test_shared_strings_and_uncached_formulas_are_read_but_never_evaluated(tmp_path: Path) -> None:
    path = tmp_path / "book.xlsx"
    synthetic.write_xlsx(path, {"S": [["x"]]})
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<si><t>shared</t></si></sst>",
        )
    data = {n: zipfile.ZipFile(path).read(n) for n in zipfile.ZipFile(path).namelist()}
    data["xl/worksheets/sheet1.xml"] = (
        b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        b'<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><f>SUM(A1:A9)</f></c></row>'
        b"</sheetData></worksheet>"
    )
    rebuilt = tmp_path / "rebuilt.xlsx"
    with zipfile.ZipFile(rebuilt, "w") as archive:
        for name, content in data.items():
            archive.writestr(name, content)
    sheet = read_xlsx(rebuilt).sheets[0]
    assert sheet.rows() == {1: {"A": "shared"}}
    assert sheet.uncached_formulas() == ("B1",)


@pytest.mark.parametrize(
    ("part", "code"),
    [
        ("xl/vbaProject.bin", "active_content"),
        ("xl/externalLinks/externalLink1.xml", "active_content"),
    ],
)
def test_active_or_external_workbook_content_is_refused(
    tmp_path: Path, part: str, code: str
) -> None:
    path = tmp_path / "book.xlsx"
    synthetic.write_xlsx(path, {"S": [["x"]]})
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(part, b"x")
    with pytest.raises(XlsxRefused) as refused:
        read_xlsx(path)
    assert refused.value.code == code


def test_a_workbook_with_a_dtd_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "book.xlsx"
    synthetic.write_xlsx(path, {"S": [["x"]]})
    data = {n: zipfile.ZipFile(path).read(n) for n in zipfile.ZipFile(path).namelist()}
    data["xl/workbook.xml"] = b'<!DOCTYPE x [<!ENTITY a "b">]>' + data["xl/workbook.xml"]
    rebuilt = tmp_path / "dtd.xlsx"
    with zipfile.ZipFile(rebuilt, "w") as archive:
        for name, content in data.items():
            archive.writestr(name, content)
    with pytest.raises(XlsxRefused) as refused:
        read_xlsx(rebuilt)
    assert refused.value.code == "dtd_or_entities"


def test_nested_tables_are_refused_for_templates_and_flattened_for_knowledge(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested.docx"
    synthetic.write_docx(path, [synthetic._table(["Outer"], nested=["Inner one", "Inner two"])])
    with pytest.raises(DocxRefused) as refused:
        read_docx(path)
    assert refused.value.code == "nested_tables"
    texts = [p.text for p in read_docx(path, nested_tables=True).paragraphs() if p.text]
    assert texts == ["Outer", "Inner one", "Inner two"]
