"""Excel workbooks as a stream, with no spreadsheet library: the rows of one sheet, as text."""

import re
import zipfile
from collections.abc import Iterator
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _column(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def _path(z: zipfile.ZipFile, sheet: str | None) -> str:
    """The member that holds the sheet called `sheet`, or the first sheet."""
    rid = next((s.get(RID) for s in ET.fromstring(z.read("xl/workbook.xml")).iter(f"{NS}sheet")
                if sheet is None or s.get("name") == sheet), None)
    if rid is None:
        raise RuntimeError(f"xlsx: no sheet {sheet!r}; the file layout changed")
    target = next(r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")) if r.get("Id") == rid)
    return target.lstrip("/") if target.startswith("/") else f"xl/{target}"


def _strings(z: zipfile.ZipFile) -> list[str]:
    """The shared strings. Phonetic runs (furigana) are left out."""
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    with z.open("xl/sharedStrings.xml") as f:
        return ["".join(t.text or "" for t in [*si.findall(f"{NS}t"), *si.findall(f"{NS}r/{NS}t")])
                for _, si in ET.iterparse(f) if si.tag == f"{NS}si"]


def rows(xlsx, sheet: str | None = None) -> Iterator[list[str | None]]:
    """The cells of the sheet called `sheet` (the first one by default) as text, row by row, from
    column A. A cell with no value is None. The sheet is parsed as a stream."""
    with zipfile.ZipFile(xlsx) as z:
        strings = _strings(z)
        with z.open(_path(z, sheet)) as f:
            for _, row in ET.iterparse(f):
                if row.tag != f"{NS}row":
                    continue
                cells: dict[int, str | None] = {}
                for c in row.iter(f"{NS}c"):
                    v = c.findtext(f"{NS}v")
                    kind = c.get("t")
                    cells[_column(c.get("r"))] = (
                        strings[int(v)] if kind == "s" and v is not None
                        else "".join(t.text or "" for t in c.iter(f"{NS}t")) if kind == "inlineStr" else v)
                row.clear()
                yield [cells.get(i) for i in range(max(cells, default=-1) + 1)]
