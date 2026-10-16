"""Country-specific search rewrites: a country's own food words to the names the core
sources use. `synonyms/<cc>.tsv` is the country's list — a word or phrase, a TAB, the
replacement word (more TAB-separated words are one more rewrite each). A word is a stem:
it matches inside a compound (erdäpfel in erdäpfelsalat); the longest match wins, so a
phrase or a longer word can override a stem. `expand` maps only into the source language,
never the reverse.

`expand` is pure: the query alone for a country without a list or a query that replaces
nothing, else the query plus its rewrite(s) — one per extra replacement word."""

from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent / "synonyms"


@cache
def _words(cc: str) -> dict[str, list[str]] | None:
    """The country's {lowercased word or phrase: [replacements]}, or None without a list.
    cc is only ever compared to a shipped list's name — it is never a path part itself."""
    for f in _DIR.glob("*.tsv"):
        if f.stem != cc:
            continue
        words = {}
        for line in f.read_text(encoding="utf-8").splitlines():
            if not (line := line.strip()) or line.startswith("#"):
                continue
            word, *targets = (c.strip() for c in line.split("\t"))
            if word and (targets := [t for t in targets if t]):
                words[word.lower()] = targets
        return words
    return None


def _match(words: dict[str, list[str]], lower: list[str], i: int):
    """The best synonym at position i: (span, key, targets) or None. A phrase key matches token
    for token; a single-word key first matches the whole token, then as a stem inside it.
    Longest match wins — a span of more tokens first, then the longer key."""
    best = None
    for key, targets in words.items():
        parts = key.split()
        if len(parts) > 1:
            if lower[i:i + len(parts)] != parts:
                continue
            cand = (len(parts), len(key))
        elif lower[i] == key:
            cand = (1, 10_000 + len(key))  # the whole word outranks any stem inside it
        elif key in lower[i]:
            cand = (1, len(key))
        else:
            continue
        if best is None or cand > best[:2]:
            best = (*cand, key, targets)
    if best is not None:
        return best[0], best[2], best[3]
    return None


def expand(q: str, cc: str | None) -> list[str]:
    """The query plus its rewrite for the country, only when a word was replaced."""
    if cc is None or not (words := _words(cc)):
        return [q]
    tokens = q.split()
    lower = [t.lower() for t in tokens]
    hits: dict[int, tuple[int, str, list[str]]] = {}  # start -> (end, key, targets)
    i = 0
    while i < len(tokens):
        if m := _match(words, lower, i):
            hits[i] = (i + m[0], m[1], m[2])
            i += m[0]
        else:
            i += 1
    if not hits:
        return [q]

    def render(targets_for=None) -> str:
        out, i = [], 0
        while i < len(tokens):
            if i not in hits:
                out.append(tokens[i])
                i += 1
                continue
            end, key, targets = hits[i]
            target = (targets_for or {}).get(i, targets[0])
            if end == i + 1 and key != lower[i]:
                out.append(lower[i].replace(key, target.lower()))  # a stem inside a compound
            else:
                out.append(target)
            i = end
        return " ".join(out)

    variants = [render()] + [render({start: t}) for start, (_, _, targets) in hits.items()
                             for t in targets[1:]]
    seen = {q}
    return [q] + [v for v in variants if v not in seen and not seen.add(v)]
