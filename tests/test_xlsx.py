"""The xlsx reader the national tables share: a sheet by name, rows as text, no spreadsheet library."""

import io
import zipfile

import pytest

from fooddb.fetchers import xlsx

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def workbook(sheets: dict[str, str], strings: list[str] | None, targets: dict[str, str]) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>' + "".join(
            f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(sheets, 1)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="x" Target="{targets[n]}"/>' for i, n in enumerate(sheets, 1))
                   + "</Relationships>")
        if strings is not None:
            z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{MAIN}">' + "".join(strings) + "</sst>")
        for n, xml in sheets.items():
            z.writestr("xl/worksheets/" + targets[n].rsplit("/", 1)[1], f'<worksheet xmlns="{MAIN}"><sheetData>{xml}</sheetData></worksheet>')
    buf.seek(0)
    return buf


STRINGS = ["<si><t>Food</t></si>", "<si><r><t>Ap</t></r><r><t>ple</t></r><rPh sb='0' eb='1'><t>furigana</t></rPh></si>"]
FIRST = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="inlineStr"><is><t>kcal</t></is></c></row>'
         '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2"><v>52.5</v></c></row>')
SECOND = '<row r="1"><c r="A1"><v>7</v></c></row>'


def test_rows_read_the_named_sheet_and_the_first_one_by_default():
    f = workbook({"Foods": FIRST, "Other": SECOND}, STRINGS,
                 {"Foods": "worksheets/sheet1.xml", "Other": "/xl/worksheets/sheet2.xml"})
    assert list(xlsx.rows(f)) == [["Food", None, "kcal"], ["Apple", "52.5"]]
    assert list(xlsx.rows(f, "Other")) == [["7"]]
    with pytest.raises(RuntimeError, match="Missing"):
        list(xlsx.rows(f, "Missing"))


def test_rows_read_a_workbook_with_no_shared_strings():
    f = workbook({"Foods": '<row r="1"><c r="B1"><v>3</v></c></row>'}, None, {"Foods": "worksheets/sheet1.xml"})
    assert list(xlsx.rows(f)) == [[None, "3"]]
