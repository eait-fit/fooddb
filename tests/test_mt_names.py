"""Structural invariants of the machine-translation name tables in ``data/names/mt/``.

Pure file parsing — no database needed, so this can never pass vacuously on an
empty test database. Enforces the contract every batch relies on:

- every ``record_id`` appears at most once per file (a duplicate row would be
  silently overwritten by ``names.py`` syncing into ``food_name``);
- each file is sorted by ``record_id`` (C locale), which keeps diffs minimal;
- every TSV carries the same record_id set per language, so ru/es coverage
  cannot drift apart.
"""

from pathlib import Path

import pytest

MT_DIR = Path(__file__).resolve().parents[1] / "data" / "names" / "mt"


def _rows(path: Path) -> list[list[str]]:
    rows = []
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        parts = line.split("\t")
        assert len(parts) == 3 and all(parts), f"{path.name}:{lineno}: expected 3 columns"
        rows.append(parts)
    return rows


def test_each_record_id_appears_once() -> None:
    for path in sorted(MT_DIR.glob("*.tsv")):
        ids = [row[0] for row in _rows(path)]
        dupes = sorted({rid for rid in ids if ids.count(rid) > 1})
        assert not dupes, f"{path.name}: duplicate record_ids: {dupes[:10]}"


def test_files_sorted_by_record_id() -> None:
    for path in sorted(MT_DIR.glob("*.tsv")):
        ids = [row[0] for row in _rows(path)]
        assert ids == sorted(ids), f"{path.name}: not sorted by record_id"


def test_all_languages_cover_the_same_record_ids() -> None:
    id_sets = {path.name: {row[0] for row in _rows(path)} for path in MT_DIR.glob("*.tsv")}
    assert len(id_sets) >= 2
    names = sorted(id_sets)
    reference = id_sets[names[0]]
    for name in names[1:]:
        missing = sorted(reference - id_sets[name])
        extra = sorted(id_sets[name] - reference)
        assert not missing and not extra, (
            f"{name} vs {names[0]}: {len(missing)} missing {missing[:5]}, {len(extra)} extra {extra[:5]}"
        )


def test_no_empty_or_header_rows() -> None:
    for path in sorted(MT_DIR.glob("*.tsv")):
        for lineno, row in enumerate(_rows(path), 1):
            assert row[0].count(":") == 1, f"{path.name}:{lineno}: bad record_id {row[0]!r}"
            assert row[2].strip(), f"{path.name}:{lineno}: empty translation"
