"""?country= ranking: the sources a search in a country prefers.

A preference, never a filter: among results of comparable name similarity a record of a
preferred source wins, and it never outranks a much better name match. Without `country`,
the order is unchanged. A code the map does not know is refused (422), not silently ignored.
"""

from fastapi import HTTPException

# ISO 3166-1 alpha-2 → the sources preferred there, earlier first; every listed source ranks
# above an unlisted one. A second source for a country is one more entry in its list.
# "off": an OFF record joins the end of the list when its countries_tags (food.markets) name
# the country — those tags are the taxonomy's "en:" names.
COUNTRIES: dict[str, dict[str, tuple[str, ...]]] = {
    "de": {"sources": ("bls",), "off": ("en:germany",)},
    "at": {"sources": ("bls",), "off": ("en:austria",)},
    "fr": {"sources": ("ciqual",), "off": ("en:france",)},
    "gb": {"sources": ("cofid",), "off": ("en:united-kingdom",)},
    "ie": {"sources": ("cofid",), "off": ("en:ireland",)},
    "fi": {"sources": ("fineli",), "off": ("en:finland",)},
    "no": {"sources": ("matvaretabellen",), "off": ("en:norway",)},
    "dk": {"sources": ("frida",), "off": ("en:denmark",)},
    "jp": {"sources": ("mext",), "off": ("en:japan",)},
    "tw": {"sources": ("tfda",), "off": ("en:taiwan",)},
    "us": {"sources": ("fdc",), "off": ("en:united-states",)},
}


def code(country: str | None) -> str | None:
    """The normalized code, or None when no country was asked for. An unknown code is a 422."""
    if country is None:
        return None
    cc = country.strip().lower()
    if cc not in COUNTRIES:
        raise HTTPException(422, f"country: {country!r} is not a known ISO 3166-1 alpha-2 code")
    return cc


def rank_sql(cc: str) -> str:
    """A record's rank for the country's ordering: listed sources by position, an OFF record
    sold there just below them, and everything else last. Used inside `min(...)`, grouped by
    product, so any preferred record of a product counts."""
    sources = COUNTRIES[cc]["sources"]
    n = len(sources)
    cases = " ".join(f"when '{s}' then {i}" for i, s in enumerate(sources))
    return (f"case source {cases} when 'off' then "
            f"case when :off_markets && markets then {n} else {n + 1} end "
            f"else {n + 1} end")


def off_markets(cc: str) -> list[str]:
    return list(COUNTRIES[cc]["off"])
