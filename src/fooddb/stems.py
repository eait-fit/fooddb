"""The stem fallback of name search (#161, class 2): names as language-stemmed lexemes.

The trigram path needs the query's own characters inside a name; an inflection that moved
enough letters ("Walnüsse" vs "Walnuss") or a compound the source writes as two words
("laksefilet" vs "Laks, filet") falls under its threshold and the search answers nothing.

This path stems instead: a name becomes the set of its words' snowball stems
(`to_tsvector` on `f_unaccent(name)`, one Postgres text-search config per the name's
language), and a name is a candidate when the stems of the query's words all appear among
them — "kokte gulrøtter" and "Gulrot, kokt" share {kokt, gulrot}. A word the query compounds
("laksefilet") is first split on the corpus's own stems ("laks" + "fil").

It runs only when the trigram path produced no product, so it can add recall but can never
reorder a result that exists today.
"""

import time
import unicodedata
from collections.abc import Iterable

from sqlalchemy import func, literal_column, text
from sqlalchemy.sql.elements import ColumnElement

from fooddb.db import engine

# food.lang / food_name.lang → the Postgres text-search config that stems the name. A language
# Postgres cannot stem keeps whole words under 'simple'. Keep in sync with migration 0024.
CONFIG = {
    "en": "english", "de": "german", "fr": "french", "es": "spanish", "ru": "russian",
    "uk": "russian", "nb": "norwegian", "no": "norwegian", "nn": "norwegian",
    "da": "danish", "sv": "swedish", "fi": "finnish", "it": "italian",
    "pt": "portuguese", "nl": "dutch",
}

# Every config a name can stem under; a query word is tried under all of them, so a match
# is found whichever language the name is in.
CONFIGS = tuple(dict.fromkeys(CONFIG.values())) + ("simple",)

# Countries whose users compound what the sources keep as separate words ("Laks, filet" →
# "laksefilet"): a query under one splits long tokens on the corpus's own stems.
SPLIT = {"de": "de", "at": "de", "ch": "de", "li": "de",
         "no": "nb", "dk": "da", "se": "sv", "nl": "nl", "fi": "fi", "is": "nb"}

def tsv(table) -> ColumnElement:
    """The stemmed lexeme vector of <table>.name under its own language's config: the
    IMMUTABLE f_stemtext wrapper (migration 0024) so the query uses the GIN index."""
    return func.f_stemtext(table.c.lang, table.c.name)


def tsquery(phrase: str) -> ColumnElement:
    """The phrase as a stem query: its words ANDed, each OR'd over every name config."""
    it = iter(CONFIGS)
    tsq = func.plainto_tsquery(literal_column(f"'{next(it)}'"), phrase)
    for cfg in it:
        tsq = tsq.op("||")(func.plainto_tsquery(literal_column(f"'{cfg}'"), phrase))
    return tsq


_VOCAB: dict[str, tuple[float, frozenset[str]]] = {}
VOCAB_SECONDS = 600

# The stems shorter than this never split a compound off: "en"/"er"/"ge" link inside
# half the words a corpus holds.
MIN_PART = 3


def vocab(lang: str) -> frozenset[str]:
    """The stems the corpus's names in `lang` produce — what a compound can be made of."""
    if (hit := _VOCAB.get(lang)) is not None and hit[0] > time.monotonic():
        return hit[1]
    stmt = text(
        "select lex from ("
        "select unnest(tsvector_to_array(f_stemtext(lang, name))) as lex "
        "from food_name where lang = :lang union "
        "select unnest(tsvector_to_array(f_stemtext(lang, name))) "
        "from food where lang = :lang) s")
    with engine().connect() as conn:
        words = frozenset(conn.execute(stmt, {"lang": lang}).scalars())
    _VOCAB[lang] = (time.monotonic() + VOCAB_SECONDS, words)
    return words


def reset() -> None:
    _VOCAB.clear()


def _unaccent(s: str) -> str:
    """f_unaccent for the splitter: the letters unaccent.rules folds to two, then the marks."""
    s = s.translate(str.maketrans({
        "Æ": "AE", "æ": "ae", "Ø": "O", "ø": "o", "Å": "A", "å": "a", "Œ": "OE", "œ": "oe",
        "ß": "ss", "ẞ": "SS", "Þ": "TH", "þ": "th", "Ð": "D", "ð": "d",
        "Ł": "L", "ł": "l", "Đ": "D", "đ": "d"}))
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def segment(token: str, voc: frozenset[str]) -> list[str]:
    """The corpus-stem constituents of a compound token, in order: longest match at each
    position. "laksefilet" → ["laks", "fil"], "aeggeblomme" → ["aeg", "blom"]."""
    parts, i = [], 0
    while i < len(token):
        for end in range(len(token), i + MIN_PART - 1, -1):
            if token[i:end] in voc:
                parts.append(token[i:end])
                i = end
                break
        else:
            i += 1
    return parts


def variants(q: str, cc: str | None, expanded: Iterable[str]) -> list[tuple[str, str]]:
    """(phrase, score-against) pairs for the stem legs. The expanded variants score against
    themselves; under a compounding country each long token also emits its segmentation —
    ("laksefilet" → "laks fil", "svinekjøtt" → "svin kjott" + the parts alone, "speilegg" →
    "egg") — which scores against the original query, so a loose part ("filet") never
    outranks the real split on its own similarity."""
    out = [(v, v) for v in expanded]
    if not (lang := SPLIT.get(cc or "")) or not (voc := vocab(lang)):
        return out
    seen = {v for v, _ in out}
    for v, _ in out[:]:
        tokens = v.lower().split()
        for i, token in enumerate(tokens):
            token = _unaccent(token)
            if len(token) < 6 or not (parts := segment(token, voc)):
                continue
            choices = [parts] + [[p] for p in parts]
            for words in choices:
                variant = " ".join(tokens[:i] + words + tokens[i + 1:])
                if variant not in seen:
                    seen.add(variant)
                    out.append((variant, q))
                    if len(out) >= 10:
                        return out
    return out
