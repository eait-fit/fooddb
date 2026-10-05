"""Automatic checks run on every incoming record. They flag, they never fix."""

from collections.abc import Mapping

MACROS = ("PROCNT", "FAT", "CHOCDF")


def flags(values: Mapping[str, float]) -> dict[str, set[str]]:
    """Values are per 100 g, keyed by INFOODS tagname. Each failed check names the fields it implicates."""
    out: dict[str, set[str]] = {}
    kcal = values.get("ENERC_KCAL")
    p, f, c = values.get("PROCNT"), values.get("FAT"), values.get("CHOCDF")
    if kcal is not None and None not in (p, f, c):
        atwater = 4 * p + 9 * f + 4 * c
        if abs(kcal - atwater) > max(20, 0.25 * max(kcal, atwater)):
            out["energy-mismatch"] = {"ENERC_KCAL", *MACROS}
    if sum(v for v in (p, f, c) if v is not None) > 105:
        out["macros-over-100g"] = {k for k in MACROS if k in values}
    sugar, sat = values.get("SUGAR"), values.get("FASAT")
    if sugar is not None and c is not None and sugar > c + 0.5:
        out["sugars-over-carbs"] = {"SUGAR", "CHOCDF"}
    if sat is not None and f is not None and sat > f + 0.5:
        out["saturates-over-fat"] = {"FASAT", "FAT"}
    if negative := {k for k, v in values.items() if v < 0}:
        out["negative-value"] = negative
    return out
